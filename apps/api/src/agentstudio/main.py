"""The FastAPI application factory.

uvicorn agentstudio.main:create_app --factory --port 8120
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agentstudio import __version__
from agentstudio.api.router import api_router
from agentstudio.core.config import Settings, get_settings
from agentstudio.core.context import BodySizeLimitMiddleware, RequestContextMiddleware
from agentstudio.core.errors import install_exception_handlers
from agentstudio.core.logging import configure_logging, get_logger
from agentstudio.db.migrate import migrate
from agentstudio.integrations.queue import InlineQueue
from agentstudio.integrations.sandbox import create_sandbox_app
from agentstudio.services.container import Container, build_container
from agentstudio.services.runs import RunExecution

log = get_logger("agentstudio.app")
INLINE_REAPER_INTERVAL_S = 30
INLINE_DRAIN_S = 5

DESCRIPTION = """
Build AI agent workflows as graphs, run them from the UI, the API or signed webhooks, watch
every step live, and export any flow as a standalone Python script.

Authenticate with the session cookie set by `POST /api/v1/auth/login`, or with
`Authorization: Bearer <token>` using a session token or a workspace API key (`agst_...`).
Every error uses one envelope: `{"error": {"code", "message", "request_id", "details?"}}`.
"""

TAGS = [
    {"name": "auth", "description": "Sign-in, sign-up, sessions and your profile."},
    {"name": "workspaces", "description": "Workspaces, members, roles and the audit trail."},
    {"name": "dashboard", "description": "Runs, success, latency, tokens and cost."},
    {"name": "flows", "description": "Drafts, validation, versions, import, export, webhooks."},
    {"name": "runs", "description": "Start runs, stream their traces, cancel and re-run."},
    {"name": "approvals", "description": "Human approval decisions for paused runs."},
    {"name": "knowledge", "description": "Knowledge bases searched by flows."},
    {"name": "secrets", "description": "Write-only credentials referenced as {{secrets.NAME}}."},
    {"name": "api keys", "description": "Workspace-scoped keys for programmatic access."},
    {"name": "catalog", "description": "The template gallery and the configured models."},
    {"name": "offline model", "description": "The built-in model over the OpenAI chat format."},
    {"name": "webhooks", "description": "Signed inbound webhooks that start runs."},
    {"name": "system", "description": "Deployment capabilities and limits."},
]


async def _inline_reaper(container: Container) -> None:
    """With the inline queue there is no worker, so the API expires approvals itself."""
    execution = RunExecution(container)
    while True:
        await asyncio.sleep(INLINE_REAPER_INTERVAL_S)
        try:
            await execution.reap()
        except Exception:
            log.exception("reaper_failed")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_format)
    if settings.is_production and (problems := settings.production_problems()):
        raise RuntimeError("Refusing to start in production:\n  - " + "\n  - ".join(problems))

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if settings.migrate_on_boot:
            await migrate(settings)
        container = build_container(settings)
        reaper: asyncio.Task[None] | None = None
        if isinstance(container.queue, InlineQueue):
            container.queue.bind(RunExecution(container).execute)
            reaper = asyncio.create_task(_inline_reaper(container))
        app.state.container = container
        log.info(
            "started",
            version=__version__,
            env=settings.app_env,
            queue=settings.queue_backend,
            storage=settings.storage_backend,
            models=[model.ref for model in container.models.models()],
        )
        try:
            yield
        finally:
            if reaper is not None:
                reaper.cancel()
            if isinstance(container.queue, InlineQueue):
                # Give in-flight runs a moment; anything left is released to resume later.
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(container.queue.drain(), INLINE_DRAIN_S)
                await container.queue.cancel_all()
            await container.close()

    app = FastAPI(
        title=settings.product_name,
        version=__version__,
        description=DESCRIPTION,
        openapi_tags=TAGS,
        docs_url="/docs",
        redoc_url=None,
        lifespan=lifespan,
        license_info={"name": "MIT", "identifier": "MIT"},
    )
    install_exception_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["authorization", "content-type", "x-request-id", "last-event-id"],
        expose_headers=[
            "x-request-id",
            "x-ratelimit-limit",
            "x-ratelimit-remaining",
            "x-ratelimit-reset",
            "content-disposition",
        ],
        max_age=600,
    )
    # Twenty documents per upload at the per-document limit, plus multipart overhead.
    app.add_middleware(
        BodySizeLimitMiddleware, max_bytes=settings.max_document_bytes * 20 + 1024 * 1024
    )
    app.add_middleware(RequestContextMiddleware, hsts=settings.is_production)
    app.include_router(api_router)
    # Fixture endpoints for exported scripts; flows reach the same app in process.
    app.mount("/sandbox", create_sandbox_app())
    return app
