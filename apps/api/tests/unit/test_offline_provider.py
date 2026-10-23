import json
from typing import Any

from agentstudio.engine import runtime
from agentstudio.providers.base import ChatRequest
from agentstudio.providers.offline import OfflineProvider, respond
from agentstudio.providers.offline.summarize import action_items, decisions
from tests.unit.offline_samples import ARTICLES, HANDBOOK, INVOICE, NOTES, PRICING, TICKET

TRIAGE_FIELDS = [
    {"name": "category", "enum": ["billing", "technical", "account", "feature_request", "other"]},
    {"name": "priority", "enum": ["low", "normal", "high", "urgent"]},
    {"name": "sentiment", "enum": ["positive", "neutral", "negative"]},
    {"name": "summary", "description": "One sentence describing the problem."},
]


def ask(
    system: str,
    prompt: str,
    *,
    fields: list[dict[str, Any]] | None = None,
    tools: list[dict[str, Any]] | None = None,
    extra: list[dict[str, Any]] | None = None,
    max_tokens: int = 800,
) -> Any:
    mode = "json" if fields is not None else "text"
    messages = runtime.build_messages(
        system, prompt, output_mode=mode, json_fields=fields or []
    ) + (extra or [])
    return respond(
        ChatRequest(
            model="offline",
            messages=messages,
            tools=tools,
            max_tokens=max_tokens,
            response_format=runtime.response_format(mode, fields or []),
        )
    )


def test_tickets_are_triaged_into_a_schema() -> None:
    response = ask(
        "You triage support tickets.",
        "Classify this support ticket.\n\nSubject: Charged twice\n"
        f"Customer: dana.whitfield@globex.example\n\nTicket:\n{TICKET}",
        fields=TRIAGE_FIELDS,
    )
    data = json.loads(response.content)
    assert data["category"] == "billing"
    assert data["priority"] == "high"
    assert data["sentiment"] == "negative"
    assert data["summary"].startswith("The customer was charged twice for their March invoice")
    assert response.prompt_tokens > 100
    assert response.completion_tokens > 20
    assert response.finish_reason == "stop"


def test_the_same_request_always_gets_the_same_answer() -> None:
    first = ask("You triage.", f"Classify.\n\nTicket:\n{TICKET}", fields=TRIAGE_FIELDS)
    second = ask("You triage.", f"Classify.\n\nTicket:\n{TICKET}", fields=TRIAGE_FIELDS)
    assert first.content == second.content
    assert first.prompt_tokens == second.prompt_tokens


def test_invoices_are_extracted_into_typed_fields() -> None:
    fields = [
        {"name": "vendor"},
        {"name": "invoice_number"},
        {"name": "invoice_date"},
        {"name": "due_date"},
        {"name": "currency"},
        {"name": "subtotal", "type": "number"},
        {"name": "tax", "type": "number"},
        {"name": "total", "type": "number"},
        {
            "name": "line_items",
            "type": "array",
            "items": "object",
            "fields": [
                {"name": "description"},
                {"name": "quantity", "type": "number"},
                {"name": "amount", "type": "number"},
            ],
        },
    ]
    data = runtime.parse_json_output(
        ask(
            "Extract invoice data.",
            f"Extract the invoice fields.\n\nInvoice:\n{INVOICE}",
            fields=fields,
        ).content,
        fields,
    )
    assert data["vendor"] == "Acme Office Supplies Ltd"
    assert (data["invoice_number"], data["invoice_date"], data["due_date"]) == (
        "AOS-2026-0417",
        "2026-03-03",
        "2026-04-02",
    )
    assert (data["currency"], data["subtotal"], data["tax"], data["total"]) == (
        "GBP",
        3527.0,
        705.4,
        4232.4,
    )
    assert data["line_items"][2] == {
        "description": "Monitor arm, dual",
        "quantity": 6,
        "amount": 477.0,
    }


def test_support_replies_use_the_name_policy_and_sign_off() -> None:
    reply = ask(
        "You are a support agent. Sign off as Northwind Support.",
        "Draft a reply to this ticket.\n\nCustomer: Dana Whitfield (enterprise plan)\n"
        "Subject: Charged twice\nCategory: billing\nPriority: high\n\n"
        f"Ticket:\n{TICKET}\n\nHelp center articles:\n{ARTICLES}",
    ).content
    assert reply.startswith("Hi Dana,")
    assert "refunded to the original payment method within 5 business days" in reply
    assert "happened again" in reply
    assert reply.endswith("Best regards,\nNorthwind Support")


def test_meeting_notes_become_action_items_and_decisions() -> None:
    items = action_items(NOTES)
    assert items[0] == {
        "owner": "Leo",
        "task": "Send the final firmware build to QA",
        "due": "Thursday",
    }
    assert {
        "owner": "Priya",
        "task": "Schedule the kickoff call with the design partners",
        "due": None,
    } in items
    assert items[-1]["owner"] == "Ava"
    assert items[-1]["due"] == "Friday"
    assert decisions(NOTES) == ["We decided to open the beta to 40 design partners on March 16."]
    summary = ask(
        "You summarise meetings.",
        f"Summarize the meeting in three bullet points.\n\nNotes:\n{NOTES}",
    ).content
    lines = summary.splitlines()
    assert len(lines) == 3
    assert all(line.startswith("- ") for line in lines)
    assert "Ava:" not in summary


def test_questions_are_answered_from_sources_with_citations() -> None:
    answer = ask(
        "Answer using the sources.",
        "Answer the question.\n\n"
        "Question: How many vacation days do full-time employees get?\n\n"
        f"Sources:\n{HANDBOOK}",
    ).content
    assert (
        answer == "Full-time employees receive 25 days of paid vacation per year, "
        "plus public holidays [1]."
    )
    missing = ask(
        "Answer.",
        "Answer the question.\n\nQuestion: What is the parking policy?\n\n"
        "Sources:\n[1] X\nUnrelated text about lunch menus here.",
    ).content
    assert "could not find" in missing


def test_research_questions_and_briefs() -> None:
    fields = [{"name": "questions", "type": "array", "items": "string"}]
    questions = json.loads(
        ask(
            "Plan.",
            "Break this into three research questions.\n\nTopic: Our data retention policy",
            fields=fields,
        ).content
    )["questions"]
    assert questions[0] == "What do our documents say about our data retention policy?"
    assert len(questions) == 3
    findings = (
        "### Q1?\nLogs are kept for 30 days. Teams should delete exports after use.\n\n"
        "### Q2?\nBackups are encrypted."
    )
    brief = ask(
        "Write briefs.",
        "Write a research brief.\n\nTopic: Data retention\nAudience: Engineering leads\n\n"
        f"Findings:\n{findings}",
    ).content
    assert brief.startswith("# Data retention\nPrepared for Engineering leads.")
    assert "## Key findings\n- **Q1?** Logs are kept for 30 days." in brief
    assert "- Teams should delete exports after use." in brief


def run_agent(
    system: str, task: str, tools: list[dict[str, Any]], knowledge: str
) -> tuple[str, list[tuple[str, dict[str, Any]]]]:
    messages = runtime.build_messages(system, task)
    calls: list[tuple[str, dict[str, Any]]] = []
    for _ in range(5):
        response = respond(ChatRequest(model="offline", messages=messages, tools=tools))
        if not response.tool_calls:
            return response.content or "", calls
        messages.append(
            runtime.assistant_message(
                None,
                [
                    {"id": c.id, "name": c.name, "arguments": c.arguments}
                    for c in response.tool_calls
                ],
            )
        )
        for call in response.tool_calls:
            args = json.loads(call.arguments)
            calls.append((call.name, args))
            result: Any = (
                {"result": runtime.calculate(args["expression"])}
                if call.name == "calculator"
                else {"results": [], "context": knowledge}
            )
            messages.append(runtime.tool_message(call.id, result))
    raise AssertionError("the agent did not finish")


def test_agents_plan_a_search_then_a_calculation_then_write() -> None:
    tools = [
        runtime.tool_definition(
            "knowledge", {"tool_description": "Search the product handbook."}, "product_docs"
        ),
        runtime.tool_definition("calculator", {}, "calculator"),
    ]
    task = (
        "Write a personalized outreach email to Priya Raman at Initech (480 employees). "
        'They wrote: "We have about 120 agents and budget approved for this quarter." '
        "Search the product docs for pricing that fits 120 seats and calculate the annual price."
    )
    email, calls = run_agent("You are a sales rep. Sign off as Jordan Lee.", task, tools, PRICING)
    assert calls == [
        ("product_docs", {"query": "pricing that fits 120 seats"}),
        ("calculator", {"expression": "120 * 39 * 12"}),
    ]
    assert email.startswith("Hi Priya,")
    assert "The Business plan costs $39 per seat per month" in email
    assert "For 120 seats, that comes to $56,160 per year." in email
    assert email.endswith("Jordan Lee")


def test_agents_answer_questions_with_their_search_tool() -> None:
    tools = [runtime.tool_definition("knowledge", {}, "search_policies")]
    answer, calls = run_agent(
        "Answer from the handbook.",
        "Question: How many vacation days do full-time employees get each year?",
        tools,
        HANDBOOK,
    )
    assert calls == [
        (
            "search_policies",
            {"query": "How many vacation days do full-time employees get each year?"},
        )
    ]
    assert "25 days of paid vacation" in answer


def test_answers_longer_than_max_tokens_report_length() -> None:
    response = ask("Write.", f"Summarize the meeting.\n\nNotes:\n{NOTES}", max_tokens=5)
    assert response.finish_reason == "length"
    assert response.completion_tokens == 5


async def test_the_provider_paces_output_when_asked() -> None:
    import time

    provider = OfflineProvider(delay_ms_per_100_tokens=200)
    started = time.monotonic()
    response = await provider.complete(
        ChatRequest(
            model="offline",
            messages=[{"role": "user", "content": f"Summarize.\n\nNotes:\n{NOTES}"}],
        )
    )
    assert time.monotonic() - started >= response.completion_tokens / 100 * 0.2 * 0.9
