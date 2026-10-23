"""Probes, metrics and public deployment info."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from agentstudio import __version__
from agentstudio.api.deps import ContainerDep, SessionDep
from agentstudio.core.logging import get_logger
from agentstudio.integrations.http import SANDBOX_HOST
from agentstudio.repositories.users import UserRepository
from agentstudio.schemas.catalog import LimitsOut, SystemInfo

router = APIRouter()
log = get_logger("agentstudio.health")


@router.get("/livez", include_in_schema=False)
async def livez() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", include_in_schema=False)
async def readyz(container: ContainerDep) -> JSONResponse:
    checks: dict[str, Any] = {}
    for name, probe in (
        ("database", container.db.ping),
        ("redis", container.redis.ping),
        ("storage", container.storage.check),
        ("queue", container.queue.check),
    ):
        try:
            await probe()
            checks[name] = "ok"
        except Exception as exc:
            log.warning("readiness_check_failed", check=name, error=type(exc).__name__)
            checks[name] = "failing"
    ready = all(value == "ok" for value in checks.values())
    return JSONResponse(
        {"status": "ready" if ready else "degraded", "checks": checks},
        status_code=200 if ready else 503,
    )


@router.get("/metrics", include_in_schema=False)
async def prometheus_metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.get("/api/v1/system/info", tags=["system"], summary="Deployment capabilities and limits")
async def system_info(container: ContainerDep, session: SessionDep) -> SystemInfo:
    settings = container.settings
    providers = sorted({model.provider for model in container.models.models()})
    return SystemInfo(
        product_name=settings.product_name,
        version=__version__,
        default_model=settings.default_model,
        providers=providers,
        offline_only=providers == ["offline"],
        allow_signup=settings.allow_signup,
        needs_setup=await UserRepository(session).user_count() == 0,
        queue_backend=settings.queue_backend,
        public_api_url=settings.public_api_url,
        sandbox_url=f"https://{SANDBOX_HOST}",
        limits=LimitsOut(
            max_nodes=settings.max_nodes,
            max_edges=settings.max_edges,
            max_loop_items=settings.max_loop_items,
            max_agent_iterations=settings.max_agent_iterations,
            run_timeout_s=settings.run_timeout_s,
            max_document_kb=settings.max_document_kb,
            max_run_wait_s=settings.max_run_wait_s,
        ),
    )
