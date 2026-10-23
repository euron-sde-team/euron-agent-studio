"""The run worker: long-polls SQS and executes runs with bounded concurrency.

    python -m agentstudio.worker

- A message is only a pointer: the worker claims the run with a conditional update, so a
  duplicate or stale message is deleted without effect.
- Message visibility is extended while a run executes, so a long run is never handed to a
  second worker. A run that finishes or pauses for approval deletes its message.
- SIGTERM stops receiving; in-flight runs get WORKER_SHUTDOWN_GRACE_S to finish. Runs still
  going after that are released (status back to queued, message made visible at once) and
  resume elsewhere from their last finished step.
- One worker at a time (elected through Redis) re-queues runs whose heartbeat stopped and
  expires approvals past their deadline.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal

from prometheus_client import start_http_server

from agentstudio.core.config import get_settings
from agentstudio.core.logging import configure_logging, get_logger
from agentstudio.db.migrate import migrate
from agentstudio.integrations.queue import ReceivedJob, SqsQueue
from agentstudio.services.container import Container, build_container
from agentstudio.services.runs import RunExecution

log = get_logger("agentstudio.worker")
VISIBILITY_S = 300
REAPER_INTERVAL_S = 30


class Worker:
    def __init__(self, container: Container, queue: SqsQueue) -> None:
        self.c = container
        self.queue = queue
        self.execution = RunExecution(container)
        self.concurrency = container.settings.worker_concurrency
        self.stopping = asyncio.Event()
        self.inflight: dict[asyncio.Task[None], ReceivedJob] = {}

    def stop(self) -> None:
        if not self.stopping.is_set():
            log.info("worker_stopping", inflight=len(self.inflight))
            self.stopping.set()

    async def run(self) -> None:
        reaper = asyncio.create_task(self._reaper())
        while not self.stopping.is_set():
            free = self.concurrency - len(self.inflight)
            if free <= 0:
                await asyncio.wait(list(self.inflight), return_when=asyncio.FIRST_COMPLETED)
                continue
            try:
                received = await self.queue.receive(
                    max_messages=min(10, free), wait_s=10, visibility_s=VISIBILITY_S
                )
            except Exception:
                log.exception("queue_receive_failed")
                await asyncio.sleep(5)
                continue
            for item in received:
                task = asyncio.create_task(self._handle(item))
                self.inflight[task] = item
                task.add_done_callback(lambda done: self.inflight.pop(done, None))
        await self._drain()
        reaper.cancel()

    async def _drain(self) -> None:
        if not self.inflight:
            return
        grace = self.c.settings.worker_shutdown_grace_s
        _, pending = await asyncio.wait(list(self.inflight), timeout=grace)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def _handle(self, item: ReceivedJob) -> None:
        heartbeat = asyncio.create_task(self._extend(item.receipt))
        try:
            await self.execution.execute(item.job)
            await self.queue.delete(item.receipt)
        except asyncio.CancelledError:
            # Released by RunExecution: make the message visible so another worker resumes it.
            with contextlib.suppress(Exception):
                await asyncio.shield(self.queue.extend(item.receipt, 0))
            raise
        except Exception:
            log.exception("run_job_failed", run_id=str(item.job.run_id))
            with contextlib.suppress(Exception):
                await self.queue.extend(item.receipt, min(900, 30 * item.receive_count))
        finally:
            heartbeat.cancel()

    async def _extend(self, receipt: str) -> None:
        while True:
            await asyncio.sleep(VISIBILITY_S / 2)
            with contextlib.suppress(Exception):
                await self.queue.extend(receipt, VISIBILITY_S)

    async def _reaper(self) -> None:
        while True:
            await asyncio.sleep(REAPER_INTERVAL_S)
            try:
                if await self.c.redis.set("lock:reaper", b"1", ex=REAPER_INTERVAL_S - 5, nx=True):
                    requeued, expired = await self.execution.reap()
                    if requeued or expired:
                        log.info("reaped", requeued=requeued, expired=expired)
            except Exception:
                log.exception("reaper_failed")


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    if settings.is_production and (problems := settings.production_problems()):
        raise SystemExit("Refusing to start in production:\n  - " + "\n  - ".join(problems))
    if settings.migrate_on_boot:
        await migrate(settings)
    container = build_container(settings, application_name="agentstudio-worker")
    if not isinstance(container.queue, SqsQueue):
        raise SystemExit(
            "The worker needs QUEUE_BACKEND=sqs. With the inline queue the API runs flows itself."
        )
    if port := int(os.environ.get("WORKER_METRICS_PORT", "0")):
        start_http_server(port)
    worker = Worker(container, container.queue)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, worker.stop)
    log.info("worker_started", concurrency=worker.concurrency)
    try:
        await worker.run()
    finally:
        await container.close()
        log.info("worker_stopped")


if __name__ == "__main__":
    asyncio.run(main())
