from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from agentstudio.schemas.common import ApiModel


class KnowledgeBaseCreate(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)


class KnowledgeBaseUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)


class KnowledgeBaseOut(ApiModel):
    id: uuid.UUID
    name: str
    description: str
    document_count: int
    chunk_count: int
    created_at: datetime
    updated_at: datetime


class DocumentOut(ApiModel):
    id: uuid.UUID
    knowledge_base_id: uuid.UUID
    title: str
    filename: str
    content_type: str
    size_bytes: int
    chunk_count: int
    token_count: int
    created_at: datetime


class SearchIn(ApiModel):
    query: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=4, ge=1, le=20)


class SearchHitOut(ApiModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    title: str
    heading: str
    text: str
    snippet: str
    score: float


class SearchOut(ApiModel):
    results: list[SearchHitOut]
    context: str
