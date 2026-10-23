from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, LargeBinary, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from agentstudio.db.base import Base, IdMixin, TimestampMixin


class Flow(IdMixin, TimestampMixin, Base):
    """A workflow: an editable draft graph plus a pointer to its published version."""

    __tablename__ = "flows"
    __table_args__ = (
        Index("ix_flows_workspace_id_updated_at", "workspace_id", "updated_at"),
        Index("ix_flows_tags", "tags", postgresql_using="gin"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(32)), default=list)
    graph: Mapped[dict[str, Any]] = mapped_column(default=dict)
    # Optimistic concurrency: a draft save names the revision it was based on, so two tabs
    # editing one flow get a conflict instead of silently overwriting each other.
    draft_revision: Mapped[int] = mapped_column(default=1)
    draft_updated_at: Mapped[datetime] = mapped_column(server_default=func.now())
    draft_updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    published_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("flow_versions.id", ondelete="SET NULL", use_alter=True)
    )
    latest_version: Mapped[int] = mapped_column(default=0)
    webhook_id: Mapped[str | None] = mapped_column(String(32), unique=True)
    webhook_secret: Mapped[bytes | None] = mapped_column(LargeBinary)
    webhook_enabled: Mapped[bool] = mapped_column(default=False)
    template_slug: Mapped[str | None] = mapped_column(String(64))
    last_run_at: Mapped[datetime | None]
    last_run_status: Mapped[str | None] = mapped_column(String(16))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class FlowVersion(IdMixin, Base):
    """An immutable published snapshot of a flow's graph."""

    __tablename__ = "flow_versions"
    __table_args__ = (UniqueConstraint("flow_id", "version"),)

    flow_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("flows.id", ondelete="CASCADE"))
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    version: Mapped[int]
    graph: Mapped[dict[str, Any]]
    graph_sha256: Mapped[str] = mapped_column(String(64))
    notes: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
