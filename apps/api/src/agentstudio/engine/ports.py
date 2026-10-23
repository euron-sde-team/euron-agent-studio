"""What the engine needs from the outside world, as interfaces.

The executor never imports a database session, Redis or a concrete HTTP client. Services
hand it implementations of these ports; unit tests hand it fakes.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

from agentstudio.providers.base import ChatRequest, ChatResponse


@dataclass(slots=True)
class ModelResult:
    response: ChatResponse
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: Decimal
    simulated: bool
    cached: bool
    latency_ms: int


class ModelGateway(Protocol):
    async def complete(
        self, model_ref: str, request: ChatRequest, *, cache_ttl_s: int = 0
    ) -> ModelResult: ...


class KnowledgeSearcher(Protocol):
    async def search(
        self, knowledge_base_id: uuid.UUID, query: str, top_k: int
    ) -> list[dict[str, Any]]: ...


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    text: str
    content_type: str


class HttpClient(Protocol):
    async def send(self, spec: dict[str, Any], *, timeout_s: float) -> HttpResponse: ...


class CancelSignal(Protocol):
    async def requested(self) -> bool: ...


@dataclass(slots=True)
class EngineServices:
    models: ModelGateway
    knowledge: KnowledgeSearcher
    http: HttpClient
    cancel: CancelSignal
