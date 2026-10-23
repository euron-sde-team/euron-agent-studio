"""The one interface every model provider implements.

Requests and responses use the OpenAI Chat Completions shapes (messages, function tools,
`response_format`), because that is the wire format most providers speak and the one
exported scripts use. Adapters for other formats translate at their edge.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    # JSON text, exactly as the wire format carries it.
    arguments: str


@dataclass(slots=True)
class ChatRequest:
    model: str
    messages: list[dict[str, Any]]
    temperature: float = 0.2
    max_tokens: int = 800
    tools: list[dict[str, Any]] | None = None
    response_format: dict[str, Any] | None = None


@dataclass(slots=True)
class ChatResponse:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    finish_reason: str = "stop"


class ProviderError(Exception):
    """A provider failed. `retryable` errors (timeouts, 429, 5xx) are retried by the engine."""

    def __init__(
        self, message: str, *, code: str = "provider_error", retryable: bool = False
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.retryable = retryable


class ChatProvider(Protocol):
    name: str

    async def complete(self, request: ChatRequest) -> ChatResponse: ...

    async def aclose(self) -> None: ...
