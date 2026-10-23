"""Any OpenAI-compatible Chat Completions endpoint.

OpenAI itself, and the many servers that speak the same protocol: Azure OpenAI gateways,
Groq, Together, Mistral, DeepSeek, OpenRouter, vLLM, LM Studio, llama.cpp and others. Tools,
`response_format` and usage pass through unchanged, because the engine already speaks this
format.
"""

from __future__ import annotations

from typing import Any

import httpx

from agentstudio.providers.base import ChatRequest, ChatResponse, ProviderError, ToolCall

_RETRYABLE = frozenset({408, 409, 425, 429})


def _detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:300]
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        return str(error.get("message", ""))[:300]
    return str(error or payload)[:300]


class OpenAICompatibleProvider:
    name = "openai"

    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        *,
        timeout_s: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"authorization": f"Bearer {api_key}"} if api_key else {},
            timeout=httpx.Timeout(timeout_s, connect=10.0),
            transport=transport,
        )

    async def complete(self, request: ChatRequest) -> ChatResponse:
        body: dict[str, Any] = {
            "model": request.model,
            "messages": request.messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        if request.tools:
            body["tools"] = request.tools
        if request.response_format:
            body["response_format"] = request.response_format
        try:
            response = await self._client.post("/chat/completions", json=body)
        except httpx.TimeoutException as exc:
            raise ProviderError(
                "The model provider timed out.", code="provider_timeout", retryable=True
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                "The model provider could not be reached.",
                code="provider_unreachable",
                retryable=True,
            ) from exc
        if response.status_code >= 400:
            status = response.status_code
            raise ProviderError(
                f"The model provider returned HTTP {status}: {_detail(response)}",
                code="provider_http_error",
                retryable=status in _RETRYABLE or status >= 500,
            )
        try:
            data = response.json()
            choice = data["choices"][0]
            message = choice["message"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError(
                "The model provider sent a response this client cannot read.",
                code="provider_bad_response",
                retryable=True,
            ) from exc
        calls = [
            ToolCall(
                id=str(call.get("id") or f"call_{index}"),
                name=str(call["function"]["name"]),
                arguments=str(call["function"].get("arguments") or "{}"),
            )
            for index, call in enumerate(message.get("tool_calls") or [], start=1)
        ]
        usage = data.get("usage") or {}
        return ChatResponse(
            content=message.get("content"),
            tool_calls=calls,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            finish_reason=str(choice.get("finish_reason") or "stop"),
        )

    async def aclose(self) -> None:
        await self._client.aclose()
