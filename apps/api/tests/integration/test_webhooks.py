"""Signed webhooks start runs of the published version; everything else is refused."""

import json
import time
from typing import Any

import httpx

from agentstudio.core.crypto import sign_webhook
from tests.integration.conftest import Actor, base, create_flow, new_workspace, wait_for_run

HEADER = "x-agentstudio-signature"


async def enabled(
    client: httpx.AsyncClient, admin: Actor, workspace: dict[str, Any], *, publish: bool = True
) -> tuple[dict[str, Any], dict[str, Any]]:
    flow = await create_flow(client, admin, workspace)
    if publish:
        await client.post(
            f"{base(workspace)}/flows/{flow['id']}/publish", json={}, headers=admin.headers
        )
    response = await client.put(
        f"{base(workspace)}/flows/{flow['id']}/webhook", headers=admin.headers
    )
    assert response.status_code == 200, response.text
    return flow, response.json()


def signed(secret: str, body: bytes, at: int | None = None) -> dict[str, str]:
    return {
        HEADER: sign_webhook(secret, at or int(time.time()), body),
        "content-type": "application/json",
    }


async def test_a_signed_delivery_starts_a_run(client: httpx.AsyncClient, admin: Actor) -> None:
    workspace = await new_workspace(client, admin)
    flow, hook = await enabled(client, admin, workspace)
    assert hook["secret"].startswith("whsec_")
    assert hook["url"] == f"http://api.test/api/v1/hooks/{hook['hook_id']}"
    shown = await client.get(f"{base(workspace)}/flows/{flow['id']}/webhook", headers=admin.headers)
    assert shown.json()["secret"] is None
    body = json.dumps({"input": "from a webhook"}).encode()
    delivered = await client.post(hook["url"], content=body, headers=signed(hook["secret"], body))
    assert delivered.status_code == 202, delivered.text
    run = await wait_for_run(client, admin, workspace, delivered.json()["run_id"])
    assert run["outputs"] == {"result": "from a webhook"}
    assert run["trigger"] == "webhook"
    assert run["triggered_by"] == "Webhook"
    assert run["version_label"] == "v1"
    headers = signed(hook["secret"], body, int(time.time()) - 30)
    assert (await client.post(hook["url"], content=body, headers=headers)).status_code == 202
    replayed = await client.post(hook["url"], content=body, headers=headers)
    assert replayed.status_code == 409
    assert replayed.json()["error"]["code"] == "replayed"


async def test_bad_signatures_are_refused(client: httpx.AsyncClient, admin: Actor) -> None:
    workspace = await new_workspace(client, admin)
    _, hook = await enabled(client, admin, workspace)
    body = b'{"input": "x"}'
    missing = await client.post(hook["url"], content=body)
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "signature_missing"
    wrong = await client.post(hook["url"], content=body, headers=signed("whsec_wrong", body))
    assert wrong.json()["error"]["code"] == "signature_invalid"
    tampered = await client.post(
        hook["url"], content=b'{"input": "y"}', headers=signed(hook["secret"], body)
    )
    assert tampered.json()["error"]["code"] == "signature_invalid"
    old = await client.post(
        hook["url"], content=body, headers=signed(hook["secret"], body, int(time.time()) - 3600)
    )
    assert old.json()["error"]["code"] == "signature_expired"
    not_json = await client.post(
        hook["url"], content=b"nope", headers=signed(hook["secret"], b"nope")
    )
    assert not_json.status_code == 422
    assert not_json.json()["error"]["code"] == "invalid_json"


async def test_rotating_and_disabling(client: httpx.AsyncClient, admin: Actor) -> None:
    workspace = await new_workspace(client, admin)
    flow, hook = await enabled(client, admin, workspace)
    rotated = (
        await client.put(f"{base(workspace)}/flows/{flow['id']}/webhook", headers=admin.headers)
    ).json()
    assert rotated["hook_id"] == hook["hook_id"]
    body = b'{"input": "x"}'
    stale = await client.post(hook["url"], content=body, headers=signed(hook["secret"], body))
    assert stale.status_code == 401
    fresh = await client.post(hook["url"], content=body, headers=signed(rotated["secret"], body))
    assert fresh.status_code == 202
    await client.delete(f"{base(workspace)}/flows/{flow['id']}/webhook", headers=admin.headers)
    disabled = await client.post(
        hook["url"], content=body, headers=signed(rotated["secret"], body, int(time.time()) - 2)
    )
    assert disabled.status_code == 404
    unknown = await client.post("/api/v1/hooks/abcdefghijklmnop", content=body)
    assert unknown.status_code == 404


async def test_unpublished_flows_cannot_be_triggered(
    client: httpx.AsyncClient, admin: Actor
) -> None:
    workspace = await new_workspace(client, admin)
    _, hook = await enabled(client, admin, workspace, publish=False)
    body = b'{"input": "x"}'
    response = await client.post(hook["url"], content=body, headers=signed(hook["secret"], body))
    assert response.status_code == 409
