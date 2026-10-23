"""The run queue: SQS (with a dead-letter queue) in deployments, in process otherwise.

Messages carry ids only. The worker re-reads the run row and claims it with a conditional
update, so a duplicated or stale message is harmless: only a run that is still `queued` can
be claimed, and only once.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

import anyio
import orjson

from agentstudio.core.config import Settings
from agentstudio.core.logging import get_logger
from agentstudio.integrations import aws

log = get_logger("agentstudio.queue")


@dataclass(frozen=True, slots=True)
class RunJob:
    run_id: uuid.UUID
    workspace_id: uuid.UUID

    def encode(self) -> str:
        return orjson.dumps(
            {"run_id": str(self.run_id), "workspace_id": str(self.workspace_id)}
        ).decode()

    @classmethod
    def decode(cls, body: str) -> RunJob:
        data = orjson.loads(body)
        return cls(uuid.UUID(data["run_id"]), uuid.UUID(data["workspace_id"]))


@dataclass(frozen=True, slots=True)
class ReceivedJob:
    job: RunJob
    receipt: str
    receive_count: int


class JobQueue(Protocol):
    async def enqueue(self, job: RunJob) -> None: ...

    async def check(self) -> None: ...


Handler = Callable[[RunJob], Awaitable[object]]


class InlineQueue:
    """Executes runs as background tasks in the API process: development and tests."""

    def __init__(self) -> None:
        self._handler: Handler | None = None
        self._tasks: set[asyncio.Task[None]] = set()

    def bind(self, handler: Handler) -> None:
        self._handler = handler

    async def enqueue(self, job: RunJob) -> None:
        if self._handler is None:
            raise RuntimeError("InlineQueue has no handler bound")
        task = asyncio.create_task(self._run(job))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run(self, job: RunJob) -> None:
        if self._handler is None:
            return
        try:
            await self._handler(job)
        except Exception:
            log.exception("inline_run_failed", run_id=str(job.run_id))

    async def drain(self) -> None:
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def cancel_all(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def check(self) -> None:
        return None


class SqsQueue:
    def __init__(self, settings: Settings) -> None:
        if not settings.sqs_queue_url:
            raise ValueError("SQS_QUEUE_URL is required for QUEUE_BACKEND=sqs")
        self.url = settings.sqs_queue_url
        self._client = aws.sqs_client(settings)

    async def enqueue(self, job: RunJob) -> None:
        await anyio.to_thread.run_sync(
            lambda: self._client.send_message(QueueUrl=self.url, MessageBody=job.encode())
        )

    async def receive(
        self, *, max_messages: int, wait_s: int, visibility_s: int
    ) -> list[ReceivedJob]:
        response = await anyio.to_thread.run_sync(
            lambda: self._client.receive_message(
                QueueUrl=self.url,
                MaxNumberOfMessages=max_messages,
                WaitTimeSeconds=wait_s,
                VisibilityTimeout=visibility_s,
                MessageSystemAttributeNames=["ApproximateReceiveCount"],
            )
        )
        received = []
        for message in response.get("Messages", []):
            try:
                job = RunJob.decode(message["Body"])
            except (ValueError, KeyError):
                log.warning("queue_message_malformed", message_id=message.get("MessageId"))
                await self.delete(message["ReceiptHandle"])
                continue
            count = int(message.get("Attributes", {}).get("ApproximateReceiveCount", "1"))
            received.append(ReceivedJob(job, message["ReceiptHandle"], count))
        return received

    async def delete(self, receipt: str) -> None:
        await anyio.to_thread.run_sync(
            lambda: self._client.delete_message(QueueUrl=self.url, ReceiptHandle=receipt)
        )

    async def extend(self, receipt: str, visibility_s: int) -> None:
        await anyio.to_thread.run_sync(
            lambda: self._client.change_message_visibility(
                QueueUrl=self.url, ReceiptHandle=receipt, VisibilityTimeout=visibility_s
            )
        )

    async def depth(self) -> int:
        response = await anyio.to_thread.run_sync(
            lambda: self._client.get_queue_attributes(
                QueueUrl=self.url, AttributeNames=["ApproximateNumberOfMessages"]
            )
        )
        return int(response.get("Attributes", {}).get("ApproximateNumberOfMessages", "0"))

    async def check(self) -> None:
        await self.depth()


def build_queue(settings: Settings) -> InlineQueue | SqsQueue:
    if settings.queue_backend == "sqs":
        return SqsQueue(settings)
    return InlineQueue()
