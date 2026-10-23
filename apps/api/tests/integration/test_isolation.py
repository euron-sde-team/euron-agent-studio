"""Workspaces are sealed: no route reaches another workspace's data, by slug or by id."""

import uuid
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


async def populated(client: httpx.AsyncClient, owner: Actor) -> dict[str, Any]:
    """A workspace with one of everything: flow, run, approval, knowledge, secret, key."""
    workspace = await new_workspace(client, owner)
    flow = await create_flow(client, owner, workspace, template="support-triage")
    sample = (await client.get("/api/v1/templates/support-triage", headers=owner.headers)).json()
    run = (
        await client.post(
            f"{base(workspace)}/flows/{flow['id']}/runs?wait=30",
            json={"inputs": sample["sample"]},
            headers=owner.headers,
        )
    ).json()
    approval = (await client.get(f"{base(workspace)}/approvals", headers=owner.headers)).json()[
        "items"
    ][0]
    kb = (await client.get(f"{base(workspace)}/knowledge-bases", headers=owner.headers)).json()[
        "items"
    ][0]
    document = (
        await client.get(
            f"{base(workspace)}/knowledge-bases/{kb['id']}/documents", headers=owner.headers
        )
    ).json()["items"][0]
    await client.post(
        f"{base(workspace)}/secrets", json={"name": "TOKEN", "value": "x"}, headers=owner.headers
    )
    key = (
        await client.post(
            f"{base(workspace)}/api-keys",
            json={"name": "k", "role": "editor"},
            headers=owner.headers,
        )
    ).json()
    return {
        "workspace": workspace,
        "flow": flow["id"],
        "run": run["id"],
        "approval": approval["id"],
        "kb": kb["id"],
        "document": document["id"],
        "key": key["id"],
    }


def routes(ids: dict[str, Any]) -> list[tuple[str, str, Any]]:
    flow, run, kb, doc = ids["flow"], ids["run"], ids["kb"], ids["document"]
    return [
        ("GET", "", None),
        ("GET", "/members", None),
        ("GET", "/audit", None),
        ("GET", "/dashboard", None),
        ("GET", "/flows", None),
        ("GET", f"/flows/{flow}", None),
        ("GET", f"/flows/{flow}/versions", None),
        ("GET", f"/flows/{flow}/export", None),
        ("GET", f"/flows/{flow}/export/python", None),
        ("GET", f"/flows/{flow}/webhook", None),
        ("PATCH", f"/flows/{flow}", {"name": "mine now"}),
        ("POST", f"/flows/{flow}/runs", {"inputs": {}}),
        ("POST", f"/flows/{flow}/publish", {}),
        ("DELETE", f"/flows/{flow}", None),
        ("GET", "/runs", None),
        ("GET", f"/runs/{run}", None),
        ("GET", f"/runs/{run}/events", None),
        ("POST", f"/runs/{run}/cancel", None),
        ("POST", f"/runs/{run}/rerun", None),
        ("GET", "/approvals", None),
        ("GET", f"/approvals/{ids['approval']}", None),
        ("POST", f"/approvals/{ids['approval']}/decision", {"decision": "approve"}),
        ("GET", "/knowledge-bases", None),
        ("GET", f"/knowledge-bases/{kb}", None),
        ("GET", f"/knowledge-bases/{kb}/documents/{doc}/content", None),
        ("POST", f"/knowledge-bases/{kb}/search", {"query": "refund"}),
        ("DELETE", f"/knowledge-bases/{kb}/documents/{doc}", None),
        ("GET", "/secrets", None),
        ("DELETE", "/secrets/TOKEN", None),
        ("GET", "/api-keys", None),
        ("DELETE", f"/api-keys/{ids['key']}", None),
    ]


async def call(
    client: httpx.AsyncClient, method: str, url: str, body: Any, headers: dict[str, str]
) -> int:
    response = await client.request(method, url, json=body, headers=headers)
    return response.status_code


async def test_outsiders_cannot_see_that_a_workspace_exists(
    client: httpx.AsyncClient, admin: Actor
) -> None:
    ids = await populated(client, admin)
    elsewhere = await new_workspace(client, admin)
    outsider = await add_member(client, admin, elsewhere, "owner")
    prefix = base(ids["workspace"])
    for method, path, body in routes(ids):
        status = await call(client, method, prefix + path, body, outsider.headers)
        assert status == 404, (method, path, status)
    foreign_key = await api_key(client, admin, elsewhere, role="editor")
    for method, path, body in routes(ids):
        status = await call(client, method, prefix + path, body, foreign_key.headers)
        assert status in {403, 404}, (method, path, status)


async def test_ids_from_one_workspace_do_not_resolve_in_another(
    client: httpx.AsyncClient, admin: Actor
) -> None:
    ids = await populated(client, admin)
    other = await new_workspace(client, admin)
    prefix = base(other)
    for method, path, body in routes(ids):
        if "{" in path or path in {"", "/members", "/audit", "/dashboard"}:
            continue
        if not any(str(value) in path for value in ids.values() if isinstance(value, str)):
            continue
        status = await call(client, method, prefix + path, body, admin.headers)
        assert status == 404, (method, path, status)
    # The original workspace is untouched by everything above.
    owner_view = await client.get(
        f"{base(ids['workspace'])}/runs/{ids['run']}", headers=admin.headers
    )
    assert owner_view.json()["status"] == "waiting"
    missing = await client.get(
        f"{base(ids['workspace'])}/flows/{uuid.uuid4()}", headers=admin.headers
    )
    assert missing.status_code == 404
