"""Live run traces on Redis streams, plus the per-run cancel flag.

Every run has one stream (`run:<id>:events`). The executor's recorder appends events as they
happen; the SSE endpoint reads the stream from the beginning or from the browser's
`Last-Event-ID`, then blocks for new entries. Unlike PUBLISH, a stream keeps its history, so
nothing is lost between loading the run and subscribing, and a reconnect resumes exactly
where it stopped (see ADR 0005).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import orjson
from redis.asyncio import Redis

STREAM_MAXLEN = 5000
ACTIVE_TTL_S = 7 * 24 * 3600
FINISHED_TTL_S = 24 * 3600
CANCEL_TTL_S = 3600


@dataclass(frozen=True, slots=True)
class TraceEvent:
    id: str
    type: str
    data: dict[str, Any]


def stream_key(run_id: uuid.UUID) -> str:
    return f"run:{run_id}:events"


def cancel_key(run_id: uuid.UUID) -> str:
    return f"run:{run_id}:cancel"


class TraceBus:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def publish(self, run_id: uuid.UUID, event_type: str, data: dict[str, Any]) -> str:
        key = stream_key(run_id)
        async with self._redis.pipeline(transaction=False) as pipe:
            pipe.xadd(
                key,
                {"type": event_type, "data": orjson.dumps(data, default=str)},
                maxlen=STREAM_MAXLEN,
                approximate=True,
            )
            # Streams of runs that never finish (a crashed worker) still expire.
            pipe.expire(key, ACTIVE_TTL_S, nx=True)
            entry_id, _ = await pipe.execute()
        return entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)

    async def finished(self, run_id: uuid.UUID) -> None:
        await self._redis.expire(stream_key(run_id), FINISHED_TTL_S)

    async def exists(self, run_id: uuid.UUID) -> bool:
        return bool(await self._redis.exists(stream_key(run_id)))

    async def read(
        self, run_id: uuid.UUID, after: str = "0-0", *, block_ms: int = 15000, count: int = 500
    ) -> list[TraceEvent]:
        """Events after `after`, waiting up to `block_ms` when there are none yet."""
        response: Any = await self._redis.xread(
            {stream_key(run_id): after}, count=count, block=block_ms or None
        )
        events: list[TraceEvent] = []
        for _, entries in response or []:
            for entry_id, fields in entries:
                events.append(
                    TraceEvent(
                        _text(entry_id),
                        _text(fields.get(b"type", fields.get("type", b""))),
                        orjson.loads(fields.get(b"data", fields.get("data", b"{}"))),
                    )
                )
        return events

    async def request_cancel(self, run_id: uuid.UUID) -> None:
        await self._redis.set(cancel_key(run_id), b"1", ex=CANCEL_TTL_S)

    async def cancel_requested(self, run_id: uuid.UUID) -> bool:
        return bool(await self._redis.exists(cancel_key(run_id)))


def _text(value: Any) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)
