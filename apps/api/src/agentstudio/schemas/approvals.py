from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from agentstudio.schemas.common import ApiModel


class ApprovalOut(ApiModel):
    id: uuid.UUID
    run_id: uuid.UUID
    flow_id: uuid.UUID
    flow_name: str
    node_id: str
    title: str
    message: str
    context: dict[str, Any]
    status: str
    run_status: str
    expires_at: datetime | None
    decided_by_name: str | None
    decided_at: datetime | None
    comment: str
    created_at: datetime


class DecisionIn(ApiModel):
    decision: Literal["approve", "reject"]
    comment: str = Field(default="", max_length=2000)
