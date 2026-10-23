from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from agentstudio.schemas.common import ApiModel


class AuditEventOut(ApiModel):
    id: uuid.UUID
    action: str
    target_type: str
    target_id: str | None
    details: dict[str, Any]
    actor_name: str | None
    created_at: datetime
