"""Flows: the editor's draft, validation, versions, import and export, webhooks."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Query, status
from fastapi.responses import PlainTextResponse

from agentstudio.api import presenters
from agentstudio.api.deps import ContainerDep, EditorDep, SessionDep, ViewerDep
from agentstudio.schemas.common import Limit, Offset, Page
from agentstudio.schemas.flows import (
    DraftSave,
    DraftSaved,
    FlowCreate,
    FlowDocument,
    FlowOut,
    FlowSummaryOut,
    FlowUpdate,
    PublishRequest,
    ValidateRequest,
    ValidationOut,
    VersionDetail,
    VersionOut,
    WebhookOut,
)
from agentstudio.services.flows import FlowService

router = APIRouter(prefix="/api/v1/workspaces/{workspace}/flows", tags=["flows"])

VersionQuery = Annotated[
    Literal["draft", "published"] | int,
    Query(description="draft, published, or a version number."),
]


async def _full(service: FlowService, workspace_id: uuid.UUID, flow_id: uuid.UUID) -> FlowOut:
    flow = await service.get(workspace_id, flow_id)
    issues = await service.issues(workspace_id, service.parse_graph(flow.graph))
    return presenters.flow_out(await service.summary(flow), issues, service.webhook_url(flow))


@router.get("", summary="Flows in this workspace, most recently changed first")
async def list_flows(
    ctx: ViewerDep,
    container: ContainerDep,
    session: SessionDep,
    limit: Limit = 50,
    offset: Offset = 0,
    q: Annotated[
        str | None, Query(max_length=120, description="Search names and descriptions.")
    ] = None,
    tag: Annotated[str | None, Query(max_length=32)] = None,
    published: Annotated[
        bool | None, Query(description="Only published (or unpublished) flows.")
    ] = None,
) -> Page[FlowSummaryOut]:
    summaries, total = await FlowService(container, session).page(
        ctx.id, limit=limit, offset=offset, search=q, tag=tag, published=published
    )
    return Page(
        items=[presenters.flow_summary(s) for s in summaries],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/tags", summary="Every tag used in this workspace")
async def list_tags(ctx: ViewerDep, container: ContainerDep, session: SessionDep) -> list[str]:
    return await FlowService(container, session).tags(ctx.id)


@router.post(
    "", summary="Create a flow, blank or from a template", status_code=status.HTTP_201_CREATED
)
async def create_flow(
    body: FlowCreate, ctx: EditorDep, container: ContainerDep, session: SessionDep
) -> FlowOut:
    service = FlowService(container, session)
    flow = await service.create(ctx.workspace, ctx.principal, body)
    return await _full(service, ctx.id, flow.id)


@router.post("/import", summary="Import a flow from an exported JSON document", status_code=201)
async def import_flow(
    body: FlowDocument, ctx: EditorDep, container: ContainerDep, session: SessionDep
) -> FlowOut:
    service = FlowService(container, session)
    flow = await service.import_document(ctx.workspace, ctx.principal, body)
    return await _full(service, ctx.id, flow.id)


@router.get("/{flow_id}", summary="A flow with its draft graph and validation issues")
async def get_flow(
    flow_id: uuid.UUID, ctx: ViewerDep, container: ContainerDep, session: SessionDep
) -> FlowOut:
    return await _full(FlowService(container, session), ctx.id, flow_id)


@router.patch("/{flow_id}", summary="Rename, describe or tag a flow")
async def update_flow(
    flow_id: uuid.UUID,
    body: FlowUpdate,
    ctx: EditorDep,
    container: ContainerDep,
    session: SessionDep,
) -> FlowOut:
    service = FlowService(container, session)
    await service.update(ctx.workspace, ctx.principal, flow_id, body)
    return await _full(service, ctx.id, flow_id)


@router.delete("/{flow_id}", summary="Delete a flow with its versions and runs", status_code=204)
async def delete_flow(
    flow_id: uuid.UUID, ctx: EditorDep, container: ContainerDep, session: SessionDep
) -> None:
    await FlowService(container, session).delete(ctx.workspace, ctx.principal, flow_id)


@router.put(
    "/{flow_id}/draft",
    summary="Save the draft graph",
    description="Send the revision the edit was based on; a stale revision is refused with 409.",
)
async def save_draft(
    flow_id: uuid.UUID,
    body: DraftSave,
    ctx: EditorDep,
    container: ContainerDep,
    session: SessionDep,
) -> DraftSaved:
    flow, issues = await FlowService(container, session).save_draft(
        ctx.workspace, ctx.principal, flow_id, body.graph, body.base_revision
    )
    return DraftSaved(
        draft_revision=flow.draft_revision,
        draft_updated_at=flow.draft_updated_at,
        issues=presenters.issues_out(issues),
    )


@router.post("/{flow_id}/validate", summary="Validate a graph without saving it")
async def validate_flow(
    flow_id: uuid.UUID,
    body: ValidateRequest,
    ctx: ViewerDep,
    container: ContainerDep,
    session: SessionDep,
) -> ValidationOut:
    service = FlowService(container, session)
    await service.get(ctx.id, flow_id)
    issues = await service.issues(ctx.id, service.parse_graph(body.graph))
    return ValidationOut(
        valid=not any(i.severity == "error" for i in issues), issues=presenters.issues_out(issues)
    )


@router.post("/{flow_id}/duplicate", summary="Copy a flow's draft into a new flow", status_code=201)
async def duplicate_flow(
    flow_id: uuid.UUID, ctx: EditorDep, container: ContainerDep, session: SessionDep
) -> FlowOut:
    service = FlowService(container, session)
    copy = await service.duplicate(ctx.workspace, ctx.principal, flow_id)
    return await _full(service, ctx.id, copy.id)


@router.post("/{flow_id}/publish", summary="Publish the draft as a new version", status_code=201)
async def publish_flow(
    flow_id: uuid.UUID,
    body: PublishRequest,
    ctx: EditorDep,
    container: ContainerDep,
    session: SessionDep,
) -> VersionOut:
    service = FlowService(container, session)
    version = await service.publish(ctx.workspace, ctx.principal, flow_id, body.notes)
    flow = await service.get(ctx.id, flow_id)
    return presenters.version_out(
        version, ctx.principal.user.name if ctx.principal.user else None, flow
    )


@router.get("/{flow_id}/versions", summary="Published versions, newest first")
async def list_versions(
    flow_id: uuid.UUID,
    ctx: ViewerDep,
    container: ContainerDep,
    session: SessionDep,
    limit: Limit = 50,
    offset: Offset = 0,
) -> Page[VersionOut]:
    flow, rows, total = await FlowService(container, session).versions(
        ctx.id, flow_id, limit=limit, offset=offset
    )
    return Page(
        items=[presenters.version_out(v, name, flow) for v, name in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{flow_id}/versions/{number}", summary="One version with its graph")
async def get_version(
    flow_id: uuid.UUID, number: int, ctx: ViewerDep, container: ContainerDep, session: SessionDep
) -> VersionDetail:
    flow, version, name = await FlowService(container, session).version(ctx.id, flow_id, number)
    return VersionDetail(
        **presenters.version_out(version, name, flow).model_dump(), graph=version.graph
    )


@router.post("/{flow_id}/versions/{number}/restore", summary="Copy a version into the draft")
async def restore_version(
    flow_id: uuid.UUID, number: int, ctx: EditorDep, container: ContainerDep, session: SessionDep
) -> FlowOut:
    service = FlowService(container, session)
    await service.restore(ctx.workspace, ctx.principal, flow_id, number)
    return await _full(service, ctx.id, flow_id)


@router.get("/{flow_id}/export", summary="Export as a portable JSON document")
async def export_json(
    flow_id: uuid.UUID,
    ctx: ViewerDep,
    container: ContainerDep,
    session: SessionDep,
    version: VersionQuery = "draft",
) -> FlowDocument:
    return await FlowService(container, session).export_document(ctx.id, flow_id, version)


@router.get(
    "/{flow_id}/export/python",
    summary="Export as a standalone Python script",
    response_class=PlainTextResponse,
    responses={200: {"content": {"text/x-python": {}}}},
)
async def export_python(
    flow_id: uuid.UUID,
    ctx: ViewerDep,
    container: ContainerDep,
    session: SessionDep,
    version: VersionQuery = "draft",
) -> PlainTextResponse:
    filename, source = await FlowService(container, session).export_python(
        ctx.workspace, flow_id, version
    )
    return PlainTextResponse(
        source,
        media_type="text/x-python; charset=utf-8",
        headers={"content-disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{flow_id}/webhook", summary="The flow's webhook (the secret is never shown again)")
async def get_webhook(
    flow_id: uuid.UUID, ctx: EditorDep, container: ContainerDep, session: SessionDep
) -> WebhookOut:
    service = FlowService(container, session)
    flow = await service.get(ctx.id, flow_id)
    return presenters.webhook_out(flow, service.webhook_url(flow))


@router.put("/{flow_id}/webhook", summary="Enable the webhook or rotate its secret (shown once)")
async def enable_webhook(
    flow_id: uuid.UUID, ctx: EditorDep, container: ContainerDep, session: SessionDep
) -> WebhookOut:
    service = FlowService(container, session)
    flow, secret = await service.enable_webhook(ctx.workspace, ctx.principal, flow_id)
    return presenters.webhook_out(flow, service.webhook_url(flow), secret)


@router.delete("/{flow_id}/webhook", summary="Disable the webhook and discard its secret")
async def disable_webhook(
    flow_id: uuid.UUID, ctx: EditorDep, container: ContainerDep, session: SessionDep
) -> WebhookOut:
    service = FlowService(container, session)
    flow = await service.disable_webhook(ctx.workspace, ctx.principal, flow_id)
    return presenters.webhook_out(flow, service.webhook_url(flow))
