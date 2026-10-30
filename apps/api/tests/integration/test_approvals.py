from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from fastapi import FastAPI
from sqlalchemy import update

from agentstudio.models import Approval
from agentstudio.services.runs import RunExecution
from tests.integration.conftest import (
    Actor,
    add_member,
    base,
    create_flow,
    new_workspace,
    wait_for_run,
)

TICKET = {
    "subject": "Charged twice for the March invoice",
    "body": (
        "I was charged twice for invoice INV-2041. Please refund the duplicate charge "
        "as soon as possible. Thanks, Dana Whitfield"
    ),
    "customer_email": "dana.whitfield@globex.example",
}


async def waiting_run(
    client: httpx.AsyncClient, admin: Actor, workspace: dict[str, Any]
) -> dict[str, Any]:
    flow = await create_flow(client, admin, workspace, name="Triage", template="support-triage")
    response = await client.post(
        f"{base(workspace)}/flows/{flow['id']}/runs?wait=15",
        json={"inputs": TICKET},
        headers=admin.headers,
    )
    run = response.json()
    assert run["status"] == "waiting", run
    return run


async def test_approving_resumes_on_the_approved_branch(
    client: httpx.AsyncClient, admin: Actor
) -> None:
    workspace = await new_workspace(client, admin)
    run = await waiting_run(client, admin, workspace)
    inbox = await client.get(f"{base(workspace)}/approvals?status=pending", headers=admin.headers)
    assert inbox.json()["total"] == 1
    approval = inbox.json()["items"][0]
    assert approval["title"] == "Review reply: Charged twice for the March invoice"
    assert approval["message"].startswith("Hi Dana,")
    assert approval["run_status"] == "waiting"
    decided = await client.post(
        f"{base(workspace)}/approvals/{approval['id']}/decision",
        json={"decision": "approve", "comment": "Send it"},
        headers=admin.headers,
    )
    assert decided.status_code == 200
    assert decided.json()["status"] == "approved"
    assert decided.json()["decided_by_name"] == "Ava Admin"
    finished = await wait_for_run(client, admin, workspace, run["id"], ("succeeded", "failed"))
    assert finished["outputs"]["status"] == "sent"
    assert finished["outputs"]["reviewer_note"] == "Send it"
    approve_step = next(s for s in finished["steps"] if s["node_id"] == "approve")
    assert approve_step["status"] == "succeeded"
    assert approve_step["handles"] == ["approved"]
    again = await client.post(
        f"{base(workspace)}/approvals/{approval['id']}/decision",
        json={"decision": "reject"},
        headers=admin.headers,
    )
    assert again.status_code == 409


async def test_rejecting_takes_the_rejected_branch(client: httpx.AsyncClient, admin: Actor) -> None:
    workspace = await new_workspace(client, admin)
    run = await waiting_run(client, admin, workspace)
    approval = (
        await client.get(f"{base(workspace)}/approvals?status=pending", headers=admin.headers)
    ).json()["items"][0]
    await client.post(
        f"{base(workspace)}/approvals/{approval['id']}/decision",
        json={"decision": "reject", "comment": "Escalate"},
        headers=admin.headers,
    )
    finished = await wait_for_run(client, admin, workspace, run["id"], ("succeeded", "failed"))
    assert finished["outputs"] == {
        "status": "escalated",
        "category": "billing",
        "priority": "high",
        "reviewer_note": "Escalate",
    }


async def test_viewers_cannot_decide(client: httpx.AsyncClient, admin: Actor) -> None:
    workspace = await new_workspace(client, admin)
    await waiting_run(client, admin, workspace)
    viewer = await add_member(client, admin, workspace, "viewer")
    approval = (await client.get(f"{base(workspace)}/approvals", headers=viewer.headers)).json()[
        "items"
    ][0]
    refused = await client.post(
        f"{base(workspace)}/approvals/{approval['id']}/decision",
        json={"decision": "approve"},
        headers=viewer.headers,
    )
    assert refused.status_code == 403


async def test_cancelling_a_waiting_run_cancels_its_approval(
    client: httpx.AsyncClient, admin: Actor
) -> None:
    workspace = await new_workspace(client, admin)
    run = await waiting_run(client, admin, workspace)
    cancelled = await client.post(
        f"{base(workspace)}/runs/{run['id']}/cancel", headers=admin.headers
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    approval = (await client.get(f"{base(workspace)}/approvals", headers=admin.headers)).json()[
        "items"
    ][0]
    assert approval["status"] == "cancelled"


async def test_expired_approvals_count_as_rejected(
    app: FastAPI, client: httpx.AsyncClient, admin: Actor
) -> None:
    workspace = await new_workspace(client, admin)
    run = await waiting_run(client, admin, workspace)
    container = app.state.container
    async with container.db.session() as session:
        await session.execute(
            update(Approval)
            .where(Approval.run_id == run["id"])
            .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        await session.commit()
    expired = (await RunExecution(container).reap()).expired
    assert expired >= 1
    finished = await wait_for_run(client, admin, workspace, run["id"], ("succeeded", "failed"))
    assert finished["outputs"]["status"] == "escalated"
    approval = (await client.get(f"{base(workspace)}/approvals", headers=admin.headers)).json()[
        "items"
    ][0]
    assert approval["status"] == "expired"
