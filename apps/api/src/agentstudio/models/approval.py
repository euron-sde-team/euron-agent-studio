from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from agentstudio.db.base import Base, IdMixin


class Approval(IdMixin, Base):
    """A run paused at a Human approval node, waiting for a reviewer's decision."""

    __tablename__ = "approvals"
    __table_args__ = (
        UniqueConstraint("run_id", "node_id"),
        Index("ix_approvals_workspace_id_created_at", "workspace_id", "created_at"),
        Index(
            "ix_approvals_pending",
            "workspace_id",
            "created_at",
            postgresql_where=text("status = 'pending'"),
        ),
        Index(
            "ix_approvals_pending_expiry",
            "expires_at",
            postgresql_where=text("status = 'pending'"),
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    flow_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("flows.id", ondelete="CASCADE"))
    node_id: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(Text, default="")
    context: Mapped[dict[str, Any]] = mapped_column(default=dict)
    status: Mapped[str] = mapped_column(String(16))
    expires_at: Mapped[datetime | None]
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_at: Mapped[datetime | None]
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
