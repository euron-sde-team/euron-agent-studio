"""Workspace secrets: encrypted at rest, write-only through the API, owners only."""

import httpx
from fastapi import FastAPI
from sqlalchemy import select

from agentstudio.models import Secret
from tests.integration.conftest import Actor, add_member, base, create_flow, new_workspace

VALUE = "sk-live-8f2c0b7e41d9"


async def test_values_are_write_only_and_encrypted(
    app: FastAPI, client: httpx.AsyncClient, admin: Actor
) -> None:
    workspace = await new_workspace(client, admin)
    created = await client.post(
        f"{base(workspace)}/secrets",
        json={"name": "CRM_TOKEN", "value": VALUE, "description": "CRM API token"},
        headers=admin.headers,
    )
    assert created.status_code == 201
    assert VALUE not in created.text
    listing = await client.get(f"{base(workspace)}/secrets", headers=admin.headers)
    assert [s["name"] for s in listing.json()["items"]] == ["CRM_TOKEN"]
    assert VALUE not in listing.text
    async with app.state.container.db.session() as session:
        stored = await session.scalar(select(Secret).where(Secret.name == "CRM_TOKEN"))
    assert stored is not None
    assert VALUE.encode() not in bytes(stored.ciphertext)
    duplicate = await client.post(
        f"{base(workspace)}/secrets",
        json={"name": "CRM_TOKEN", "value": "x"},
        headers=admin.headers,
    )
    assert duplicate.status_code == 409
    invalid = await client.post(
        f"{base(workspace)}/secrets",
        json={"name": "crm token", "value": "x"},
        headers=admin.headers,
    )
    assert invalid.status_code == 422


async def test_only_owners_write_and_viewers_cannot_list(
    client: httpx.AsyncClient, admin: Actor
) -> None:
    workspace = await new_workspace(client, admin)
    editor = await add_member(client, admin, workspace, "editor")
    viewer = await add_member(client, admin, workspace, "viewer")
    assert (
        await client.post(
            f"{base(workspace)}/secrets", json={"name": "A", "value": "x"}, headers=editor.headers
        )
    ).status_code == 403
    assert (
        await client.get(f"{base(workspace)}/secrets", headers=editor.headers)
    ).status_code == 200
    assert (
        await client.get(f"{base(workspace)}/secrets", headers=viewer.headers)
    ).status_code == 403


async def test_flows_see_new_values_and_missing_names(
    client: httpx.AsyncClient, admin: Actor
) -> None:
    workspace = await new_workspace(client, admin)
    await client.post(
        f"{base(workspace)}/secrets",
        json={"name": "GREETING", "value": "hello"},
        headers=admin.headers,
    )
    flow = await create_flow(client, admin, workspace)
    graph = flow["graph"]
    # Outputs mask secret values, so the flow returns a value derived from the secret.
    graph["nodes"][1]["config"]["fields"] = [
        {"name": "said", "value": "{{secrets.GREETING | upper}}"},
        {"name": "raw", "value": "{{secrets.GREETING}}"},
    ]
    await client.put(
        f"{base(workspace)}/flows/{flow['id']}/draft",
        json={"graph": graph, "base_revision": 1},
        headers=admin.headers,
    )

    async def run() -> dict[str, object]:
        response = await client.post(
            f"{base(workspace)}/flows/{flow['id']}/runs?wait=10",
            json={"inputs": {"input": "x"}},
            headers=admin.headers,
        )
        return dict(response.json())

    assert (await run())["outputs"] == {"said": "HELLO", "raw": "[secret:GREETING]"}
    await client.patch(
        f"{base(workspace)}/secrets/GREETING", json={"value": "bonjour"}, headers=admin.headers
    )
    assert (await run())["outputs"] == {"said": "BONJOUR", "raw": "[secret:GREETING]"}
    assert (
        await client.delete(f"{base(workspace)}/secrets/GREETING", headers=admin.headers)
    ).status_code == 204
    checked = (
        await client.get(f"{base(workspace)}/flows/{flow['id']}", headers=admin.headers)
    ).json()
    assert {issue["code"] for issue in checked["issues"]} == {"unknown_secret"}
