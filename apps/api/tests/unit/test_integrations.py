import uuid
from pathlib import Path

import fakeredis
import pytest

from agentstudio.core.ids import uuid7
from agentstudio.integrations.queue import InlineQueue, RunJob
from agentstudio.integrations.storage import LocalStorage, knowledge_key
from agentstudio.integrations.trace import FINISHED_TTL_S, TraceBus, stream_key


def test_uuid7_layout_and_order() -> None:
    first, second = uuid7(), uuid7()
    assert first.version == 7
    assert first.variant == uuid.RFC_4122
    assert first.int >> 80 <= second.int >> 80


async def test_trace_streams_replay_from_any_point() -> None:
    redis = fakeredis.FakeAsyncRedis()
    bus = TraceBus(redis)
    run_id = uuid.uuid4()
    first = await bus.publish(run_id, "run.started", {"status": "running"})
    await bus.publish(run_id, "step.started", {"node_id": "start"})
    await bus.publish(run_id, "run.finished", {"status": "succeeded"})
    everything = await bus.read(run_id, block_ms=0)
    assert [event.type for event in everything] == ["run.started", "step.started", "run.finished"]
    assert everything[1].data == {"node_id": "start"}
    after_first = await bus.read(run_id, first, block_ms=0)
    assert [event.type for event in after_first] == ["step.started", "run.finished"]
    assert await bus.read(run_id, everything[-1].id, block_ms=0) == []
    assert 0 < await redis.ttl(stream_key(run_id)) <= 7 * 24 * 3600
    await bus.finished(run_id)
    assert 0 < await redis.ttl(stream_key(run_id)) <= FINISHED_TTL_S
    assert await bus.exists(run_id)


async def test_cancel_flags() -> None:
    bus = TraceBus(fakeredis.FakeAsyncRedis())
    run_id = uuid.uuid4()
    assert not await bus.cancel_requested(run_id)
    await bus.request_cancel(run_id)
    assert await bus.cancel_requested(run_id)


async def test_inline_queue_runs_and_drains() -> None:
    seen: list[RunJob] = []

    async def handler(job: RunJob) -> None:
        seen.append(job)

    queue = InlineQueue()
    queue.bind(handler)
    job = RunJob(uuid.uuid4(), uuid.uuid4())
    await queue.enqueue(job)
    await queue.drain()
    assert seen == [job]
    assert RunJob.decode(job.encode()) == job


async def test_local_storage_round_trip(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    key = knowledge_key(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), ".md")
    await storage.put(key, b"# Refunds", "text/markdown")
    assert await storage.get(key) == b"# Refunds"
    assert b"".join([chunk async for chunk in storage.stream(key)]) == b"# Refunds"
    await storage.delete(key)
    await storage.delete(key)


@pytest.mark.parametrize("key", ["../etc/passwd", "/abs/path", "a/../../b", "a b"])
async def test_local_storage_refuses_unsafe_keys(tmp_path: Path, key: str) -> None:
    with pytest.raises(ValueError, match=r"unsafe|escapes"):
        await LocalStorage(tmp_path).put(key, b"x", "text/plain")
