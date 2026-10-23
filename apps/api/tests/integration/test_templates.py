"""Every template runs end to end on real Postgres search, and its export runs as a program."""

import asyncio
import json
import os
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn

from agentstudio.core.config import Settings
from agentstudio.main import create_app
from tests.integration.conftest import Actor, api_key, base, create_flow, new_workspace

SLUGS = (
    "support-triage",
    "invoice-extraction",
    "research-brief",
    "lead-qualification",
    "meeting-actions",
    "policy-assistant",
)


@dataclass(slots=True)
class Gallery:
    workspace: dict[str, Any]
    flows: dict[str, dict[str, Any]]
    samples: dict[str, dict[str, Any]]


@pytest.fixture(scope="module")
async def gallery(client: httpx.AsyncClient, admin: Actor) -> Gallery:
    """One workspace with a flow installed from every template, as `make demo` does."""
    workspace = await new_workspace(client, admin, name="Template gallery")
    templates = (await client.get("/api/v1/templates", headers=admin.headers)).json()
    flows, samples = {}, {}
    for template in templates:
        slug = template["slug"]
        flows[slug] = await create_flow(
            client, admin, workspace, name=template["name"], template=slug
        )
        samples[slug] = template["sample"]
    return Gallery(workspace, flows, samples)


async def run_sample(
    client: httpx.AsyncClient, admin: Actor, gallery: Gallery, slug: str
) -> dict[str, Any]:
    flow = gallery.flows[slug]
    response = await client.post(
        f"{base(gallery.workspace)}/flows/{flow['id']}/runs?wait=60",
        json={"inputs": gallery.samples[slug]},
        headers=admin.headers,
    )
    assert response.status_code == 202, response.text
    run = response.json()
    if run["status"] == "waiting":
        approvals = await client.get(
            f"{base(gallery.workspace)}/approvals?status=pending", headers=admin.headers
        )
        pending = [a for a in approvals.json()["items"] if a["run_id"] == run["id"]]
        await client.post(
            f"{base(gallery.workspace)}/approvals/{pending[0]['id']}/decision",
            json={"decision": "approve"},
            headers=admin.headers,
        )
        deadline = time.monotonic() + 60
        while run["status"] in {"queued", "running", "waiting"} and time.monotonic() < deadline:
            await asyncio.sleep(0.1)
            run = (
                await client.get(
                    f"{base(gallery.workspace)}/runs/{run['id']}", headers=admin.headers
                )
            ).json()
    assert run["status"] == "succeeded", run.get("error")
    detail = await client.get(f"{base(gallery.workspace)}/runs/{run['id']}", headers=admin.headers)
    return dict(detail.json())


async def test_the_gallery_has_six_ready_to_run_templates(
    client: httpx.AsyncClient, admin: Actor, gallery: Gallery
) -> None:
    templates = (await client.get("/api/v1/templates", headers=admin.headers)).json()
    assert sorted(t["slug"] for t in templates) == sorted(SLUGS)
    for template in templates:
        assert template["sample"], template["slug"]
        assert template["inputs"], template["slug"]
        assert gallery.flows[template["slug"]]["issues"] == [], template["slug"]
    one = await client.get("/api/v1/templates/meeting-actions", headers=admin.headers)
    assert "loop" in one.json()["node_types"]
    assert (await client.get("/api/v1/templates/nope", headers=admin.headers)).status_code == 404


async def test_support_triage_drafts_a_reviewed_reply(
    client: httpx.AsyncClient, admin: Actor, gallery: Gallery
) -> None:
    run = await run_sample(client, admin, gallery, "support-triage")
    outputs = run["outputs"]
    assert outputs["status"] == "sent"
    assert outputs["reply"].startswith("Hi ")
    steps = {s["node_id"]: s for s in run["steps"]}
    assert steps["search_help"]["output"]["results"]
    assert steps["classify"]["model"] == "offline"
    assert run["cost_simulated"] is True
    assert run["prompt_tokens"] > 0


async def test_invoice_extraction_posts_a_checked_record(
    client: httpx.AsyncClient, admin: Actor, gallery: Gallery
) -> None:
    run = await run_sample(client, admin, gallery, "invoice-extraction")
    assert run["outputs"] == {
        "status": "posted",
        "record": {
            "vendor": "Acme Office Supplies Ltd",
            "invoice_number": "AOS-2026-0417",
            "issued": "2026-03-03",
            "due": "2026-04-02",
            "currency": "GBP",
            "total": 4232.4,
            "lines": 3,
        },
    }


async def test_research_brief_answers_each_question_with_citations(
    client: httpx.AsyncClient, admin: Actor, gallery: Gallery
) -> None:
    run = await run_sample(client, admin, gallery, "research-brief")
    outputs = run["outputs"]
    assert outputs["questions_answered"] == 3
    assert outputs["brief"].startswith("# Rolling out the new remote work policy")
    assert "[1]" in outputs["brief"]
    iterations = sorted(s["iteration"] for s in run["steps"] if s["node_id"] == "search")
    assert iterations == ["0", "1", "2"]


async def test_lead_qualification_prices_the_deal(
    client: httpx.AsyncClient, admin: Actor, gallery: Gallery
) -> None:
    run = await run_sample(client, admin, gallery, "lead-qualification")
    outputs = run["outputs"]
    assert outputs["tier"] == "hot"
    assert outputs["intent"] == "purchase"
    assert "$56,160 per year" in outputs["email"]


async def test_meeting_actions_files_one_task_per_action(
    client: httpx.AsyncClient, admin: Actor, gallery: Gallery
) -> None:
    run = await run_sample(client, admin, gallery, "meeting-actions")
    outputs = run["outputs"]
    assert outputs["task_count"] == 4
    assert all(task.startswith("TSK-") for task in outputs["tasks"])
    assert outputs["decisions"] == [
        "We decided to open the beta to 40 design partners on March 16."
    ]


async def test_policy_assistant_answers_from_the_handbook(
    client: httpx.AsyncClient, admin: Actor, gallery: Gallery
) -> None:
    run = await run_sample(client, admin, gallery, "policy-assistant")
    assert "25 days of paid vacation" in run["outputs"]["answer"]
    assert run["outputs"]["tools_used"] == 1
    agent = next(s for s in run["steps"] if s["node_id"] == "answer")
    assert [e["type"] for e in agent["events"]].count("tool_call") == 1


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def live_api(settings: Settings, app: Any) -> Iterator[str]:
    """The API over real HTTP, for exported scripts running as separate programs."""
    port = _free_port()
    config = uvicorn.Config(create_app(settings), host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while not server.started:
        assert time.monotonic() < deadline, "the API did not start"
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=15)


@pytest.mark.parametrize("slug", ["support-triage", "research-brief", "policy-assistant"])
async def test_exported_scripts_match_the_engine(
    client: httpx.AsyncClient,
    admin: Actor,
    gallery: Gallery,
    live_api: str,
    tmp_path: Path,
    slug: str,
) -> None:
    flow = gallery.flows[slug]
    exported = await client.get(
        f"{base(gallery.workspace)}/flows/{flow['id']}/export/python", headers=admin.headers
    )
    script = tmp_path / "flow.py"
    script.write_text(exported.text)
    key = await api_key(client, admin, gallery.workspace, role="viewer")
    env = {
        **os.environ,
        "AGENTSTUDIO_URL": live_api,
        "AGENTSTUDIO_API_KEY": key.token,
        "APPROVAL_MODE": "approve",
    }
    done = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, str(script), "--input", json.dumps(gallery.samples[slug])],
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    expected = await run_sample(client, admin, gallery, slug)
    assert json.loads(done.stdout) == expected["outputs"]
