"""The dashboard aggregates, the catalog, and the offline model's OpenAI-compatible API."""

import copy
from typing import Any

import httpx

from tests.integration.conftest import (
    Actor,
    add_member,
    api_key,
    base,
    create_flow,
    new_workspace,
)


async def run(
    client: httpx.AsyncClient, actor: Actor, workspace: dict[str, Any], flow_id: str, inputs: Any
) -> dict[str, Any]:
    response = await client.post(
        f"{base(workspace)}/flows/{flow_id}/runs?wait=30",
        json={"inputs": inputs},
        headers=actor.headers,
    )
    assert response.status_code == 202, response.text
    return dict(response.json())


async def test_the_dashboard_counts_runs_and_follows_new_ones(
    client: httpx.AsyncClient, admin: Actor
) -> None:
    workspace = await new_workspace(client, admin)
    echo = await create_flow(client, admin, workspace, name="Echo")
    await client.post(
        f"{base(workspace)}/flows/{echo['id']}/publish", json={}, headers=admin.headers
    )
    divide = await create_flow(client, admin, workspace, name="Divide")
    graph = copy.deepcopy(divide["graph"])
    graph["nodes"].append(
        {"id": "calc", "type": "calculator", "config": {"expression": "1 / {{inputs.input}}"}}
    )
    graph["edges"] = [
        {"id": "a", "source": "start", "target": "calc"},
        {"id": "b", "source": "calc", "target": "result"},
    ]
    await client.put(
        f"{base(workspace)}/flows/{divide['id']}/draft",
        json={"graph": graph, "base_revision": 1},
        headers=admin.headers,
    )
    triage = await create_flow(client, admin, workspace, name="Triage", template="support-triage")
    sample = (await client.get("/api/v1/templates/support-triage", headers=admin.headers)).json()
    for text in ("a", "b", "c"):
        await run(client, admin, workspace, echo["id"], {"input": text})
    assert (await run(client, admin, workspace, divide["id"], {"input": "0"}))["status"] == "failed"
    assert (await run(client, admin, workspace, triage["id"], sample["sample"]))[
        "status"
    ] == "waiting"

    viewer = await add_member(client, admin, workspace, "viewer")
    stats = (await client.get(f"{base(workspace)}/dashboard", headers=viewer.headers)).json()
    assert (stats["runs"], stats["succeeded"], stats["failed"], stats["waiting"]) == (5, 3, 1, 1)
    assert stats["success_rate"] == 0.75
    assert stats["pending_approvals"] == 1
    assert (stats["flows"], stats["published_flows"]) == (3, 1)
    assert stats["prompt_tokens"] > 0
    assert stats["cost_usd"] > 0
    assert stats["p50_ms"] is not None
    assert len(stats["daily"]) == stats["period_days"]
    today = stats["daily"][-1]
    assert (today["succeeded"], today["failed"], today["other"]) == (3, 1, 1)
    assert stats["top_flows"][0]["name"] == "Echo"
    assert stats["top_flows"][0]["runs"] == 3
    assert len(stats["recent_runs"]) == 5

    await run(client, admin, workspace, echo["id"], {"input": "d"})
    fresh = (await client.get(f"{base(workspace)}/dashboard", headers=viewer.headers)).json()
    assert fresh["runs"] == 6
    assert fresh["recent_runs"][0]["inputs"] == {"input": "d"}


async def test_the_catalog_lists_the_offline_model(client: httpx.AsyncClient, admin: Actor) -> None:
    models = (await client.get("/api/v1/models", headers=admin.headers)).json()
    offline = next(m for m in models if m["provider"] == "offline")
    assert offline["ref"] == "offline"
    assert offline["offline"] is True
    assert offline["simulated"] is True
    assert (await client.get("/api/v1/models")).status_code == 401


async def test_the_offline_model_speaks_chat_completions(
    client: httpx.AsyncClient, admin: Actor
) -> None:
    workspace = await new_workspace(client, admin)
    key = await api_key(client, admin, workspace, role="viewer")
    listed = await client.get("/api/v1/offline/v1/models", headers=key.headers)
    assert listed.json()["data"][0]["id"] == "offline"
    answer = await client.post(
        "/api/v1/offline/v1/chat/completions",
        json={
            "model": "offline",
            "messages": [
                {
                    "role": "system",
                    "content": "Classify the ticket as billing, technical or account.",
                },
                {"role": "user", "content": "I was charged twice for my March invoice."},
            ],
        },
        headers=key.headers,
    )
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["role"] == "assistant"
    assert "billing" in body["choices"][0]["message"]["content"].lower()
    assert body["usage"]["prompt_tokens"] > 0
    tools = await client.post(
        "/api/v1/offline/v1/chat/completions",
        json={
            "model": "offline",
            "messages": [{"role": "user", "content": "What is 17.5 percent of 2400?"}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "calculator",
                        "description": "Evaluate an arithmetic expression.",
                        "parameters": {
                            "type": "object",
                            "properties": {"expression": {"type": "string"}},
                            "required": ["expression"],
                        },
                    },
                }
            ],
        },
        headers=key.headers,
    )
    choice = tools.json()["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    assert choice["message"]["tool_calls"][0]["function"]["name"] == "calculator"
    refused = await client.post("/api/v1/offline/v1/chat/completions", json={"messages": []})
    assert refused.status_code == 401
