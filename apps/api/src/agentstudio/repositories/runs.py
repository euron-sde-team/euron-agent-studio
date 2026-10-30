from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, case, cast, func, literal, select, update
from sqlalchemy.dialects.postgresql import JSONB, insert

from agentstudio.models import Flow, Run, RunStep
from agentstudio.models.enums import RunStatus
from agentstudio.repositories.base import Repository

ACTIVE = (RunStatus.QUEUED, RunStatus.RUNNING)


@dataclass(frozen=True, slots=True)
class RunTotals:
    prompt_tokens: int
    completion_tokens: int
    cost_usd: Decimal
    simulated: bool
    step_count: int


@dataclass(frozen=True, slots=True)
class WorkspaceRunStats:
    runs: int
    succeeded: int
    failed: int
    waiting: int
    running: int
    prompt_tokens: int
    completion_tokens: int
    cost_usd: Decimal
    p50_ms: int | None
    p95_ms: int | None


class RunRepository(Repository):
    async def add(self, run: Run) -> Run:
        self.session.add(run)
        await self.session.flush()
        return run

    async def get(
        self, workspace_id: uuid.UUID, run_id: uuid.UUID, *, fresh: bool = False
    ) -> Run | None:
        """A run; `fresh` re-reads every column even if this session already holds the row."""
        query = select(Run).where(Run.id == run_id, Run.workspace_id == workspace_id)
        if fresh:
            query = query.execution_options(populate_existing=True)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def claim(self, workspace_id: uuid.UUID, run_id: uuid.UUID, now: datetime) -> Run | None:
        """Take a queued run for execution. Only one caller can win: the update is conditional."""
        result = await self.session.execute(
            update(Run)
            .where(
                Run.id == run_id,
                Run.workspace_id == workspace_id,
                Run.status == RunStatus.QUEUED,
            )
            .values(
                status=RunStatus.RUNNING,
                claims=Run.claims + 1,
                heartbeat_at=now,
                started_at=func.coalesce(Run.started_at, now),
            )
            .returning(Run)
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def heartbeat(self, run_id: uuid.UUID, now: datetime) -> None:
        await self.session.execute(
            update(Run)
            .where(Run.id == run_id, Run.status == RunStatus.RUNNING)
            .values(heartbeat_at=now)
        )

    async def set_status(
        self,
        run_id: uuid.UUID,
        status: RunStatus,
        *,
        expected: tuple[RunStatus, ...],
        values: dict[str, Any] | None = None,
    ) -> bool:
        result = await self.session.execute(
            update(Run)
            .where(Run.id == run_id, Run.status.in_(expected))
            .values(status=status, **(values or {}))
        )
        return bool(getattr(result, "rowcount", 0))

    async def page(
        self,
        workspace_id: uuid.UUID,
        *,
        limit: int,
        offset: int,
        flow_id: uuid.UUID | None = None,
        status: str | None = None,
        trigger: str | None = None,
    ) -> tuple[list[tuple[Run, str]], int]:
        query = (
            select(Run, Flow.name)
            .join(Flow, Flow.id == Run.flow_id)
            .where(Run.workspace_id == workspace_id)
        )
        if flow_id is not None:
            query = query.where(Run.flow_id == flow_id)
        if status:
            query = query.where(Run.status == status)
        if trigger:
            query = query.where(Run.trigger == trigger)
        total = await self.count(query)
        result = await self.session.execute(
            query.order_by(Run.created_at.desc(), Run.id.desc()).limit(limit).offset(offset)
        )
        return [(run, name) for run, name in result.all()], total

    async def active_count(self, workspace_id: uuid.UUID) -> int:
        return int(
            await self.session.scalar(
                select(func.count()).where(Run.workspace_id == workspace_id, Run.status.in_(ACTIVE))
            )
            or 0
        )

    async def resend_due(
        self, before: datetime, now: datetime, limit: int = 50
    ) -> list[tuple[uuid.UUID, uuid.UUID]]:
        """Queued runs last sent before `before`, stamped as sent `now`: (run id, workspace id).

        A queued run is claimed within seconds of its message arriving, so one still queued
        long after it was sent lost that message, or never had one (the queue was unreachable
        when it started).
        """
        due = (
            select(Run.id)
            .where(Run.status == RunStatus.QUEUED, Run.enqueued_at < before)
            .order_by(Run.enqueued_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        result = await self.session.execute(
            update(Run)
            .where(Run.id.in_(due.scalar_subquery()), Run.status == RunStatus.QUEUED)
            .values(enqueued_at=now)
            .returning(Run.id, Run.workspace_id)
        )
        return [(row.id, row.workspace_id) for row in result]

    async def stale(self, before: datetime, limit: int = 50) -> list[Run]:
        result = await self.session.execute(
            select(Run)
            .where(Run.status == RunStatus.RUNNING, Run.heartbeat_at < before)
            .order_by(Run.heartbeat_at)
            .limit(limit)
        )
        return list(result.scalars())

    # Steps ------------------------------------------------------------------------------

    async def steps(self, run_id: uuid.UUID) -> list[RunStep]:
        result = await self.session.execute(
            select(RunStep).where(RunStep.run_id == run_id).order_by(RunStep.seq, RunStep.id)
        )
        return list(result.scalars())

    async def step(self, run_id: uuid.UUID, node_id: str, iteration: str) -> RunStep | None:
        result = await self.session.execute(
            select(RunStep).where(
                RunStep.run_id == run_id, RunStep.node_id == node_id, RunStep.iteration == iteration
            )
        )
        return result.scalar_one_or_none()

    async def start_step(self, values: dict[str, Any]) -> None:
        """Insert a step, or restart it (a retry after a crash reuses the row)."""
        statement = insert(RunStep).values(**values)
        restart: dict[str, Any] = {
            key: statement.excluded[key]
            for key in ("status", "attempt", "input", "seq", "started_at", "label", "node_type")
        }
        restart.update(
            output=None,
            error=None,
            events=[],
            handles=[],
            finished_at=None,
            latency_ms=None,
            prompt_tokens=0,
            completion_tokens=0,
            cost_usd=0,
            cached=False,
            continued=False,
        )
        await self.session.execute(
            statement.on_conflict_do_update(
                index_elements=["run_id", "node_id", "iteration"],
                set_=restart,
                # A step waiting for approval keeps its original start time and position.
                where=RunStep.status != "waiting",
            )
        )

    async def update_step(
        self, run_id: uuid.UUID, node_id: str, iteration: str, values: dict[str, Any]
    ) -> None:
        await self.session.execute(
            update(RunStep)
            .where(
                RunStep.run_id == run_id, RunStep.node_id == node_id, RunStep.iteration == iteration
            )
            .values(**values)
        )

    async def append_event(
        self, run_id: uuid.UUID, node_id: str, iteration: str, event: dict[str, Any]
    ) -> None:
        await self.session.execute(
            update(RunStep)
            .where(
                RunStep.run_id == run_id, RunStep.node_id == node_id, RunStep.iteration == iteration
            )
            .values(events=RunStep.events.op("||")(literal([event], JSONB)))
        )

    async def max_seq(self, run_id: uuid.UUID) -> int:
        return int(
            await self.session.scalar(select(func.max(RunStep.seq)).where(RunStep.run_id == run_id))
            or 0
        )

    async def totals(self, run_id: uuid.UUID) -> RunTotals:
        row = (
            await self.session.execute(
                select(
                    func.coalesce(func.sum(RunStep.prompt_tokens), 0),
                    func.coalesce(func.sum(RunStep.completion_tokens), 0),
                    func.coalesce(func.sum(RunStep.cost_usd), 0),
                    func.count(),
                ).where(RunStep.run_id == run_id, RunStep.status != "skipped")
            )
        ).one()
        simulated = await self.session.scalar(
            select(func.count()).where(
                RunStep.run_id == run_id, RunStep.model == "offline", RunStep.cost_usd > 0
            )
        )
        return RunTotals(int(row[0]), int(row[1]), Decimal(row[2]), bool(simulated), int(row[3]))

    # Dashboard --------------------------------------------------------------------------

    async def workspace_stats(self, workspace_id: uuid.UUID, since: datetime) -> WorkspaceRunStats:
        row = (
            await self.session.execute(
                select(
                    func.count(),
                    func.count(case((Run.status == RunStatus.SUCCEEDED, 1))),
                    func.count(case((Run.status == RunStatus.FAILED, 1))),
                    func.count(case((Run.status == RunStatus.WAITING, 1))),
                    func.count(case((Run.status.in_(ACTIVE), 1))),
                    func.coalesce(func.sum(Run.prompt_tokens), 0),
                    func.coalesce(func.sum(Run.completion_tokens), 0),
                    func.coalesce(func.sum(Run.cost_usd), 0),
                    func.percentile_cont(0.5).within_group(Run.duration_ms),
                    func.percentile_cont(0.95).within_group(Run.duration_ms),
                ).where(Run.workspace_id == workspace_id, Run.created_at >= since)
            )
        ).one()
        return WorkspaceRunStats(
            runs=int(row[0]),
            succeeded=int(row[1]),
            failed=int(row[2]),
            waiting=int(row[3]),
            running=int(row[4]),
            prompt_tokens=int(row[5]),
            completion_tokens=int(row[6]),
            cost_usd=Decimal(row[7]),
            p50_ms=int(row[8]) if row[8] is not None else None,
            p95_ms=int(row[9]) if row[9] is not None else None,
        )

    async def daily(self, workspace_id: uuid.UUID, since: datetime) -> list[tuple[Any, str, int]]:
        day = cast(func.date_trunc("day", Run.created_at), Date)
        result = await self.session.execute(
            select(day, Run.status, func.count())
            .where(Run.workspace_id == workspace_id, Run.created_at >= since)
            .group_by(day, Run.status)
            .order_by(day)
        )
        return [(d, status, int(count)) for d, status, count in result.all()]

    async def top_flows(
        self, workspace_id: uuid.UUID, since: datetime, limit: int = 5
    ) -> list[tuple[uuid.UUID, str, int, int, Decimal]]:
        result = await self.session.execute(
            select(
                Flow.id,
                Flow.name,
                func.count(Run.id),
                func.count(case((Run.status == RunStatus.SUCCEEDED, 1))),
                func.coalesce(func.sum(Run.cost_usd), 0),
            )
            .join(Run, Run.flow_id == Flow.id)
            .where(Flow.workspace_id == workspace_id, Run.created_at >= since)
            .group_by(Flow.id, Flow.name)
            .order_by(func.count(Run.id).desc(), Flow.name)
            .limit(limit)
        )
        return [
            (fid, name, int(n), int(ok), Decimal(cost)) for fid, name, n, ok, cost in result.all()
        ]
