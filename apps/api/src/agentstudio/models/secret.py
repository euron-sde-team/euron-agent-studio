from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, LargeBinary, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from agentstudio.db.base import Base, IdMixin, TimestampMixin


class Secret(IdMixin, TimestampMixin, Base):
    """A workspace credential. Only AES-256-GCM ciphertext is stored; the API never returns it."""

    __tablename__ = "secrets"
    __table_args__ = (UniqueConstraint("workspace_id", "name"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(String(200), default="")
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    last_used_at: Mapped[datetime | None]
