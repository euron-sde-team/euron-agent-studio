"""Redis keys for cached reads, so writers know exactly what to invalidate."""

from __future__ import annotations

import uuid


def dashboard_key(workspace_id: uuid.UUID) -> str:
    return f"dash:{workspace_id}"
