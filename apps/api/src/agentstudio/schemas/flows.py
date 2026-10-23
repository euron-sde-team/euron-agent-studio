from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator

from agentstudio.schemas.common import ApiModel

Tag = str


def _clean_tags(value: list[str]) -> list[str]:
    tags: list[str] = []
    for raw in value:
        tag = raw.strip().lower()
        if tag and tag not in tags:
            tags.append(tag[:32])
    return tags[:10]


class IssueOut(ApiModel):
    severity: Literal["error", "warning"]
    code: str
    message: str
    node_id: str | None = None
    edge_id: str | None = None
    field: str | None = None


class WebhookOut(ApiModel):
    enabled: bool
    hook_id: str | None
    url: str | None
    signature_header: str = "X-AgentStudio-Signature"
    secret: str | None = Field(
        default=None, description="The signing secret. Returned only when it is created or rotated."
    )


class FlowSummaryOut(ApiModel):
    id: uuid.UUID
    name: str
    description: str
    tags: list[str]
    published_version: int | None
    latest_version: int
    draft_revision: int
    node_count: int
    node_types: list[str]
    template_slug: str | None
    webhook_enabled: bool
    last_run_at: datetime | None
    last_run_status: str | None
    runs_7d: int = 0
    success_rate_7d: float | None = None
    created_at: datetime
    updated_at: datetime


class FlowOut(FlowSummaryOut):
    graph: dict[str, Any]
    draft_updated_at: datetime
    issues: list[IssueOut]
    webhook: WebhookOut


class FlowCreate(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    template: str | None = Field(default=None, max_length=64, description="A template slug.")

    _tags = field_validator("tags")(_clean_tags)


class FlowUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    tags: list[str] | None = Field(default=None, max_length=20)

    @field_validator("tags")
    @classmethod
    def _tags(cls, value: list[str] | None) -> list[str] | None:
        return _clean_tags(value) if value is not None else None


class DraftSave(ApiModel):
    graph: dict[str, Any]
    base_revision: int = Field(ge=1, description="The draft revision this edit was based on.")


class DraftSaved(ApiModel):
    draft_revision: int
    draft_updated_at: datetime
    issues: list[IssueOut]


class ValidateRequest(ApiModel):
    graph: dict[str, Any]


class ValidationOut(ApiModel):
    valid: bool
    issues: list[IssueOut]


class PublishRequest(ApiModel):
    notes: str = Field(default="", max_length=2000)


class VersionOut(ApiModel):
    id: uuid.UUID
    version: int
    notes: str
    graph_sha256: str
    node_count: int
    created_by_name: str | None
    created_at: datetime
    published: bool


class VersionDetail(VersionOut):
    graph: dict[str, Any]


class FlowDocument(ApiModel):
    """The portable export format (Export JSON / Import)."""

    format: Literal["agentstudio.flow"] = "agentstudio.flow"
    format_version: Literal[1] = 1
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    graph: dict[str, Any]
    exported_at: datetime | None = None
    source_version: int | None = None

    _tags = field_validator("tags")(_clean_tags)
