from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from agentstudio.schemas.approvals import ApprovalOut
from agentstudio.schemas.common import ApiModel


class RunCreate(ApiModel):
    inputs: dict[str, Any] = Field(default_factory=dict)
    version: Literal["auto", "draft", "published"] | int = Field(
        default="auto",
        description="auto runs the published version when there is one, otherwise the draft.",
    )


class RunOut(ApiModel):
    id: uuid.UUID
    flow_id: uuid.UUID
    flow_name: str
    version: int
    version_label: str
    status: str
    trigger: str
    inputs: dict[str, Any]
    outputs: dict[str, Any] | None
    error: dict[str, Any] | None
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    cost_simulated: bool
    step_count: int
    triggered_by: str | None
    rerun_of_id: uuid.UUID | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None


class StepOut(ApiModel):
    id: uuid.UUID
    node_id: str
    node_type: str
    label: str
    iteration: str
    seq: int
    status: str
    attempt: int
    input: dict[str, Any] | None
    output: Any
    error: dict[str, Any] | None
    events: list[dict[str, Any]]
    handles: list[str]
    model: str | None
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    cached: bool
    continued: bool
    started_at: datetime
    finished_at: datetime | None
    latency_ms: int | None


class RunDetail(RunOut):
    graph: dict[str, Any]
    steps: list[StepOut]
    approvals: list[ApprovalOut]
