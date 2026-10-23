"""Local models through Ollama's native chat API.

Ollama takes tool-call arguments as JSON objects (not strings), ignores tool call ids and
accepts a JSON schema in `format`; this adapter translates both ways so the engine can keep
one message format.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from agentstudio.providers.base import ChatRequest, ChatResponse, ProviderError, ToolCall


def _to_ollama(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for message in messages:
        item: dict[str, Any] = {"role": message["role"], "content": message.get("content") or ""}
        if message.get("tool_calls"):
            item["tool_calls"] = [
                {
                    "function": {
                        "name": call["function"]["name"],
                        "arguments": _arguments(call["function"].get("arguments")),
                    }
                }
                for call in message["tool_calls"]
            ]
        converted.append(item)
    return converted


def _arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw or "{}")
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


class OllamaProvider:
    name = "ollama"

    def __init__(
        self,
        base_url: str,
        *,
        timeout_s: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(timeout_s, connect=10.0),
            transport=transport,
        )

    async def complete(self, request: ChatRequest) -> ChatResponse:
        body: dict[str, Any] = {
            "model": request.model,
            "messages": _to_ollama(request.messages),
            "stream": False,
            "options": {"temperature": request.temperature, "num_predict": request.max_tokens},
        }
        if request.tools:
            body["tools"] = request.tools
        response_format = request.response_format or {}
        if response_format.get("type") == "json_schema":
            body["format"] = (response_format.get("json_schema") or {}).get("schema") or "json"
        elif response_format.get("type") == "json_object":
            body["format"] = "json"
        try:
            response = await self._client.post("/api/chat", json=body)
        except httpx.TimeoutException as exc:
            raise ProviderError(
                "Ollama timed out.", code="provider_timeout", retryable=True
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                "Ollama could not be reached.", code="provider_unreachable", retryable=True
            ) from exc
        if response.status_code >= 400:
            raise ProviderError(
                f"Ollama returned HTTP {response.status_code}: {response.text[:300]}",
                code="provider_http_error",
                retryable=response.status_code >= 500 or response.status_code == 429,
            )
        try:
            data = response.json()
            message = data["message"]
        except (ValueError, KeyError, TypeError) as exc:
            raise ProviderError(
                "Ollama sent a response this client cannot read.",
                code="provider_bad_response",
                retryable=True,
            ) from exc
        calls = [
            ToolCall(
                id=f"call_{index}",
                name=str(call["function"]["name"]),
                arguments=json.dumps(_arguments(call["function"].get("arguments"))),
            )
            for index, call in enumerate(message.get("tool_calls") or [], start=1)
        ]
        return ChatResponse(
            content=message.get("content") or None,
            tool_calls=calls,
            prompt_tokens=int(data.get("prompt_eval_count") or 0),
            completion_tokens=int(data.get("eval_count") or 0),
            finish_reason="tool_calls" if calls else str(data.get("done_reason") or "stop"),
        )

    async def aclose(self) -> None:
        await self._client.aclose()
