"""The workspace dashboard: two weeks of runs, cached briefly in Redis."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from agentstudio.models.enums import RunStatus
from agentstudio.repositories.approvals import ApprovalRepository
from agentstudio.repositories.flows import FlowRepository
from agentstudio.repositories.runs import RunRepository
from agentstudio.schemas.dashboard import DashboardStats, DayOut, TopFlowOut
from agentstudio.services.cache import dashboard_key
from agentstudio.services.container import Container
from agentstudio.services.views import RunView, triggered_by

CACHE_TTL_S = 30
PERIOD_DAYS = 14


class DashboardService:
    def __init__(self, container: Container, session: AsyncSession) -> None:
        self.c = container
        self.session = session

    async def stats(self, workspace_id: uuid.UUID) -> DashboardStats:
        """Aggregates for the period, from the cache when a run has not changed them."""
        cached = await self.c.redis.get(dashboard_key(workspace_id))
        if cached:
            return DashboardStats.model_validate_json(cached)
        stats = await self._compute(workspace_id)
        await self.c.redis.set(dashboard_key(workspace_id), stats.model_dump_json(), ex=CACHE_TTL_S)
        return stats

    async def recent(self, workspace_id: uuid.UUID, limit: int = 6) -> list[RunView]:
        rows, _ = await RunRepository(self.session).page(workspace_id, limit=limit, offset=0)
        names = await triggered_by(self.session, [run for run, _ in rows])
        return [RunView(run, name, names.get(run.id)) for run, name in rows]

    async def _compute(self, workspace_id: uuid.UUID) -> DashboardStats:
        today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        since = today - timedelta(days=PERIOD_DAYS - 1)
        runs = RunRepository(self.session)
        totals = await runs.workspace_stats(workspace_id, since)
        days: dict[date, list[int]] = {
            (since + timedelta(days=offset)).date(): [0, 0, 0] for offset in range(PERIOD_DAYS)
        }
        for day, status, count in await runs.daily(workspace_id, since):
            bucket = days.setdefault(day, [0, 0, 0])
            index = 0 if status == RunStatus.SUCCEEDED else 1 if status == RunStatus.FAILED else 2
            bucket[index] += count
        flows, published = await FlowRepository(self.session).counts(workspace_id)
        finished = totals.succeeded + totals.failed
        return DashboardStats(
            period_days=PERIOD_DAYS,
            runs=totals.runs,
            succeeded=totals.succeeded,
            failed=totals.failed,
            waiting=totals.waiting,
            running=totals.running,
            success_rate=round(totals.succeeded / finished, 4) if finished else None,
            prompt_tokens=totals.prompt_tokens,
            completion_tokens=totals.completion_tokens,
            cost_usd=float(totals.cost_usd),
            p50_ms=totals.p50_ms,
            p95_ms=totals.p95_ms,
            pending_approvals=await ApprovalRepository(self.session).pending_count(workspace_id),
            flows=flows,
            published_flows=published,
            daily=[
                DayOut(date=d, succeeded=s, failed=f, other=o)
                for d, (s, f, o) in sorted(days.items())
            ],
            top_flows=[
                TopFlowOut(
                    flow_id=flow_id,
                    name=name,
                    runs=count,
                    success_rate=round(ok / count, 4) if count else 0.0,
                    cost_usd=float(cost),
                )
                for flow_id, name, count, ok, cost in await runs.top_flows(workspace_id, since)
            ],
        )
