"""Initial schema: identity, flows and versions, runs and steps, approvals, knowledge, secrets.

Revision ID: 0001
Revises:
Create Date: 2026-10-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = pg.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)
MONEY = sa.Numeric(14, 6)


def _id() -> sa.Column[object]:
    return sa.Column("id", UUID, nullable=False)


def _created() -> sa.Column[object]:
    return sa.Column("created_at", TS, nullable=False, server_default=sa.func.now())


def _updated() -> sa.Column[object]:
    return sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now())


def _jsonb(name: str, default: str | None = None, *, nullable: bool = False) -> sa.Column[object]:
    server_default = sa.text(f"'{default}'::jsonb") if default is not None else None
    return sa.Column(name, pg.JSONB(), nullable=nullable, server_default=server_default)


def _fk(column: str, table: str, ondelete: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint([column], [f"{table}.id"], ondelete=ondelete)


def _check_in(column: str, values: Sequence[str], name: str) -> sa.CheckConstraint:
    listed = ", ".join(f"'{value}'" for value in values)
    return sa.CheckConstraint(f"{column} IN ({listed})", name=name)


RUN_STATUSES = ("queued", "running", "waiting", "succeeded", "failed", "cancelled")
STEP_STATUSES = ("running", "succeeded", "failed", "skipped", "waiting", "cancelled")
APPROVAL_STATUSES = ("pending", "approved", "rejected", "expired", "cancelled")


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")

    # Identity and access --------------------------------------------------------------
    op.create_table(
        "users",
        _id(),
        sa.Column("email", pg.CITEXT(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("session_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("failed_logins", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", TS),
        sa.Column("last_login_at", TS),
        _created(),
        _updated(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )

    op.create_table(
        "workspaces",
        _id(),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        _jsonb("settings", "{}"),
        sa.Column("created_by", UUID),
        _created(),
        _updated(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
        _fk("created_by", "users", "SET NULL"),
    )

    op.create_table(
        "memberships",
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        _created(),
        sa.PrimaryKeyConstraint("workspace_id", "user_id"),
        _fk("workspace_id", "workspaces", "CASCADE"),
        _fk("user_id", "users", "CASCADE"),
        _check_in("role", ("owner", "editor", "viewer"), "role"),
    )
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])

    op.create_table(
        "api_keys",
        _id(),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("created_by", UUID),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("prefix", sa.String(16), nullable=False),
        sa.Column("secret_hash", sa.String(64), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("last_used_at", TS),
        sa.Column("expires_at", TS),
        sa.Column("revoked_at", TS),
        _created(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("prefix"),
        _fk("workspace_id", "workspaces", "CASCADE"),
        _fk("created_by", "users", "SET NULL"),
        _check_in("role", ("editor", "viewer"), "role"),
    )
    op.create_index("ix_api_keys_workspace_id", "api_keys", ["workspace_id"])

    op.create_table(
        "audit_events",
        _id(),
        sa.Column("workspace_id", UUID),
        sa.Column("actor_user_id", UUID),
        sa.Column("actor_api_key_id", UUID),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_id", sa.String(64)),
        _jsonb("details", "{}"),
        _created(),
        sa.PrimaryKeyConstraint("id"),
        _fk("workspace_id", "workspaces", "CASCADE"),
        _fk("actor_user_id", "users", "SET NULL"),
        _fk("actor_api_key_id", "api_keys", "SET NULL"),
    )
    op.create_index(
        "ix_audit_events_workspace_id_created_at", "audit_events", ["workspace_id", "created_at"]
    )

    # Flows and versions ----------------------------------------------------------------
    op.create_table(
        "flows",
        _id(),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "tags",
            pg.ARRAY(sa.String(32)),
            nullable=False,
            server_default=sa.text("'{}'::varchar[]"),
        ),
        _jsonb("graph", "{}"),
        sa.Column("draft_revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("draft_updated_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("draft_updated_by", UUID),
        sa.Column("published_version_id", UUID),
        sa.Column("latest_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("webhook_id", sa.String(32)),
        sa.Column("webhook_secret", sa.LargeBinary()),
        sa.Column("webhook_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("template_slug", sa.String(64)),
        sa.Column("last_run_at", TS),
        sa.Column("last_run_status", sa.String(16)),
        sa.Column("created_by", UUID),
        _created(),
        _updated(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("webhook_id"),
        _fk("workspace_id", "workspaces", "CASCADE"),
        _fk("draft_updated_by", "users", "SET NULL"),
        _fk("created_by", "users", "SET NULL"),
    )
    op.create_index("ix_flows_workspace_id_updated_at", "flows", ["workspace_id", "updated_at"])
    op.create_index("ix_flows_tags", "flows", ["tags"], postgresql_using="gin")

    op.create_table(
        "flow_versions",
        _id(),
        sa.Column("flow_id", UUID, nullable=False),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        _jsonb("graph"),
        sa.Column("graph_sha256", sa.String(64), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by", UUID),
        _created(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("flow_id", "version"),
        _fk("flow_id", "flows", "CASCADE"),
        _fk("workspace_id", "workspaces", "CASCADE"),
        _fk("created_by", "users", "SET NULL"),
    )
    # flows and flow_versions reference each other; the second edge is added afterwards.
    op.create_foreign_key(
        "fk_flows_published_version_id_flow_versions",
        "flows",
        "flow_versions",
        ["published_version_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Runs, steps and approvals ----------------------------------------------------------
    op.create_table(
        "runs",
        _id(),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("flow_id", UUID, nullable=False),
        sa.Column("flow_version_id", UUID),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        _jsonb("graph", nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("trigger", sa.String(16), nullable=False),
        _jsonb("inputs", "{}"),
        _jsonb("outputs", nullable=True),
        _jsonb("error", nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", MONEY, nullable=False, server_default="0"),
        sa.Column("cost_simulated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("step_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("triggered_by_user_id", UUID),
        sa.Column("triggered_by_api_key_id", UUID),
        sa.Column("rerun_of_id", UUID),
        sa.Column("claims", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("heartbeat_at", TS),
        sa.Column("cancel_requested_at", TS),
        _created(),
        sa.Column("started_at", TS),
        sa.Column("finished_at", TS),
        sa.Column("duration_ms", sa.Integer()),
        sa.PrimaryKeyConstraint("id"),
        _fk("workspace_id", "workspaces", "CASCADE"),
        _fk("flow_id", "flows", "CASCADE"),
        _fk("flow_version_id", "flow_versions", "CASCADE"),
        _fk("triggered_by_user_id", "users", "SET NULL"),
        _fk("triggered_by_api_key_id", "api_keys", "SET NULL"),
        _fk("rerun_of_id", "runs", "SET NULL"),
        _check_in("status", RUN_STATUSES, "status"),
        _check_in("trigger", ("manual", "api", "webhook", "rerun"), "trigger"),
    )
    op.create_index("ix_runs_workspace_id_created_at", "runs", ["workspace_id", "created_at"])
    op.create_index("ix_runs_flow_id_created_at", "runs", ["flow_id", "created_at"])
    op.create_index(
        "ix_runs_workspace_id_status_created_at", "runs", ["workspace_id", "status", "created_at"]
    )
    # Small partial index for the reaper: only running runs are in it.
    op.create_index(
        "ix_runs_running_heartbeat",
        "runs",
        ["heartbeat_at"],
        postgresql_where=sa.text("status = 'running'"),
    )

    op.create_table(
        "run_steps",
        _id(),
        sa.Column("run_id", UUID, nullable=False),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("node_id", sa.String(40), nullable=False),
        sa.Column("node_type", sa.String(24), nullable=False),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("iteration", sa.String(64), nullable=False, server_default=""),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        _jsonb("input", nullable=True),
        _jsonb("output", nullable=True),
        _jsonb("error", nullable=True),
        _jsonb("events", "[]"),
        _jsonb("handles", "[]"),
        sa.Column("model", sa.String(120)),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", MONEY, nullable=False, server_default="0"),
        sa.Column("cached", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("continued", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("started_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", TS),
        sa.Column("latency_ms", sa.Integer()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "node_id", "iteration"),
        _fk("run_id", "runs", "CASCADE"),
        _fk("workspace_id", "workspaces", "CASCADE"),
        _check_in("status", STEP_STATUSES, "status"),
    )
    op.create_index("ix_run_steps_run_id_seq", "run_steps", ["run_id", "seq"])

    op.create_table(
        "approvals",
        _id(),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("run_id", UUID, nullable=False),
        sa.Column("flow_id", UUID, nullable=False),
        sa.Column("node_id", sa.String(40), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        _jsonb("context", "{}"),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("expires_at", TS),
        sa.Column("decided_by", UUID),
        sa.Column("decided_at", TS),
        sa.Column("comment", sa.Text(), nullable=False, server_default=""),
        _created(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "node_id"),
        _fk("workspace_id", "workspaces", "CASCADE"),
        _fk("run_id", "runs", "CASCADE"),
        _fk("flow_id", "flows", "CASCADE"),
        _fk("decided_by", "users", "SET NULL"),
        _check_in("status", APPROVAL_STATUSES, "status"),
    )
    op.create_index(
        "ix_approvals_workspace_id_created_at", "approvals", ["workspace_id", "created_at"]
    )
    op.create_index(
        "ix_approvals_pending",
        "approvals",
        ["workspace_id", "created_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_approvals_pending_expiry",
        "approvals",
        ["expires_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )

    # Knowledge --------------------------------------------------------------------------
    op.create_table(
        "knowledge_bases",
        _id(),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("document_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", UUID),
        _created(),
        _updated(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "name"),
        _fk("workspace_id", "workspaces", "CASCADE"),
        _fk("created_by", "users", "SET NULL"),
    )

    op.create_table(
        "knowledge_documents",
        _id(),
        sa.Column("knowledge_base_id", UUID, nullable=False),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("filename", sa.String(300), nullable=False),
        sa.Column("content_type", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(400), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("token_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", UUID),
        _created(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("knowledge_base_id", "sha256"),
        _fk("knowledge_base_id", "knowledge_bases", "CASCADE"),
        _fk("workspace_id", "workspaces", "CASCADE"),
        _fk("created_by", "users", "SET NULL"),
    )
    op.create_index(
        "ix_knowledge_documents_knowledge_base_id", "knowledge_documents", ["knowledge_base_id"]
    )

    op.create_table(
        "knowledge_chunks",
        _id(),
        sa.Column("document_id", UUID, nullable=False),
        sa.Column("knowledge_base_id", UUID, nullable=False),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("heading", sa.Text(), nullable=False, server_default=""),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "tsv",
            pg.TSVECTOR(),
            sa.Computed(
                "to_tsvector('english', coalesce(heading, '') || ' ' || text)", persisted=True
            ),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "ordinal"),
        _fk("document_id", "knowledge_documents", "CASCADE"),
        _fk("knowledge_base_id", "knowledge_bases", "CASCADE"),
        _fk("workspace_id", "workspaces", "CASCADE"),
    )
    op.create_index(
        "ix_knowledge_chunks_knowledge_base_id", "knowledge_chunks", ["knowledge_base_id"]
    )
    op.create_index("ix_knowledge_chunks_tsv", "knowledge_chunks", ["tsv"], postgresql_using="gin")

    # Secrets ----------------------------------------------------------------------------
    op.create_table(
        "secrets",
        _id(),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("description", sa.String(200), nullable=False, server_default=""),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("created_by", UUID),
        sa.Column("updated_by", UUID),
        sa.Column("last_used_at", TS),
        _created(),
        _updated(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "name"),
        _fk("workspace_id", "workspaces", "CASCADE"),
        _fk("created_by", "users", "SET NULL"),
        _fk("updated_by", "users", "SET NULL"),
    )


def downgrade() -> None:
    for table in (
        "secrets",
        "knowledge_chunks",
        "knowledge_documents",
        "knowledge_bases",
        "approvals",
        "run_steps",
        "runs",
    ):
        op.drop_table(table)
    op.drop_constraint("fk_flows_published_version_id_flow_versions", "flows", type_="foreignkey")
    for table in ("flow_versions", "flows", "audit_events", "api_keys", "memberships"):
        op.drop_table(table)
    op.drop_table("workspaces")
    op.drop_table("users")
