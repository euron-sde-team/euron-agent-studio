"""Every template runs end to end, offline: the real engine, offline model and sandbox."""

import uuid
from collections import Counter
from typing import Any

import pytest

from agentstudio.core.config import Settings
from agentstudio.core.text import content_terms
from agentstudio.engine.executor import Executor, Limits
from agentstudio.engine.graph import GraphDocument
from agentstudio.engine.plan import build_plan
from agentstudio.engine.ports import EngineServices
from agentstudio.engine.recorder import MemoryRecorder
from agentstudio.engine.validate import validate_graph
from agentstudio.ingestion.chunker import chunk_document, title_of
from agentstudio.integrations.http import GuardedHttpClient, NetworkPolicy
from agentstudio.integrations.sandbox import create_sandbox_app
from agentstudio.providers.registry import ModelRegistry
from agentstudio.templates import (
    TEMPLATES,
    bind_knowledge,
    get_template,
    knowledge_documents,
    knowledge_names,
)
from tests.unit.helpers import FakeCancel


class MemoryKnowledge:
    """Keyword search over the bundled documents, standing in for Postgres full-text search."""

    def __init__(self) -> None:
        self.chunks: dict[uuid.UUID, list[dict[str, Any]]] = {}

    def load(self, name: str) -> uuid.UUID:
        spec = next(k for t in TEMPLATES for k in t.knowledge if k.name == name)
        kb_id = uuid.uuid4()
        rows: list[dict[str, Any]] = []
        for filename, data in knowledge_documents(spec):
            text = data.decode()
            title = title_of(text, filename)
            rows.extend(
                {"title": title, "heading": chunk.heading, "text": chunk.text}
                for chunk in chunk_document(text, title=title)
            )
        self.chunks[kb_id] = rows
        return kb_id

    async def search(self, kb_id: uuid.UUID, query: str, top_k: int) -> list[dict[str, Any]]:
        wanted = set(content_terms(query))
        scored = []
        for row in self.chunks[kb_id]:
            terms = Counter(content_terms(row["heading"] + " " + row["text"]))
            score = sum(terms[term] for term in wanted)
            if score:
                scored.append((score, row))
        scored.sort(key=lambda pair: -pair[0])
        return [{**row, "snippet": row["text"][:120], "score": s} for s, row in scored[:top_k]]


async def run_template(
    slug: str, inputs: dict[str, Any] | None = None
) -> tuple[Any, MemoryRecorder]:
    template = get_template(slug)
    assert template is not None
    knowledge = MemoryKnowledge()
    ids = {name: knowledge.load(name) for name in knowledge_names(template.graph)}
    document = GraphDocument.model_validate(bind_knowledge(template.graph, ids))
    http = GuardedHttpClient(NetworkPolicy(), sandbox=create_sandbox_app())
    recorder = MemoryRecorder()
    services = EngineServices(
        models=ModelRegistry(Settings(), None), knowledge=knowledge, http=http, cancel=FakeCancel()
    )
    executor = Executor(build_plan(document), services, recorder, limits=Limits(cancel_poll_s=0.05))
    result = await executor.execute(inputs or template.sample)
    await http.aclose()
    return result, recorder


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda t: t.slug)
def test_every_template_is_a_valid_flow(template: Any) -> None:
    names = knowledge_names(template.graph)
    assert names == [k.name for k in template.knowledge]
    bound = bind_knowledge(template.graph, {name: uuid.uuid4() for name in names})
    assert validate_graph(GraphDocument.model_validate(bound)) == []
    assert all(knowledge_documents(spec) for spec in template.knowledge)


async def test_support_triage_pauses_for_review_with_a_drafted_reply() -> None:
    result, recorder = await run_template("support-triage")
    assert result.status == "waiting"
    assert result.waiting_on == ["approve"]
    classified = recorder.output_of("classify")["json"]
    assert (classified["category"], classified["priority"]) == ("billing", "high")
    approval = recorder.approvals[0]
    assert approval.title == "Review reply: Charged twice for the March invoice"
    assert approval.message.startswith("Hi Dana,")
    assert "within 5 business days" in approval.message
    assert recorder.status_of("auto_reply") == "skipped"


async def test_support_triage_answers_low_priority_tickets_automatically() -> None:
    result, _ = await run_template(
        "support-triage",
        {
            "subject": "How do I export a report?",
            "body": "Hello, quick question: how can I export the weekly report to CSV? Thanks, Tom",
            "customer_email": "tom.becker@brightside.example",
        },
    )
    assert result.status == "succeeded"
    assert result.outputs["status"] == "auto-replied"
    assert result.outputs["reply"].startswith("Hi Tom,")


async def test_invoice_extraction_posts_a_clean_invoice() -> None:
    result, _ = await run_template("invoice-extraction")
    assert result.status == "succeeded"
    assert result.outputs["status"] == "posted"
    assert result.outputs["record"] == {
        "vendor": "Acme Office Supplies Ltd",
        "invoice_number": "AOS-2026-0417",
        "issued": "2026-03-03",
        "due": "2026-04-02",
        "currency": "GBP",
        "total": 4232.4,
        "lines": 3,
    }


async def test_invoices_that_do_not_add_up_go_to_review() -> None:
    template = get_template("invoice-extraction")
    assert template is not None
    wrong = template.sample["invoice_text"].replace("4,232.40", "4,323.40")
    result, recorder = await run_template("invoice-extraction", {"invoice_text": wrong})
    assert result.status == "waiting"
    assert "Arithmetic difference: -91" in recorder.approvals[0].message


async def test_research_brief_answers_every_question_with_citations() -> None:
    result, recorder = await run_template("research-brief")
    assert result.status == "succeeded"
    assert result.outputs["questions_answered"] == 3
    brief = result.outputs["brief"]
    assert brief.startswith("# Rolling out the new remote work policy")
    assert brief.count("- **What") == 3
    assert "[1]" in brief
    assert sorted(s.iteration for s in recorder.finished if s.node_id == "answer") == [
        "0",
        "1",
        "2",
    ]


async def test_lead_qualification_prices_hot_leads_with_its_tools() -> None:
    result, recorder = await run_template("lead-qualification")
    assert result.status == "succeeded"
    assert result.outputs["tier"] == "hot"
    assert result.outputs["score"] == 74
    assert "For 120 seats, that comes to $56,160 per year." in result.outputs["email"]
    tools = [event["name"] for (node, _, event) in recorder.events if event["type"] == "tool_call"]
    assert tools == ["product_docs", "calculator"]


async def test_lead_qualification_nurtures_small_leads() -> None:
    result, _ = await run_template(
        "lead-qualification",
        {
            "name": "Tom Becker",
            "email": "tom@brightside.example",
            "company": "Brightside Bakery",
            "message": (
                "Just curious what your tool does. "
                "We are a small team and not ready to buy anything yet."
            ),
        },
    )
    assert result.outputs["tier"] == "nurture"
    assert result.outputs["email"].startswith("Hi Tom,")


async def test_meeting_notes_become_tasks() -> None:
    result, _ = await run_template("meeting-actions")
    assert result.status == "succeeded"
    assert result.outputs["task_count"] == 4
    assert all(task.startswith("TSK-") for task in result.outputs["tasks"])
    assert result.outputs["decisions"] == [
        "We decided to open the beta to 40 design partners on March 16."
    ]
    assert result.outputs["summary"].count("\n- ") == 2


async def test_policy_assistant_answers_from_the_handbook() -> None:
    result, _ = await run_template("policy-assistant")
    assert result.outputs == {
        "answer": (
            "Full-time employees receive 25 days of paid vacation per year, "
            "plus public holidays [1]."
        ),
        "tools_used": 1,
    }
