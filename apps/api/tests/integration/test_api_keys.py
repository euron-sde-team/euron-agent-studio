import httpx

from tests.integration.conftest import Actor, add_member, api_key, base, create_flow, new_workspace


async def test_keys_are_shown_once_and_work_as_bearer_tokens(
    client: httpx.AsyncClient, admin: Actor
) -> None:
    workspace = await new_workspace(client, admin)
    created = await client.post(
        f"{base(workspace)}/api-keys",
        json={"name": "Zapier", "role": "editor"},
        headers=admin.headers,
    )
    assert created.status_code == 201
    key = created.json()["key"]
    assert key.startswith("agst_")
    listed = await client.get(f"{base(workspace)}/api-keys", headers=admin.headers)
    assert "key" not in listed.json()["items"][0]
    keyed = {"authorization": f"Bearer {key}"}
    flows = await client.get(f"{base(workspace)}/flows", headers=keyed)
    assert flows.status_code == 200
    assert (await client.get("/api/v1/auth/me", headers=keyed)).status_code == 403


async def test_viewer_keys_cannot_start_runs_and_revoked_keys_stop_working(
    client: httpx.AsyncClient, admin: Actor
) -> None:
    workspace = await new_workspace(client, admin)
    flow = await create_flow(client, admin, workspace, name="Echo")
    viewer = await api_key(client, admin, workspace, "viewer")
    run = await client.post(
        f"{base(workspace)}/flows/{flow['id']}/runs",
        json={"inputs": {"input": "x"}},
        headers=viewer.headers,
    )
    assert run.status_code == 403
    keys = (await client.get(f"{base(workspace)}/api-keys", headers=admin.headers)).json()["items"]
    assert (
        await client.delete(f"{base(workspace)}/api-keys/{keys[0]['id']}", headers=admin.headers)
    ).status_code == 204
    revoked = await client.get(f"{base(workspace)}/flows", headers=viewer.headers)
    assert revoked.status_code == 401
    assert revoked.json()["error"]["code"] == "invalid_api_key"


async def test_keys_only_reach_their_own_workspace(client: httpx.AsyncClient, admin: Actor) -> None:
    mine = await new_workspace(client, admin)
    other = await new_workspace(client, admin)
    key = await api_key(client, admin, mine)
    assert (await client.get(base(other), headers=key.headers)).status_code == 404
    garbage = {"authorization": "Bearer agst_aaaaaaaaaa_" + "x" * 43}
    assert (await client.get(base(mine), headers=garbage)).status_code == 401


async def test_only_owners_manage_keys(client: httpx.AsyncClient, admin: Actor) -> None:
    workspace = await new_workspace(client, admin)
    editor = await add_member(client, admin, workspace, "editor")
    response = await client.post(
        f"{base(workspace)}/api-keys", json={"name": "Mine"}, headers=editor.headers
    )
    assert response.status_code == 403
