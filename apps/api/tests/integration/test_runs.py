import asyncio
import copy
import json
import uuid
from typing import Any

import httpx
from fastapi import FastAPI

from tests.integration.conftest import (
    Actor,
    add_member,
    base,
    create_flow,
    new_workspace,
    wait_for_run,
)


async def start(
    client: httpx.AsyncClient,
    actor: Actor,
    workspace: dict[str, Any],
    flow_id: str,
    inputs: dict[str, Any],
    **query: Any,
) -> httpx.Response:
    params = "&".join(f"{k}={v}" for k, v in query.items())
    return await client.post(
        f"{base(workspace)}/flows/{flow_id}/runs" + (f"?{params}" if params else ""),
        json={
            "inputs": inputs,
            **({"version": query.pop("version")} if "version" in query else {}),
        },
        headers=actor.headers,
    )


async def test_runs_execute_and_can_be_awaited(client: httpx.AsyncClient, admin: Actor) -> None:
    workspace = await new_workspace(client, admin)
    flow = await create_flow(client, admin, workspace)
    response = await start(client, admin, workspace, flow["id"], {"input": "hello"}, wait=10)
    assert response.status_code == 202
    run = response.json()
    assert run["status"] == "succeeded"
    assert run["outputs"] == {"result": "hello"}
    assert run["version_label"] == "draft"
    assert run["triggered_by"] == "Ava Admin"
    assert run["trigger"] == "manual"
    detail = await client.get(f"{base(workspace)}/runs/{run['id']}", headers=admin.headers)
    assert [s["node_id"] for s in detail.json()["steps"]] == ["start", "result"]
    assert detail.json()["graph"]["nodes"]


async def test_inputs_are_validated_before_queueing(
    client: httpx.AsyncClient, admin: Actor
) -> None:
    workspace = await new_workspace(client, admin)
    flow = await create_flow(client, admin, workspace)
    response = await start(client, admin, workspace, flow["id"], {})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_inputs"
    unpublished = await client.post(
        f"{base(workspace)}/flows/{flow['id']}/runs",
        json={"inputs": {"input": "x"}, "version": "published"},
        headers=admin.headers,
    )
    assert unpublished.status_code == 409


async def test_history_filters_and_reruns(client: httpx.AsyncClient, admin: Actor) -> None:
    workspace = await new_workspace(client, admin)
    flow = await create_flow(client, admin, workspace)
    await client.post(
        f"{base(workspace)}/flows/{flow['id']}/publish", json={}, headers=admin.headers
    )
    first = (await start(client, admin, workspace, flow["id"], {"input": "one"}, wait=10)).json()
    assert first["version_label"] == "v1"
    rerun = await client.post(f"{base(workspace)}/runs/{first['id']}/rerun", headers=admin.headers)
    assert rerun.status_code == 202
    again = await wait_for_run(client, admin, workspace, rerun.json()["id"])
    assert again["outputs"] == {"result": "one"}
    assert again["trigger"] == "rerun"
    assert again["rerun_of_id"] == first["id"]
    history = await client.get(f"{base(workspace)}/runs?trigger=rerun", headers=admin.headers)
    assert history.json()["total"] == 1
    by_flow = await client.get(
        f"{base(workspace)}/runs?flow_id={flow['id']}&status=succeeded&limit=1",
        headers=admin.headers,
    )
    assert by_flow.json()["total"] == 2
    assert len(by_flow.json()["items"]) == 1


async def test_failures_record_the_node_and_the_error(
    client: httpx.AsyncClient, admin: Actor
) -> None:
    workspace = await new_workspace(client, admin)
    flow = await create_flow(client, admin, workspace)
    graph = copy.deepcopy(flow["graph"])
    graph["nodes"].append(
        {
            "id": "calc",
            "type": "calculator",
            "position": {"x": 200, "y": 0},
            "config": {"expression": "100 / {{inputs.input}}"},
        }
    )
    graph["edges"] = [
        {"id": "a", "source": "start", "target": "calc"},
        {"id": "b", "source": "calc", "target": "result"},
    ]
    await client.put(
        f"{base(workspace)}/flows/{flow['id']}/draft",
        json={"graph": graph, "base_revision": 1},
        headers=admin.headers,
    )
    run = (await start(client, admin, workspace, flow["id"], {"input": "0"}, wait=10)).json()
    assert run["status"] == "failed"
    assert run["error"]["code"] == "calculation_failed"
    assert run["error"]["node_id"] == "calc"
    detail = (await client.get(f"{base(workspace)}/runs/{run['id']}", headers=admin.headers)).json()
    failed = next(s for s in detail["steps"] if s["node_id"] == "calc")
    assert failed["status"] == "failed"
    assert failed["input"] == {"expression": "100 / 0"}


async def test_secrets_are_resolved_but_never_recorded(
    client: httpx.AsyncClient, admin: Actor
) -> None:
    workspace = await new_workspace(client, admin)
    await client.post(
        f"{base(workspace)}/secrets",
        json={"name": "API_TOKEN", "value": "tok-live-123456"},
        headers=admin.headers,
    )
    flow = await create_flow(client, admin, workspace)
    graph = copy.deepcopy(flow["graph"])
    graph["nodes"][1]["config"]["fields"] = [
        {"name": "auth", "value": "Bearer {{secrets.API_TOKEN}}"}
    ]
    await client.put(
        f"{base(workspace)}/flows/{flow['id']}/draft",
        json={"graph": graph, "base_revision": 1},
        headers=admin.headers,
    )
    run = (await start(client, admin, workspace, flow["id"], {"input": "x"}, wait=10)).json()
    assert run["outputs"] == {"auth": "Bearer [secret:API_TOKEN]"}
    detail = await client.get(f"{base(workspace)}/runs/{run['id']}", headers=admin.headers)
    assert "tok-live-123456" not in detail.text
    assert "[secret:API_TOKEN]" in json.dumps(detail.json()["steps"])


async def test_live_traces_stream_and_resume(client: httpx.AsyncClient, admin: Actor) -> None:
    workspace = await new_workspace(client, admin)
    flow = await create_flow(client, admin, workspace)
    run = (await start(client, admin, workspace, flow["id"], {"input": "x"}, wait=10)).json()
    events: list[tuple[str, str]] = []
    async with client.stream(
        "GET", f"{base(workspace)}/runs/{run['id']}/events", headers=admin.headers
    ) as stream:
        assert stream.headers["content-type"].startswith("text/event-stream")
        current_id = ""
        async for line in stream.aiter_lines():
            if line.startswith("id: "):
                current_id = line[4:]
            elif line.startswith("event: "):
                events.append((current_id, line[7:]))
                if line == "event: run.finished":
                    break
    kinds = [kind for _, kind in events]
    assert kinds[0] == "run.queued"
    assert kinds[-1] == "run.finished"
    assert kinds.count("step.finished") == 2
    middle = events[2][0]
    resumed: list[str] = []
    async with client.stream(
        "GET",
        f"{base(workspace)}/runs/{run['id']}/events",
        headers={**admin.headers, "last-event-id": middle},
    ) as stream:
        async for line in stream.aiter_lines():
            if line.startswith("event: "):
                resumed.append(line[7:])
                if line == "event: run.finished":
                    break
    assert resumed == kinds[3:]


async def test_traces_of_old_runs_are_replayed_from_postgres(
    app: FastAPI, client: httpx.AsyncClient, admin: Actor
) -> None:
    workspace = await new_workspace(client, admin)
    flow = await create_flow(client, admin, workspace)
    run = (await start(client, admin, workspace, flow["id"], {"input": "x"}, wait=10)).json()
    await app.state.container.stream_redis.delete(f"run:{run['id']}:events")
    async with client.stream(
        "GET", f"{base(workspace)}/runs/{run['id']}/events", headers=admin.headers
    ) as stream:
        kinds = [line[7:] async for line in stream.aiter_lines() if line.startswith("event: ")]
    assert kinds == ["run.started", "step.finished", "step.finished", "run.finished"]


async def test_too_many_active_runs_are_refused(
    app: FastAPI, client: httpx.AsyncClient, admin: Actor
) -> None:
    workspace = await new_workspace(client, admin)
    flow = await create_flow(client, admin, workspace)
    container = app.state.container
    original = container.settings
    container.settings = original.model_copy(update={"max_active_runs_per_workspace": 0})
    try:
        refused = await start(client, admin, workspace, flow["id"], {"input": "x"})
    finally:
        container.settings = original
    assert refused.status_code == 429
    assert refused.json()["error"]["code"] == "too_many_active_runs"


async def test_viewers_cannot_start_or_cancel_runs(client: httpx.AsyncClient, admin: Actor) -> None:
    workspace = await new_workspace(client, admin)
    flow = await create_flow(client, admin, workspace)
    viewer = await add_member(client, admin, workspace, "viewer")
    assert (await start(client, viewer, workspace, flow["id"], {"input": "x"})).status_code == 403
    run = (await start(client, admin, workspace, flow["id"], {"input": "x"}, wait=10)).json()
    assert (
        await client.post(f"{base(workspace)}/runs/{run['id']}/cancel", headers=viewer.headers)
    ).status_code == 403
    finished = await client.post(
        f"{base(workspace)}/runs/{run['id']}/cancel", headers=admin.headers
    )
    assert finished.status_code == 409
    assert (
        await client.get(f"{base(workspace)}/runs/{uuid.uuid4()}", headers=admin.headers)
    ).status_code == 404


async def test_parallel_runs_all_finish(client: httpx.AsyncClient, admin: Actor) -> None:
    workspace = await new_workspace(client, admin)
    flow = await create_flow(client, admin, workspace)
    responses = await asyncio.gather(
        *(start(client, admin, workspace, flow["id"], {"input": str(i)}) for i in range(8))
    )
    finished = [await wait_for_run(client, admin, workspace, r.json()["id"]) for r in responses]
    assert sorted(run["outputs"]["result"] for run in finished) == [str(i) for i in range(8)]
