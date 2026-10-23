"""Human approvals: the inbox and decisions."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter

from agentstudio.api import presenters
from agentstudio.api.deps import ContainerDep, EditorDep, SessionDep, UserDep, ViewerDep
from agentstudio.schemas.approvals import ApprovalOut, DecisionIn
from agentstudio.schemas.common import Limit, Offset, Page
from agentstudio.services.approvals import ApprovalService

router = APIRouter(prefix="/api/v1/workspaces/{workspace}/approvals", tags=["approvals"])


@router.get("", summary="Approvals, newest first (filter by status for the inbox)")
async def list_approvals(
    ctx: ViewerDep,
    container: ContainerDep,
    session: SessionDep,
    limit: Limit = 50,
    offset: Offset = 0,
    status: Literal["pending", "approved", "rejected", "expired", "cancelled"] | None = None,
) -> Page[ApprovalOut]:
    views, total = await ApprovalService(container, session).page(
        ctx.id, status=status, limit=limit, offset=offset
    )
    return Page(
        items=[presenters.approval_out(v) for v in views], total=total, limit=limit, offset=offset
    )


@router.get("/{approval_id}", summary="One approval")
async def get_approval(
    approval_id: uuid.UUID, ctx: ViewerDep, container: ContainerDep, session: SessionDep
) -> ApprovalOut:
    return presenters.approval_out(
        await ApprovalService(container, session).view(ctx.id, approval_id)
    )


@router.post(
    "/{approval_id}/decision",
    summary="Approve or reject; the paused run continues on that branch",
)
async def decide(
    approval_id: uuid.UUID,
    body: DecisionIn,
    ctx: EditorDep,
    user: UserDep,
    container: ContainerDep,
    session: SessionDep,
) -> ApprovalOut:
    view = await ApprovalService(container, session).decide(
        ctx.workspace,
        ctx.principal,
        user,
        approval_id,
        approve=body.decision == "approve",
        comment=body.comment,
    )
    return presenters.approval_out(view)
