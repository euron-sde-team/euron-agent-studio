from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import ForeignKey, Index, Numeric, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from agentstudio.db.base import Base, IdMixin

Money = Numeric(14, 6)


class Run(IdMixin, Base):
    """One execution of a flow version (or of the draft). The row is the source of truth;
    queue messages only point at it."""

    __tablename__ = "runs"
    __table_args__ = (
        Index("ix_runs_workspace_id_created_at", "workspace_id", "created_at"),
        Index("ix_runs_flow_id_created_at", "flow_id", "created_at"),
        Index("ix_runs_workspace_id_status_created_at", "workspace_id", "status", "created_at"),
        # Small partial indexes for the reaper: only running (or queued) runs are in them.
        Index(
            "ix_runs_running_heartbeat",
            "heartbeat_at",
            postgresql_where=text("status = 'running'"),
        ),
        Index(
            "ix_runs_queued_enqueued_at",
            "enqueued_at",
            postgresql_where=text("status = 'queued'"),
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    flow_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("flows.id", ondelete="CASCADE"))
    flow_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("flow_versions.id", ondelete="CASCADE")
    )
    version: Mapped[int] = mapped_column(default=0)
    # A snapshot for draft runs only: versions are immutable, so version runs reference them.
    graph: Mapped[dict[str, Any] | None]
    status: Mapped[str] = mapped_column(String(16))
    trigger: Mapped[str] = mapped_column(String(16))
    inputs: Mapped[dict[str, Any]] = mapped_column(default=dict)
    outputs: Mapped[dict[str, Any] | None]
    error: Mapped[dict[str, Any] | None]
    prompt_tokens: Mapped[int] = mapped_column(default=0)
    completion_tokens: Mapped[int] = mapped_column(default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    cost_simulated: Mapped[bool] = mapped_column(default=False)
    step_count: Mapped[int] = mapped_column(default=0)
    triggered_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    triggered_by_api_key_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("api_keys.id", ondelete="SET NULL")
    )
    rerun_of_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL")
    )
    claims: Mapped[int] = mapped_column(default=0)
    heartbeat_at: Mapped[datetime | None]
    # When the run was last put on the queue. A run still queued long after this lost its
    # message (or never had one), and the reaper sends it again.
    enqueued_at: Mapped[datetime | None]
    cancel_requested_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    duration_ms: Mapped[int | None]


class RunStep(IdMixin, Base):
    """One node execution in a run; one row per loop iteration for nodes inside loops."""

    __tablename__ = "run_steps"
    __table_args__ = (
        UniqueConstraint("run_id", "node_id", "iteration"),
        Index("ix_run_steps_run_id_seq", "run_id", "seq"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    node_id: Mapped[str] = mapped_column(String(40))
    node_type: Mapped[str] = mapped_column(String(24))
    label: Mapped[str] = mapped_column(String(120))
    iteration: Mapped[str] = mapped_column(String(64), default="")
    seq: Mapped[int]
    status: Mapped[str] = mapped_column(String(16))
    attempt: Mapped[int] = mapped_column(default=1)
    input: Mapped[dict[str, Any] | None]
    output: Mapped[Any | None] = mapped_column(JSONB)
    error: Mapped[dict[str, Any] | None]
    events: Mapped[list[dict[str, Any]]] = mapped_column(default=list)
    handles: Mapped[list[str]] = mapped_column(JSONB, default=list)
    model: Mapped[str | None] = mapped_column(String(120))
    prompt_tokens: Mapped[int] = mapped_column(default=0)
    completion_tokens: Mapped[int] = mapped_column(default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    cached: Mapped[bool] = mapped_column(default=False)
    continued: Mapped[bool] = mapped_column(default=False)
    started_at: Mapped[datetime] = mapped_column(server_default=func.now())
    finished_at: Mapped[datetime | None]
    latency_ms: Mapped[int | None]
