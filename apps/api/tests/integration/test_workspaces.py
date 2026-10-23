import httpx

from tests.integration.conftest import Actor, add_member, base, new_workspace


async def test_owners_manage_members_and_roles(client: httpx.AsyncClient, admin: Actor) -> None:
    workspace = await new_workspace(client, admin, "Members test")
    viewer = await add_member(client, admin, workspace, "viewer")
    editor = await add_member(client, admin, workspace, "editor")
    members = await client.get(f"{base(workspace)}/members?limit=2", headers=viewer.headers)
    assert members.status_code == 200
    assert members.json()["total"] == 3
    assert len(members.json()["items"]) == 2
    users = {
        m["email"]: m
        for m in (await client.get(f"{base(workspace)}/members", headers=admin.headers)).json()[
            "items"
        ]
    }
    promoted = await client.patch(
        f"{base(workspace)}/members/{users[viewer.email]['user_id']}",
        json={"role": "editor"},
        headers=admin.headers,
    )
    assert promoted.status_code == 200
    assert promoted.json()["role"] == "editor"
    refused = await client.patch(
        f"{base(workspace)}/members/{users[viewer.email]['user_id']}",
        json={"role": "owner"},
        headers=editor.headers,
    )
    assert refused.status_code == 403
    duplicate = await client.post(
        f"{base(workspace)}/members",
        json={"email": editor.email, "role": "viewer"},
        headers=admin.headers,
    )
    assert duplicate.status_code == 409


async def test_a_workspace_always_keeps_an_owner(client: httpx.AsyncClient, admin: Actor) -> None:
    workspace = await new_workspace(client, admin)
    me = (await client.get("/api/v1/auth/me", headers=admin.headers)).json()["user"]
    leave = await client.delete(f"{base(workspace)}/members/{me['id']}", headers=admin.headers)
    assert leave.status_code == 422
    assert leave.json()["error"]["code"] == "last_owner"
    demote = await client.patch(
        f"{base(workspace)}/members/{me['id']}", json={"role": "viewer"}, headers=admin.headers
    )
    assert demote.status_code == 422


async def test_members_can_leave_and_only_owners_remove_others(
    client: httpx.AsyncClient, admin: Actor
) -> None:
    workspace = await new_workspace(client, admin)
    editor = await add_member(client, admin, workspace, "editor")
    viewer = await add_member(client, admin, workspace, "viewer")
    people = {
        m["email"]: m["user_id"]
        for m in (await client.get(f"{base(workspace)}/members", headers=admin.headers)).json()[
            "items"
        ]
    }
    assert (
        await client.delete(
            f"{base(workspace)}/members/{people[viewer.email]}", headers=editor.headers
        )
    ).status_code == 403
    assert (
        await client.delete(
            f"{base(workspace)}/members/{people[viewer.email]}", headers=viewer.headers
        )
    ).status_code == 204
    assert (await client.get(base(workspace), headers=viewer.headers)).status_code == 404


async def test_settings_and_the_audit_trail(client: httpx.AsyncClient, admin: Actor) -> None:
    workspace = await new_workspace(client, admin, "Audit test")
    updated = await client.patch(
        base(workspace),
        json={
            "name": "Audit test renamed",
            "settings": {"default_model": "offline", "run_retention_days": 30},
        },
        headers=admin.headers,
    )
    assert updated.status_code == 200
    assert updated.json()["settings"]["run_retention_days"] == 30
    await add_member(client, admin, workspace, "viewer")
    audit = await client.get(f"{base(workspace)}/audit", headers=admin.headers)
    actions = [event["action"] for event in audit.json()["items"]]
    assert actions[:3] == ["member.added", "workspace.updated", "workspace.created"]
    assert audit.json()["items"][0]["actor_name"] == "Ava Admin"
    filtered = await client.get(f"{base(workspace)}/audit?action=member.", headers=admin.headers)
    assert [e["action"] for e in filtered.json()["items"]] == ["member.added"]


async def test_deleting_a_workspace_removes_everything(
    client: httpx.AsyncClient, admin: Actor
) -> None:
    workspace = await new_workspace(client, admin)
    flow = await client.post(
        f"{base(workspace)}/flows", json={"name": "Doomed"}, headers=admin.headers
    )
    assert flow.status_code == 201
    assert (await client.delete(base(workspace), headers=admin.headers)).status_code == 204
    assert (await client.get(base(workspace), headers=admin.headers)).status_code == 404
