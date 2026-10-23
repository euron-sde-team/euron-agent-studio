"""Server-sent events for run traces.

A connection replays the run's Redis stream from the beginning, or from the browser's
`Last-Event-ID`, then waits for new entries, sending a comment every 15 seconds to keep
proxies from closing it. It ends after `run.finished`, or after five minutes (the browser
reconnects and resumes exactly where it stopped). Runs whose stream has expired are replayed
from Postgres instead.
"""

from __future__ import annotations

import re
import time
from collections.abc import AsyncIterator
from typing import Any

import orjson

from agentstudio.models import Run
from agentstudio.models.enums import RunStatus
from agentstudio.repositories.runs import RunRepository
from agentstudio.services.container import Container

MAX_CONNECTION_S = 300
KEEPALIVE_MS = 15_000
_STREAM_ID = re.compile(r"^\d{1,20}-\d{1,20}$")


def frame(event_id: str | None, event: str, data: dict[str, Any]) -> str:
    lines = []
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.append("data: " + orjson.dumps(data, default=str).decode())
    return "\n".join(lines) + "\n\n"


class RunEvents:
    def __init__(self, container: Container) -> None:
        self.c = container

    async def stream(self, run: Run, last_event_id: str | None) -> AsyncIterator[str]:
        # Tell EventSource how soon to reconnect when the connection drops.
        yield "retry: 2000\n\n"
        if not await self.c.trace.exists(run.id):
            async for item in self._replay(run):
                yield item
            return
        cursor = last_event_id if last_event_id and _STREAM_ID.match(last_event_id) else "0-0"
        opened = time.monotonic()
        while time.monotonic() - opened < MAX_CONNECTION_S:
            events = await self.c.trace.read(run.id, cursor, block_ms=KEEPALIVE_MS)
            if not events:
                yield ": keep-alive\n\n"
                continue
            for event in events:
                cursor = event.id
                yield frame(event.id, event.type, event.data)
                if event.type == "run.finished":
                    return

    async def _replay(self, run: Run) -> AsyncIterator[str]:
        """The trace of a run whose stream expired, rebuilt from its rows."""
        async with self.c.db.session() as session:
            steps = await RunRepository(session).steps(run.id)
        yield frame(None, "run.started", {"status": RunStatus.RUNNING, "replayed": True})
        for step in steps:
            yield frame(
                None,
                "step.finished",
                {
                    "node_id": step.node_id,
                    "node_type": step.node_type,
                    "label": step.label,
                    "iteration": step.iteration,
                    "status": step.status,
                    "attempt": step.attempt,
                    "input": step.input,
                    "output": step.output,
                    "error": step.error,
                    "handles": step.handles,
                    "model": step.model,
                    "prompt_tokens": step.prompt_tokens,
                    "completion_tokens": step.completion_tokens,
                    "cost_usd": float(step.cost_usd),
                    "cached": step.cached,
                    "latency_ms": step.latency_ms,
                },
            )
        if run.status == RunStatus.WAITING:
            yield frame(None, "run.waiting", {"status": run.status})
        else:
            yield frame(
                None,
                "run.finished",
                {
                    "status": run.status,
                    "outputs": run.outputs,
                    "error": run.error,
                    "prompt_tokens": run.prompt_tokens,
                    "completion_tokens": run.completion_tokens,
                    "cost_usd": float(run.cost_usd),
                    "duration_ms": run.duration_ms,
                },
            )
