"""Runs: start, watch live, inspect, cancel and re-run."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, status
from fastapi.responses import StreamingResponse

from agentstudio.api import presenters
from agentstudio.api.deps import ContainerDep, EditorDep, SessionDep, ViewerDep, rate_limit
from agentstudio.models.enums import RunTrigger
from agentstudio.schemas.common import Limit, Offset, Page
from agentstudio.schemas.runs import RunCreate, RunDetail, RunOut
from agentstudio.services.events import RunEvents
from agentstudio.services.runs import RunService

router = APIRouter(prefix="/api/v1/workspaces/{workspace}", tags=["runs"])

RunStatusFilter = Literal["queued", "running", "waiting", "succeeded", "failed", "cancelled"]
TriggerFilter = Literal["manual", "api", "webhook", "rerun"]


@router.post(
    "/flows/{flow_id}/runs",
    summary="Start a run",
    description=(
        "Queues a run and returns it at once. Pass `wait` (seconds) to wait for it to finish or "
        "pause first; the response is the run as it is when the wait ends."
    ),
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(rate_limit("runs", "rate_limit_runs"))],
)
async def start_run(
    flow_id: uuid.UUID,
    body: RunCreate,
    ctx: EditorDep,
    container: ContainerDep,
    session: SessionDep,
    wait: Annotated[float, Query(ge=0, le=120, description="Seconds to wait for the result.")] = 0,
) -> RunOut:
    service = RunService(container, session)
    trigger = RunTrigger.MANUAL if ctx.principal.user is not None else RunTrigger.API
    run = await service.start(
        ctx.workspace, ctx.principal, flow_id, body.inputs, body.version, trigger=trigger
    )
    if wait:
        await service.wait(ctx.id, run, min(wait, container.settings.max_run_wait_s))
    return presenters.run_out(await service.view(ctx.id, run.id))


@router.get("/runs", summary="Run history, newest first")
async def list_runs(
    ctx: ViewerDep,
    container: ContainerDep,
    session: SessionDep,
    limit: Limit = 50,
    offset: Offset = 0,
    flow_id: uuid.UUID | None = None,
    status: RunStatusFilter | None = None,
    trigger: TriggerFilter | None = None,
) -> Page[RunOut]:
    views, total = await RunService(container, session).page(
        ctx.id, limit=limit, offset=offset, flow_id=flow_id, status=status, trigger=trigger
    )
    return Page(
        items=[presenters.run_out(v) for v in views], total=total, limit=limit, offset=offset
    )


@router.get("/runs/{run_id}", summary="A run with every step, its graph and its approvals")
async def get_run(
    run_id: uuid.UUID, ctx: ViewerDep, container: ContainerDep, session: SessionDep
) -> RunDetail:
    return presenters.run_detail(await RunService(container, session).detail(ctx.id, run_id))


@router.get(
    "/runs/{run_id}/events",
    summary="Live trace as server-sent events",
    description=(
        "Events: run.queued, run.started, step.started, step.progress, step.finished, "
        "step.waiting, approval.decided, run.waiting, run.finished. Reconnect with "
        "Last-Event-ID to resume exactly where the stream stopped."
    ),
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def run_events(
    run_id: uuid.UUID,
    ctx: ViewerDep,
    container: ContainerDep,
    session: SessionDep,
    last_event_id: Annotated[str | None, Header(max_length=64)] = None,
) -> StreamingResponse:
    run = await RunService(container, session).get(ctx.id, run_id)
    return StreamingResponse(
        RunEvents(container).stream(run, last_event_id),
        media_type="text/event-stream",
        headers={"cache-control": "no-cache", "x-accel-buffering": "no"},
    )


@router.post("/runs/{run_id}/cancel", summary="Cancel a queued, running or waiting run")
async def cancel_run(
    run_id: uuid.UUID, ctx: EditorDep, container: ContainerDep, session: SessionDep
) -> RunOut:
    service = RunService(container, session)
    await service.cancel(ctx.workspace, ctx.principal, run_id)
    return presenters.run_out(await service.view(ctx.id, run_id))


@router.post(
    "/runs/{run_id}/rerun",
    summary="Run again with the same inputs and version",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(rate_limit("runs", "rate_limit_runs"))],
)
async def rerun(
    run_id: uuid.UUID, ctx: EditorDep, container: ContainerDep, session: SessionDep
) -> RunOut:
    service = RunService(container, session)
    run = await service.rerun(ctx.workspace, ctx.principal, run_id)
    return presenters.run_out(await service.view(ctx.id, run.id))
