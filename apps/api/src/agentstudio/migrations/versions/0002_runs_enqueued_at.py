"""Runs remember when they were last queued, so the reaper can resend lost messages.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("enqueued_at", sa.DateTime(timezone=True)))
    # Runs queued before this migration count as queued when they were created.
    op.execute("UPDATE runs SET enqueued_at = created_at WHERE status = 'queued'")
    op.create_index(
        "ix_runs_queued_enqueued_at",
        "runs",
        ["enqueued_at"],
        postgresql_where=sa.text("status = 'queued'"),
    )


def downgrade() -> None:
    op.drop_index("ix_runs_queued_enqueued_at", table_name="runs")
    op.drop_column("runs", "enqueued_at")
