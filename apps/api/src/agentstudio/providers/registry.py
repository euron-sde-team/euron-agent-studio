"""The model registry: resolves model references, caches, prices and measures every call.

A node names its model with a reference: `offline`, `openai:<model>` or `ollama:<model>`.
The registry maps the reference to a configured provider (refusing ones this deployment does
not have), serves repeated deterministic calls from the Redis cache when the node asks for
it, computes the cost from token usage, and records metrics. It implements the engine's
`ModelGateway` port.
"""

from __future__ import annotations

import dataclasses
import hashlib
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import orjson
from redis.asyncio import Redis

from agentstudio.core import metrics
from agentstudio.core.config import Settings
from agentstudio.core.logging import get_logger
from agentstudio.engine.ports import ModelResult
from agentstudio.providers.base import (
    ChatProvider,
    ChatRequest,
    ChatResponse,
    ProviderError,
    ToolCall,
)
from agentstudio.providers.offline import OFFLINE_MODEL, OfflineProvider
from agentstudio.providers.ollama import OllamaProvider
from agentstudio.providers.openai_compat import OpenAICompatibleProvider
from agentstudio.providers.pricing import DEFAULT_PRICES, cost, parse_prices

log = get_logger("agentstudio.models")
_CACHE_PREFIX = "llm:"


@dataclass(frozen=True, slots=True)
class ModelInfo:
    ref: str
    provider: str
    model: str
    label: str
    offline: bool
    price_input: float
    price_output: float
    simulated: bool


def split_ref(ref: str) -> tuple[str, str]:
    """`openai:gpt-4o-mini` becomes ("openai", "gpt-4o-mini"); `offline` stays offline."""
    provider, _, model = ref.strip().partition(":")
    if provider == OFFLINE_MODEL:
        return OFFLINE_MODEL, OFFLINE_MODEL
    return provider, model


class ModelRegistry:
    def __init__(
        self,
        settings: Settings,
        redis: Redis | None,
        *,
        providers: dict[str, ChatProvider] | None = None,
    ) -> None:
        self._redis = redis
        self._prices = {**DEFAULT_PRICES, **parse_prices(settings.model_prices)}
        self._offline_price = (settings.offline_price_input, settings.offline_price_output)
        self._models: dict[str, list[str]] = {OFFLINE_MODEL: [OFFLINE_MODEL]}
        self._providers: dict[str, ChatProvider] = {
            OFFLINE_MODEL: OfflineProvider(
                delay_ms_per_100_tokens=settings.offline_delay_ms_per_100_tokens
            )
        }
        if settings.openai_base_url:
            key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else None
            self._providers["openai"] = OpenAICompatibleProvider(
                settings.openai_base_url, key, timeout_s=settings.llm_timeout_s
            )
            self._models["openai"] = list(settings.openai_models)
        if settings.ollama_url:
            self._providers["ollama"] = OllamaProvider(
                settings.ollama_url, timeout_s=settings.llm_timeout_s
            )
            self._models["ollama"] = list(settings.ollama_models)
        for name, provider in (providers or {}).items():
            self._providers[name] = provider
            self._models.setdefault(name, [])

    # ----------------------------------------------------------------------------------
    # Catalogue
    # ----------------------------------------------------------------------------------

    def available(self, ref: str) -> bool:
        provider, model = split_ref(ref)
        return provider in self._providers and bool(model)

    def _price(self, provider: str, model: str) -> tuple[tuple[float, float], bool]:
        if provider == OFFLINE_MODEL:
            return self._offline_price, True
        if provider == "ollama":
            return (0.0, 0.0), False
        return self._prices.get(model, (0.0, 0.0)), False

    def models(self) -> list[ModelInfo]:
        found: list[ModelInfo] = []
        for provider, names in self._models.items():
            for model in names:
                (price_in, price_out), simulated = self._price(provider, model)
                ref = OFFLINE_MODEL if provider == OFFLINE_MODEL else f"{provider}:{model}"
                label = "Offline (built in, deterministic)" if provider == OFFLINE_MODEL else model
                found.append(
                    ModelInfo(
                        ref=ref,
                        provider=provider,
                        model=model,
                        label=label,
                        offline=provider == OFFLINE_MODEL,
                        price_input=price_in,
                        price_output=price_out,
                        simulated=simulated,
                    )
                )
        return found

    # ----------------------------------------------------------------------------------
    # Calls
    # ----------------------------------------------------------------------------------

    def _resolve(self, ref: str) -> tuple[str, str, ChatProvider]:
        provider_name, model = split_ref(ref)
        provider = self._providers.get(provider_name)
        if provider is None or not model:
            raise ProviderError(
                f"The model {ref!r} is not configured on this deployment.",
                code="model_unavailable",
            )
        return provider_name, model, provider

    @staticmethod
    def cache_key(provider: str, request: ChatRequest) -> str:
        material = orjson.dumps(
            {
                "provider": provider,
                "model": request.model,
                "messages": request.messages,
                "tools": request.tools,
                "response_format": request.response_format,
                "temperature": request.temperature,
                "max_tokens": request.max_tokens,
            },
            option=orjson.OPT_SORT_KEYS,
        )
        return _CACHE_PREFIX + hashlib.sha256(material).hexdigest()

    async def _cached(self, key: str) -> ChatResponse | None:
        if self._redis is None:
            return None
        try:
            raw = await self._redis.get(key)
        except Exception:
            log.warning("model_cache_unavailable", exc_info=True)
            return None
        if raw is None:
            return None
        data: dict[str, Any] = orjson.loads(raw)
        data["tool_calls"] = [ToolCall(**call) for call in data.get("tool_calls", [])]
        return ChatResponse(**data)

    async def _store(self, key: str, response: ChatResponse, ttl_s: int) -> None:
        if self._redis is None:
            return
        try:
            await self._redis.set(key, orjson.dumps(dataclasses.asdict(response)), ex=ttl_s)
        except Exception:
            log.warning("model_cache_unavailable", exc_info=True)

    async def complete(
        self, model_ref: str, request: ChatRequest, *, cache_ttl_s: int = 0
    ) -> ModelResult:
        provider_name, model, provider = self._resolve(model_ref)
        resolved = dataclasses.replace(request, model=model)
        key = self.cache_key(provider_name, resolved) if cache_ttl_s > 0 else None
        if key is not None and (hit := await self._cached(key)) is not None:
            metrics.MODEL_CALLS.labels(provider_name, "cached").inc()
            return ModelResult(
                response=hit,
                provider=provider_name,
                model=model,
                prompt_tokens=hit.prompt_tokens,
                completion_tokens=hit.completion_tokens,
                cost_usd=Decimal(0),
                simulated=False,
                cached=True,
                latency_ms=0,
            )
        started = time.perf_counter()
        try:
            response = await provider.complete(resolved)
        except ProviderError:
            metrics.MODEL_CALLS.labels(provider_name, "error").inc()
            raise
        elapsed = time.perf_counter() - started
        price, simulated = self._price(provider_name, model)
        spent = cost(response.prompt_tokens, response.completion_tokens, price)
        metrics.MODEL_CALLS.labels(provider_name, "ok").inc()
        metrics.MODEL_LATENCY.labels(provider_name).observe(elapsed)
        metrics.TOKENS.labels(provider_name, "prompt").inc(response.prompt_tokens)
        metrics.TOKENS.labels(provider_name, "completion").inc(response.completion_tokens)
        metrics.COST.labels(provider_name).inc(float(spent))
        if key is not None:
            await self._store(key, response, cache_ttl_s)
        return ModelResult(
            response=response,
            provider=provider_name,
            model=model,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            cost_usd=spent,
            simulated=simulated,
            cached=False,
            latency_ms=int(elapsed * 1000),
        )

    async def aclose(self) -> None:
        for provider in self._providers.values():
            await provider.aclose()
