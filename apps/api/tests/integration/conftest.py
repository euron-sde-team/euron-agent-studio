"""Integration fixtures: the real app against real Postgres, Redis and the Floci emulator.

Start the dependencies with `scripts/test-deps.sh` (or `make test-integration`). Each
session gets a fresh database schema, its own Redis database, and its own S3 bucket and SQS
queues on Floci, so runs never see each other's state.
"""

from __future__ import annotations

import asyncio
import os
import secrets
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import boto3
import httpx
import pytest
from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from agentstudio.core.config import Settings
from agentstudio.db.migrate import migrate
from agentstudio.main import create_app


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "tests/integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)


DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://agentstudio:agentstudio@127.0.0.1:9121/agentstudio_test",
)
REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://127.0.0.1:9122/0")
AWS_ENDPOINT_URL = os.environ.get("TEST_AWS_ENDPOINT_URL", "http://127.0.0.1:9123")
PASSWORD = "integration-password-2026"
WEB = "http://web.test"


def aws(service: str) -> Any:
    return boto3.client(
        service,
        endpoint_url=AWS_ENDPOINT_URL,
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )


@dataclass(frozen=True, slots=True)
class Infra:
    bucket: str
    queue_url: str
    dead_letter_url: str


@pytest.fixture(scope="session")
def infra() -> Infra:
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
    suffix = secrets.token_hex(4)
    try:
        s3 = aws("s3")
        bucket = f"agentstudio-test-{suffix}"
        s3.create_bucket(Bucket=bucket)
        sqs = aws("sqs")
        dead = sqs.create_queue(QueueName=f"agentstudio-runs-dlq-{suffix}")["QueueUrl"]
        dead_arn = sqs.get_queue_attributes(QueueUrl=dead, AttributeNames=["QueueArn"])[
            "Attributes"
        ]["QueueArn"]
        queue = sqs.create_queue(
            QueueName=f"agentstudio-runs-{suffix}",
            Attributes={
                "RedrivePolicy": f'{{"deadLetterTargetArn":"{dead_arn}","maxReceiveCount":"3"}}'
            },
        )["QueueUrl"]
    except Exception as exc:  # pragma: no cover - a missing emulator is a setup problem
        pytest.exit(
            f"Floci is not reachable at {AWS_ENDPOINT_URL}: run scripts/test-deps.sh ({exc})", 2
        )
    return Infra(bucket, queue, dead)


def make_settings(infra: Infra, tmp: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "app_env": "test",
        "database_url": DATABASE_URL,
        "redis_url": REDIS_URL,
        "queue_backend": "inline",
        "storage_backend": "s3",
        "s3_bucket": infra.bucket,
        "sqs_queue_url": infra.queue_url,
        "aws_endpoint_url": AWS_ENDPOINT_URL,
        "storage_dir": tmp,
        "cors_origins": [WEB],
        "web_url": WEB,
        "public_api_url": "http://api.test",
        "log_level": "warning",
        "log_format": "console",
        "rate_limit_login": 1000,
        "rate_limit_runs": 1000,
        "max_active_runs_per_workspace": 50,
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture(scope="session")
async def database() -> None:
    engine = create_async_engine(DATABASE_URL)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
    except OSError as exc:  # pragma: no cover
        pytest.exit(f"Postgres is not reachable: run scripts/test-deps.sh ({exc})", 2)
    finally:
        await engine.dispose()
    redis = Redis.from_url(REDIS_URL)
    await redis.flushdb()
    await redis.aclose()


@pytest.fixture(scope="session")
def settings(infra: Infra, tmp_path_factory: pytest.TempPathFactory) -> Settings:
    return make_settings(infra, tmp_path_factory.mktemp("files"))


@pytest.fixture(scope="session")
async def app(settings: Settings, database: None) -> AsyncIterator[FastAPI]:
    await migrate(settings)
    application = create_app(settings)
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture(scope="session")
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as http:
        yield http


@dataclass(slots=True)
class Actor:
    email: str
    name: str
    token: str
    password: str = ""

    @property
    def headers(self) -> dict[str, str]:
        return {"authorization": f"Bearer {self.token}"}


async def login(client: httpx.AsyncClient, email: str, password: str) -> Actor:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    # Tests authenticate with bearer tokens; a stored cookie would authenticate the rest too.
    client.cookies.clear()
    body = response.json()
    return Actor(email, body["user"]["name"], body["token"], password)


@pytest.fixture(scope="session")
async def admin(client: httpx.AsyncClient) -> Actor:
    """The first account: it becomes the instance administrator."""
    response = await client.post(
        "/api/v1/auth/signup",
        json={"email": "ava.admin@northwind.example", "name": "Ava Admin", "password": PASSWORD},
    )
    assert response.status_code == 201, response.text
    client.cookies.clear()
    return Actor("ava.admin@northwind.example", "Ava Admin", response.json()["token"], PASSWORD)


async def new_workspace(
    client: httpx.AsyncClient, owner: Actor, name: str | None = None
) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/workspaces",
        json={"name": name or f"Team {uuid.uuid4().hex[:8]}"},
        headers=owner.headers,
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


async def add_member(
    client: httpx.AsyncClient, owner: Actor, workspace: dict[str, Any], role: str
) -> Actor:
    email = f"{role}.{uuid.uuid4().hex[:8]}@northwind.example"
    response = await client.post(
        f"/api/v1/workspaces/{workspace['slug']}/members",
        json={"email": email, "name": f"{role.title()} Person", "role": role},
        headers=owner.headers,
    )
    assert response.status_code == 201, response.text
    password = response.json()["temporary_password"]
    return await login(client, email, password)


@pytest.fixture
async def workspace(client: httpx.AsyncClient, admin: Actor) -> dict[str, Any]:
    return await new_workspace(client, admin)


def base(workspace: dict[str, Any]) -> str:
    return f"/api/v1/workspaces/{workspace['slug']}"


async def create_flow(
    client: httpx.AsyncClient, actor: Actor, workspace: dict[str, Any], **body: Any
) -> dict[str, Any]:
    payload = {"name": body.pop("name", "A flow"), **body}
    response = await client.post(f"{base(workspace)}/flows", json=payload, headers=actor.headers)
    assert response.status_code == 201, response.text
    return dict(response.json())


async def wait_for_run(
    client: httpx.AsyncClient,
    actor: Actor,
    workspace: dict[str, Any],
    run_id: str,
    statuses: tuple[str, ...] = ("succeeded", "failed", "cancelled", "waiting"),
    within: float = 30,
) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + within
    while True:
        response = await client.get(f"{base(workspace)}/runs/{run_id}", headers=actor.headers)
        detail = dict(response.json())
        if detail["status"] in statuses:
            return detail
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"run {run_id} stayed {detail['status']}")
        await asyncio.sleep(0.1)


async def api_key(
    client: httpx.AsyncClient, owner: Actor, workspace: dict[str, Any], role: str = "editor"
) -> Actor:
    response = await client.post(
        f"{base(workspace)}/api-keys",
        json={"name": f"{role} key", "role": role},
        headers=owner.headers,
    )
    assert response.status_code == 201, response.text
    return Actor(f"{role}-key", f"{role} key", response.json()["key"])
