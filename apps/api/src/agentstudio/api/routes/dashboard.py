"""The workspace dashboard."""

from __future__ import annotations

from fastapi import APIRouter

from agentstudio.api import presenters
from agentstudio.api.deps import ContainerDep, SessionDep, ViewerDep
from agentstudio.schemas.dashboard import DashboardOut
from agentstudio.services.dashboard import DashboardService

router = APIRouter(prefix="/api/v1/workspaces/{workspace}", tags=["dashboard"])


@router.get("/dashboard", summary="Runs, success, latency, tokens and cost over two weeks")
async def dashboard(ctx: ViewerDep, container: ContainerDep, session: SessionDep) -> DashboardOut:
    service = DashboardService(container, session)
    stats = await service.stats(ctx.id)
    recent = await service.recent(ctx.id)
    return DashboardOut(**stats.model_dump(), recent_runs=[presenters.run_out(v) for v in recent])
