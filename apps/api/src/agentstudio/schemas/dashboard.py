from __future__ import annotations

import uuid
from datetime import date

from agentstudio.schemas.common import ApiModel
from agentstudio.schemas.runs import RunOut


class DayOut(ApiModel):
    date: date
    succeeded: int
    failed: int
    other: int


class TopFlowOut(ApiModel):
    flow_id: uuid.UUID
    name: str
    runs: int
    success_rate: float
    cost_usd: float


class DashboardStats(ApiModel):
    """The cached part of the dashboard: aggregates over the period."""

    period_days: int
    runs: int
    succeeded: int
    failed: int
    waiting: int
    running: int
    success_rate: float | None
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    p50_ms: int | None
    p95_ms: int | None
    pending_approvals: int
    flows: int
    published_flows: int
    daily: list[DayOut]
    top_flows: list[TopFlowOut]


class DashboardOut(DashboardStats):
    recent_runs: list[RunOut]
