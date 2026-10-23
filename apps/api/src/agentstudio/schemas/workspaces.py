from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import EmailStr, Field

from agentstudio.schemas.common import ApiModel


class WorkspaceSettings(ApiModel):
    """Per-workspace preferences."""

    default_model: str = Field(
        default="offline", max_length=120, description="Model reference new nodes start with."
    )
    run_retention_days: int = Field(default=90, ge=1, le=3650)


class WorkspaceCreate(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)


class WorkspaceUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    settings: WorkspaceSettings | None = None


class WorkspaceOut(ApiModel):
    id: uuid.UUID
    slug: str
    name: str
    description: str
    settings: WorkspaceSettings
    role: str
    created_at: datetime


class MemberOut(ApiModel):
    user_id: uuid.UUID
    email: str
    name: str
    role: str
    joined_at: datetime


class MemberAdd(ApiModel):
    email: EmailStr
    name: str | None = Field(default=None, max_length=120)
    role: Literal["owner", "editor", "viewer"] = "viewer"


class MemberAdded(ApiModel):
    member: MemberOut
    temporary_password: str | None = Field(
        default=None, description="Set only when the account was created by this call. Shown once."
    )


class MemberUpdate(ApiModel):
    role: Literal["owner", "editor", "viewer"]
