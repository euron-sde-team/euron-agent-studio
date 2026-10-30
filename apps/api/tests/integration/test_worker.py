"""The SQS path: the API queues, a worker claims, and runs survive duplicates and lost workers."""

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select, update

from agentstudio.core.config import Settings
from agentstudio.integrations.queue import RunJob, SqsQueue
from agentstudio.main import create_app
from agentstudio.models import Run
from agentstudio.models.enums import RunStatus
from agentstudio.services.container import build_container
from agentstudio.services.runs import RunExecution
from agentstudio.worker import Worker
from tests.integration.conftest import (
    Actor,
    Infra,
    aws,
    base,
    create_flow,
    make_settings,
    new_workspace,
    wait_for_run,
)


@dataclass(slots=True)
class Queued:
    settings: Settings
    app: FastAPI
    client: httpx.AsyncClient
    infra: Infra


def drain(infra: Infra) -> int:
    """Delete every visible message: what a worker that took them and died leaves behind."""
    sqs, removed = aws("sqs"), 0
    while messages := sqs.receive_message(
        QueueUrl=infra.queue_url, MaxNumberOfMessages=10, WaitTimeSeconds=0
    ).get("Messages", []):
        for message in messages:
            sqs.delete_message(QueueUrl=infra.queue_url, ReceiptHandle=message["ReceiptHandle"])
            removed += 1
    return removed


def in_queue(infra: Infra) -> int:
    attributes = aws("sqs").get_queue_attributes(
        QueueUrl=infra.queue_url,
        AttributeNames=["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"],
    )["Attributes"]
    return int(attributes["ApproximateNumberOfMessages"]) + int(
        attributes["ApproximateNumberOfMessagesNotVisible"]
    )


async def until_empty(infra: Infra, within: float = 20) -> None:
    deadline = asyncio.get_running_loop().time() + within
    while in_queue(infra):
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("the queue never emptied")
        await asyncio.sleep(0.2)


@pytest.fixture
async def queued(infra: Infra, app: FastAPI, tmp_path: Path) -> AsyncIterator[Queued]:
    """A second API instance that puts runs on SQS instead of executing them itself."""
    drain(infra)
    settings = make_settings(infra, tmp_path, queue_backend="sqs")
    application = create_app(settings)
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as http:
            yield Queued(settings, application, http, infra)
    drain(infra)


@asynccontextmanager
async def worker(settings: Settings, **overrides: Any) -> AsyncIterator[Worker]:
    container = build_container(settings.model_copy(update=overrides), application_name="worker")
    assert isinstance(container.queue, SqsQueue)
    running = Worker(container, container.queue, poll_s=1)
    task = asyncio.create_task(running.run())
    try:
        yield running
    finally:
        running.stop()
        await asyncio.wait_for(task, 30)
        await container.close()


async def enqueued_at(app: FastAPI, run_id: str) -> datetime:
    async with app.state.container.db.session() as session:
        value = await session.scalar(select(Run.enqueued_at).where(Run.id == uuid.UUID(run_id)))
    assert value is not None
    return value


async def backdate_send(app: FastAPI, run_id: str) -> None:
    async with app.state.container.db.session() as session:
        await session.execute(
            update(Run)
            .where(Run.id == uuid.UUID(run_id))
            .values(enqueued_at=datetime.now(UTC) - timedelta(minutes=10))
        )
        await session.commit()


async def claims(app: FastAPI, run_id: str) -> int:
    async with app.state.container.db.session() as session:
        return int(await session.scalar(select(Run.claims).where(Run.id == uuid.UUID(run_id))))


async def start(
    q: Queued, actor: Actor, workspace: dict[str, Any], flow_id: str, inputs: Any
) -> str:
    response = await q.client.post(
        f"{base(workspace)}/flows/{flow_id}/runs", json={"inputs": inputs}, headers=actor.headers
    )
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "queued"
    return str(response.json()["id"])


async def test_a_worker_executes_queued_runs(queued: Queued, admin: Actor) -> None:
    workspace = await new_workspace(queued.client, admin)
    flow = await create_flow(queued.client, admin, workspace)
    run_id = await start(queued, admin, workspace, flow["id"], {"input": "via sqs"})
    assert in_queue(queued.infra) == 1
    detail = await queued.client.get(f"{base(workspace)}/runs/{run_id}", headers=admin.headers)
    assert detail.json()["status"] == "queued"
    async with worker(queued.settings):
        run = await wait_for_run(queued.client, admin, workspace, run_id, ("succeeded", "failed"))
        await until_empty(queued.infra)
    assert run["outputs"] == {"result": "via sqs"}
    assert await claims(queued.app, run_id) == 1


async def test_approvals_resume_on_a_worker(queued: Queued, admin: Actor) -> None:
    client = queued.client
    workspace = await new_workspace(client, admin)
    template = (await client.get("/api/v1/templates/support-triage", headers=admin.headers)).json()
    flow = await create_flow(client, admin, workspace, template="support-triage")
    run_id = await start(queued, admin, workspace, flow["id"], template["sample"])
    async with worker(queued.settings):
        await wait_for_run(client, admin, workspace, run_id, ("waiting",))
        approvals = await client.get(f"{base(workspace)}/approvals", headers=admin.headers)
        approval = approvals.json()["items"][0]
        await client.post(
            f"{base(workspace)}/approvals/{approval['id']}/decision",
            json={"decision": "approve"},
            headers=admin.headers,
        )
        run = await wait_for_run(client, admin, workspace, run_id, ("succeeded", "failed"))
        await until_empty(queued.infra)
    assert run["outputs"]["status"] == "sent"
    assert await claims(queued.app, run_id) == 2
    assert [s["node_id"] for s in run["steps"]].count("classify") == 1


async def test_duplicate_messages_never_run_a_flow_twice(queued: Queued, admin: Actor) -> None:
    workspace = await new_workspace(queued.client, admin)
    flow = await create_flow(queued.client, admin, workspace)
    run_id = await start(queued, admin, workspace, flow["id"], {"input": "once"})
    async with worker(queued.settings) as running:
        first = await wait_for_run(queued.client, admin, workspace, run_id, ("succeeded",))
        job = RunJob(uuid.UUID(run_id), uuid.UUID(workspace["id"]))
        await running.queue.enqueue(job)
        await running.queue.enqueue(job)
        await until_empty(queued.infra)
    again = await wait_for_run(queued.client, admin, workspace, run_id, ("succeeded",))
    assert again["finished_at"] == first["finished_at"]
    assert len(again["steps"]) == len(first["steps"])
    assert await claims(queued.app, run_id) == 1


async def test_runs_whose_worker_died_are_requeued_and_finished(
    queued: Queued, admin: Actor
) -> None:
    workspace = await new_workspace(queued.client, admin)
    flow = await create_flow(queued.client, admin, workspace)
    run_id = await start(queued, admin, workspace, flow["id"], {"input": "recovered"})
    # A worker took the message, claimed the run and died: no message, no heartbeat.
    assert drain(queued.infra) == 1
    stale = datetime.now(UTC) - timedelta(minutes=10)
    container = queued.app.state.container
    async with container.db.session() as session:
        await session.execute(
            update(Run)
            .where(Run.id == uuid.UUID(run_id))
            .values(status=RunStatus.RUNNING, claims=1, heartbeat_at=stale, started_at=stale)
        )
        await session.commit()
    assert (await RunExecution(container).reap()).requeued == 1
    async with worker(queued.settings):
        run = await wait_for_run(queued.client, admin, workspace, run_id, ("succeeded", "failed"))
    assert run["outputs"] == {"result": "recovered"}
    assert await claims(queued.app, run_id) == 2


async def test_runs_whose_message_was_lost_are_sent_again(queued: Queued, admin: Actor) -> None:
    workspace = await new_workspace(queued.client, admin)
    flow = await create_flow(queued.client, admin, workspace)
    run_id = await start(queued, admin, workspace, flow["id"], {"input": "resent"})
    # The message vanished before any worker claimed the run.
    assert drain(queued.infra) == 1
    execution = RunExecution(queued.app.state.container)
    sent = await enqueued_at(queued.app, run_id)
    await execution.reap()
    # Too early: a message that is merely slow must not be doubled.
    assert await enqueued_at(queued.app, run_id) == sent
    await backdate_send(queued.app, run_id)
    await execution.reap()
    assert await enqueued_at(queued.app, run_id) > sent
    async with worker(queued.settings):
        run = await wait_for_run(queued.client, admin, workspace, run_id, ("succeeded", "failed"))
    assert run["outputs"] == {"result": "resent"}
    assert await claims(queued.app, run_id) == 1


async def test_a_run_survives_an_unreachable_queue(
    queued: Queued, admin: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = await new_workspace(queued.client, admin)
    flow = await create_flow(queued.client, admin, workspace)
    container = queued.app.state.container

    async def unreachable(job: RunJob) -> None:
        raise ConnectionError("queue unreachable")

    with monkeypatch.context() as patch:
        patch.setattr(container.queue, "enqueue", unreachable)
        # Stored is accepted: the client gets its run, not an error it might retry.
        run_id = await start(queued, admin, workspace, flow["id"], {"input": "deferred"})
    assert in_queue(queued.infra) == 0
    await backdate_send(queued.app, run_id)
    await RunExecution(container).reap()
    async with worker(queued.settings):
        run = await wait_for_run(queued.client, admin, workspace, run_id, ("succeeded", "failed"))
    assert run["outputs"] == {"result": "deferred"}


async def test_runs_that_keep_losing_their_worker_are_stopped(queued: Queued, admin: Actor) -> None:
    workspace = await new_workspace(queued.client, admin)
    flow = await create_flow(queued.client, admin, workspace)
    run_id = await start(queued, admin, workspace, flow["id"], {"input": "doomed"})
    drain(queued.infra)
    stale = datetime.now(UTC) - timedelta(minutes=10)
    container = queued.app.state.container
    async with container.db.session() as session:
        await session.execute(
            update(Run)
            .where(Run.id == uuid.UUID(run_id))
            .values(status=RunStatus.RUNNING, claims=5, heartbeat_at=stale, started_at=stale)
        )
        await session.commit()
    assert (await RunExecution(container).reap()).requeued == 0
    run = await wait_for_run(queued.client, admin, workspace, run_id, ("failed",))
    assert run["error"]["code"] == "worker_lost"
    assert in_queue(queued.infra) == 0


async def test_a_stopping_worker_hands_its_runs_back(queued: Queued, admin: Actor) -> None:
    client = queued.client
    workspace = await new_workspace(client, admin)
    template = (await client.get("/api/v1/templates/research-brief", headers=admin.headers)).json()
    flow = await create_flow(client, admin, workspace, template="research-brief")
    run_id = await start(queued, admin, workspace, flow["id"], template["sample"])
    slow = {"offline_delay_ms_per_100_tokens": 4000, "worker_shutdown_grace_s": 1}
    async with worker(queued.settings, **slow):
        deadline = asyncio.get_running_loop().time() + 30
        while True:
            detail = (
                await client.get(f"{base(workspace)}/runs/{run_id}", headers=admin.headers)
            ).json()
            if any(s["node_id"] == "plan" and s["status"] == "succeeded" for s in detail["steps"]):
                break
            assert asyncio.get_running_loop().time() < deadline, detail["status"]
            await asyncio.sleep(0.1)
    # Stopped mid-run: the run goes back to the queue with the steps it finished.
    released = await wait_for_run(client, admin, workspace, run_id, ("queued",))
    assert any(s["node_id"] == "plan" for s in released["steps"])
    async with worker(queued.settings):
        run = await wait_for_run(client, admin, workspace, run_id, ("succeeded", "failed"))
        await until_empty(queued.infra)
    assert run["status"] == "succeeded", run["error"]
    assert run["outputs"]["questions_answered"] == 3
    keys = [(s["node_id"], s["iteration"]) for s in run["steps"]]
    assert len(keys) == len(set(keys))
    assert await claims(queued.app, run_id) == 2
