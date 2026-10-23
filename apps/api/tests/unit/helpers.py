"""Builders for graphs and fakes for the engine's ports."""

from __future__ import annotations

import asyncio
import itertools
import uuid
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any

from agentstudio.engine.graph import GraphDocument
from agentstudio.engine.ports import EngineServices, HttpResponse, ModelResult
from agentstudio.providers.base import ChatRequest, ChatResponse, ToolCall

KB_ID = uuid.UUID("00000000-0000-7000-8000-00000000000b")
_x = itertools.count()


def node(
    node_id: str,
    node_type: str,
    *,
    x: float | None = None,
    y: float = 0,
    settings: dict[str, Any] | None = None,
    label: str = "",
    **config: Any,
) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": node_type,
        "position": {"x": float(next(_x) * 10) if x is None else x, "y": y},
        "label": label,
        "config": config,
        "settings": settings or {},
    }


def edge(
    source: str, target: str, source_handle: str = "out", target_handle: str = "in"
) -> dict[str, Any]:
    return {
        "id": f"{source}.{source_handle}->{target}.{target_handle}",
        "source": source,
        "source_handle": source_handle,
        "target": target,
        "target_handle": target_handle,
    }


def graph(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> GraphDocument:
    return GraphDocument.model_validate({"nodes": nodes, "edges": edges})


def start(*names: str, **kwargs: Any) -> dict[str, Any]:
    return node(
        "start", "start", x=0, inputs=[{"name": name, "type": "string"} for name in names], **kwargs
    )


def output(node_id: str = "result", **fields: str) -> dict[str, Any]:
    return node(node_id, "output", fields=[{"name": k, "value": v} for k, v in fields.items()])


def llm(node_id: str, prompt: str, **config: Any) -> dict[str, Any]:
    return node(node_id, "llm", prompt=prompt, **config)


Responder = Callable[[str, ChatRequest], ChatResponse | Awaitable[ChatResponse]]


def echo(_: str, request: ChatRequest) -> ChatResponse:
    """A fake model that answers with the last user message."""
    last = next(m for m in reversed(request.messages) if m["role"] == "user")
    return ChatResponse(content=f"echo: {last['content']}", prompt_tokens=10, completion_tokens=5)


class FakeModels:
    def __init__(self, responder: Responder = echo, *, price: Decimal = Decimal("0.001")) -> None:
        self.responder = responder
        self.price = price
        self.requests: list[tuple[str, ChatRequest]] = []

    async def complete(
        self, model_ref: str, request: ChatRequest, *, cache_ttl_s: int = 0
    ) -> ModelResult:
        self.requests.append((model_ref, request))
        produced = self.responder(model_ref, request)
        response = await produced if asyncio.iscoroutine(produced) else produced
        assert isinstance(response, ChatResponse)
        return ModelResult(
            response=response,
            provider="fake",
            model=model_ref,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            cost_usd=self.price,
            simulated=False,
            cached=False,
            latency_ms=1,
        )


class FakeKnowledge:
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def search(
        self, knowledge_base_id: uuid.UUID, query: str, top_k: int
    ) -> list[dict[str, Any]]:
        self.queries.append(query)
        return [
            {
                "title": "Refund policy",
                "heading": "",
                "text": f"Answer about {query}.",
                "snippet": "",
                "score": 0.5,
                "document_id": str(KB_ID),
            }
        ][:top_k]


class FakeHttp:
    def __init__(self, handler: Callable[[dict[str, Any]], HttpResponse] | None = None) -> None:
        self.handler = handler or (
            lambda spec: HttpResponse(200, '{"ok": true}', "application/json")
        )
        self.sent: list[dict[str, Any]] = []

    async def send(self, spec: dict[str, Any], *, timeout_s: float) -> HttpResponse:
        self.sent.append(spec)
        return self.handler(spec)


class FakeCancel:
    def __init__(self) -> None:
        self.flag = False

    async def requested(self) -> bool:
        return self.flag


def services(
    models: FakeModels | None = None,
    *,
    http: FakeHttp | None = None,
    cancel: FakeCancel | None = None,
) -> EngineServices:
    return EngineServices(
        models=models or FakeModels(),
        knowledge=FakeKnowledge(),
        http=http or FakeHttp(),
        cancel=cancel or FakeCancel(),
    )


def tool_call_response(*calls: tuple[str, str]) -> ChatResponse:
    return ChatResponse(
        content=None,
        tool_calls=[
            ToolCall(id=f"call_{i}", name=name, arguments=args)
            for i, (name, args) in enumerate(calls, 1)
        ],
        prompt_tokens=20,
        completion_tokens=8,
        finish_reason="tool_calls",
    )
