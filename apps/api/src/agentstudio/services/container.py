"""Process-wide infrastructure, built once at startup and shared by every request.

Services are cheap objects created per request around one database session; everything
expensive (connection pools, provider clients, the HTTP client) lives here.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import FastAPI
from redis.asyncio import Redis

from agentstudio.core.config import Settings
from agentstudio.core.crypto import Cipher
from agentstudio.core.ratelimit import RateLimiter
from agentstudio.db.session import Database
from agentstudio.integrations.http import GuardedHttpClient, NetworkPolicy
from agentstudio.integrations.queue import InlineQueue, SqsQueue, build_queue
from agentstudio.integrations.sandbox import create_sandbox_app
from agentstudio.integrations.storage import Storage, build_storage
from agentstudio.integrations.trace import TraceBus
from agentstudio.providers.registry import ModelRegistry


@dataclass
class Container:
    settings: Settings
    db: Database
    redis: Redis
    stream_redis: Redis
    storage: Storage
    queue: InlineQueue | SqsQueue
    models: ModelRegistry
    http: GuardedHttpClient
    sandbox: FastAPI
    trace: TraceBus
    limiter: RateLimiter
    cipher: Cipher

    async def close(self) -> None:
        await self.http.aclose()
        await self.models.aclose()
        await self.stream_redis.aclose()
        await self.redis.aclose()
        await self.db.dispose()


def build_container(settings: Settings, *, application_name: str = "agentstudio") -> Container:
    redis = Redis.from_url(
        settings.redis_url, decode_responses=False, health_check_interval=30, socket_timeout=5
    )
    # Trace readers block on XREAD for up to 15 seconds: they get a client whose socket
    # timeout outlasts the block, so a quiet run is not mistaken for a dead Redis.
    stream_redis = Redis.from_url(
        settings.redis_url, decode_responses=False, health_check_interval=30, socket_timeout=30
    )
    sandbox = create_sandbox_app()
    policy = NetworkPolicy.from_hosts(
        settings.http_allowed_hosts, allow_private=settings.http_allow_private_networks
    )
    return Container(
        settings=settings,
        db=Database(settings, application_name=application_name),
        redis=redis,
        stream_redis=stream_redis,
        storage=build_storage(settings),
        queue=build_queue(settings),
        models=ModelRegistry(settings, redis),
        http=GuardedHttpClient(
            policy, sandbox=sandbox, max_response_bytes=settings.http_max_response_kb * 1024
        ),
        sandbox=sandbox,
        trace=TraceBus(stream_redis),
        limiter=RateLimiter(redis),
        cipher=Cipher(settings.encryption_key.get_secret_value()),
    )
