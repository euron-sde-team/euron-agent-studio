from __future__ import annotations

from datetime import datetime

from pydantic import Field

from agentstudio.schemas.common import ApiModel

SECRET_NAME_PATTERN = r"^[A-Z][A-Z0-9_]{0,63}$"  # noqa: S105 (a name format, not a secret)


class SecretOut(ApiModel):
    name: str
    description: str
    created_at: datetime
    updated_at: datetime
    last_used_at: datetime | None


class SecretCreate(ApiModel):
    name: str = Field(
        pattern=SECRET_NAME_PATTERN, description="UPPER_SNAKE_CASE, used as {{secrets.NAME}}."
    )
    value: str = Field(min_length=1, max_length=8000)
    description: str = Field(default="", max_length=200)


class SecretUpdate(ApiModel):
    value: str | None = Field(default=None, min_length=1, max_length=8000)
    description: str | None = Field(default=None, max_length=200)
