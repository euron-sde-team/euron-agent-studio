import json
from decimal import Decimal
from typing import Any

import fakeredis
import httpx
import pytest

from agentstudio.core.config import Settings
from agentstudio.providers.base import ChatRequest, ChatResponse, ProviderError
from agentstudio.providers.ollama import OllamaProvider
from agentstudio.providers.openai_compat import OpenAICompatibleProvider
from agentstudio.providers.pricing import cost, parse_prices
from agentstudio.providers.registry import ModelRegistry, split_ref

TOOLS = [
    {
        "type": "function",
        "function": {"name": "calc", "parameters": {"type": "object", "properties": {}}},
    }
]


def openai_with(handler: Any) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        "https://llm.example.com/v1/", "sk-test", transport=httpx.MockTransport(handler)
    )


async def test_openai_requests_and_responses_round_trip() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "c1",
                                    "type": "function",
                                    "function": {
                                        "name": "calc",
                                        "arguments": '{"expression": "2+2"}',
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 7},
            },
        )

    provider = openai_with(handler)
    response = await provider.complete(
        ChatRequest(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "2+2?"}],
            tools=TOOLS,
            response_format={"type": "json_object"},
        )
    )
    await provider.aclose()
    assert seen["url"] == "https://llm.example.com/v1/chat/completions"
    assert seen["auth"] == "Bearer sk-test"
    assert seen["body"]["tools"] == TOOLS
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert response.tool_calls[0].name == "calc"
    assert response.tool_calls[0].arguments == '{"expression": "2+2"}'
    assert (response.prompt_tokens, response.completion_tokens, response.finish_reason) == (
        12,
        7,
        "tool_calls",
    )


@pytest.mark.parametrize(
    ("status", "retryable"), [(429, True), (503, True), (400, False), (401, False)]
)
async def test_openai_errors_say_whether_to_retry(status: int, retryable: bool) -> None:
    provider = openai_with(lambda _: httpx.Response(status, json={"error": {"message": "nope"}}))
    with pytest.raises(ProviderError) as error:
        await provider.complete(ChatRequest(model="m", messages=[]))
    assert error.value.retryable is retryable
    assert "nope" in error.value.message


async def test_openai_network_failures_are_retryable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow", request=request)

    with pytest.raises(ProviderError) as error:
        await openai_with(handler).complete(ChatRequest(model="m", messages=[]))
    assert error.value.code == "provider_timeout"
    assert error.value.retryable


async def test_ollama_translates_tool_calls_and_formats() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {"function": {"name": "calc", "arguments": {"expression": "1+1"}}}
                    ],
                },
                "prompt_eval_count": 30,
                "eval_count": 4,
                "done_reason": "stop",
            },
        )

    provider = OllamaProvider("http://ollama.local:11434", transport=httpx.MockTransport(handler))
    messages = [
        {"role": "user", "content": "add"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "x",
                    "type": "function",
                    "function": {"name": "calc", "arguments": '{"expression": "3+3"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "x", "content": '{"result": 6}'},
    ]
    schema = {"type": "object", "properties": {"a": {"type": "string"}}}
    response = await provider.complete(
        ChatRequest(
            model="llama3.2",
            messages=messages,
            tools=TOOLS,
            response_format={"type": "json_schema", "json_schema": {"schema": schema}},
        )
    )
    await provider.aclose()
    body = seen["body"]
    assert body["stream"] is False
    assert body["format"] == schema
    assert body["messages"][1]["tool_calls"][0]["function"]["arguments"] == {"expression": "3+3"}
    assert body["messages"][1]["content"] == ""
    assert response.tool_calls[0].arguments == '{"expression": "1+1"}'
    assert response.finish_reason == "tool_calls"
    assert response.prompt_tokens == 30


def test_prices_are_parsed_and_costs_rounded() -> None:
    assert parse_prices('{"my-model": [1, 2]}') == {"my-model": (1.0, 2.0)}
    assert parse_prices("") == {}
    with pytest.raises(ValueError, match="input, output"):
        parse_prices('{"bad": 3}')
    assert cost(1_000_000, 500_000, (0.15, 0.60)) == Decimal("0.450000")
    assert cost(123, 45, (2.5, 10)) == Decimal("0.000758")


def test_model_references() -> None:
    assert split_ref("offline") == ("offline", "offline")
    assert split_ref("openai:gpt-4o-mini") == ("openai", "gpt-4o-mini")
    assert split_ref("ollama:qwen3:4b") == ("ollama", "qwen3:4b")


def test_the_catalogue_lists_configured_providers_only() -> None:
    plain = ModelRegistry(Settings(), None)
    assert [m.ref for m in plain.models()] == ["offline"]
    assert plain.available("offline")
    assert not plain.available("openai:gpt-4o-mini")
    full = ModelRegistry(
        Settings(
            openai_base_url="https://api.example.com/v1",
            openai_models="gpt-4o-mini",
            ollama_url="http://o:11434",
            ollama_models="llama3.2",
        ),
        None,
    )
    refs = {m.ref: m for m in full.models()}
    assert set(refs) == {"offline", "openai:gpt-4o-mini", "ollama:llama3.2"}
    assert refs["offline"].simulated
    assert refs["offline"].offline
    assert refs["openai:gpt-4o-mini"].price_input == 0.15
    assert refs["ollama:llama3.2"].price_output == 0.0


class Counting:
    name = "fake"

    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, request: ChatRequest) -> ChatResponse:
        self.calls += 1
        return ChatResponse(
            content=f"answer {self.calls}", prompt_tokens=1000, completion_tokens=500
        )

    async def aclose(self) -> None:
        return None


async def test_registry_prices_caches_and_refuses_unknown_models() -> None:
    fake = Counting()
    registry = ModelRegistry(
        Settings(model_prices='{"m1": [1.0, 2.0]}'),
        fakeredis.FakeAsyncRedis(),
        providers={"fake": fake},
    )
    request = ChatRequest(model="", messages=[{"role": "user", "content": "hi"}], temperature=0)
    first = await registry.complete("fake:m1", request, cache_ttl_s=60)
    second = await registry.complete("fake:m1", request, cache_ttl_s=60)
    third = await registry.complete("fake:m1", request)
    assert fake.calls == 2
    assert first.cost_usd == Decimal("0.002000")
    assert not first.cached
    assert second.cached
    assert second.cost_usd == 0
    assert second.response.content == "answer 1"
    assert third.response.content == "answer 2"
    with pytest.raises(ProviderError) as error:
        await registry.complete("openai:gpt-4o", request)
    assert error.value.code == "model_unavailable"


async def test_offline_calls_carry_a_simulated_cost() -> None:
    registry = ModelRegistry(Settings(), None)
    result = await registry.complete(
        "offline",
        ChatRequest(
            model="",
            messages=[
                {"role": "user", "content": "Summarize.\n\nNotes:\nWe agreed to ship the beta."}
            ],
        ),
    )
    assert result.provider == "offline"
    assert result.simulated
    assert result.cost_usd > 0
    await registry.aclose()
