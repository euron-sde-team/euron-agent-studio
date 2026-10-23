"""Workspaces, members and the audit trail."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from agentstudio.api.deps import (
    ContainerDep,
    OwnerDep,
    PrincipalDep,
    SessionDep,
    UserDep,
    ViewerDep,
)
from agentstudio.core.errors import ForbiddenError
from agentstudio.models import Membership, User, Workspace
from agentstudio.models.enums import Role
from agentstudio.schemas.audit import AuditEventOut
from agentstudio.schemas.auth import WorkspaceSummaryOut
from agentstudio.schemas.common import Limit, Offset, Page
from agentstudio.schemas.workspaces import (
    MemberAdd,
    MemberAdded,
    MemberOut,
    MemberUpdate,
    WorkspaceCreate,
    WorkspaceOut,
    WorkspaceSettings,
    WorkspaceUpdate,
)
from agentstudio.services import audit
from agentstudio.services.workspaces import WorkspaceService

router = APIRouter(prefix="/api/v1/workspaces", tags=["workspaces"])


def _out(workspace: Workspace, role: str) -> WorkspaceOut:
    return WorkspaceOut(
        id=workspace.id,
        slug=workspace.slug,
        name=workspace.name,
        description=workspace.description,
        settings=WorkspaceSettings.model_validate(workspace.settings),
        role=role,
        created_at=workspace.created_at,
    )


def _member(membership: Membership, user: User) -> MemberOut:
    return MemberOut(
        user_id=user.id,
        email=user.email,
        name=user.name,
        role=membership.role,
        joined_at=membership.created_at,
    )


@router.get("", summary="Workspaces you belong to")
async def list_workspaces(
    user: UserDep, container: ContainerDep, session: SessionDep
) -> list[WorkspaceSummaryOut]:
    summaries = await WorkspaceService(container, session).list_for(user)
    return [
        WorkspaceSummaryOut(
            id=s.workspace.id,
            slug=s.workspace.slug,
            name=s.workspace.name,
            role=s.role,
            flow_count=s.flow_count,
            member_count=s.member_count,
        )
        for s in summaries
    ]


@router.post("", summary="Create a workspace", status_code=status.HTTP_201_CREATED)
async def create_workspace(
    body: WorkspaceCreate,
    principal: PrincipalDep,
    user: UserDep,
    container: ContainerDep,
    session: SessionDep,
) -> WorkspaceOut:
    workspace = await WorkspaceService(container, session).create(
        principal, body.name, body.description
    )
    return _out(workspace, Role.OWNER.value)


@router.get("/{workspace}", summary="A workspace and your role in it")
async def get_workspace(ctx: ViewerDep) -> WorkspaceOut:
    return _out(ctx.workspace, ctx.role.value)


@router.patch("/{workspace}", summary="Rename, describe or change settings (owner)")
async def update_workspace(
    body: WorkspaceUpdate, ctx: OwnerDep, container: ContainerDep, session: SessionDep
) -> WorkspaceOut:
    updated = await WorkspaceService(container, session).update(
        ctx.workspace,
        ctx.principal,
        name=body.name,
        description=body.description,
        settings=body.settings,
    )
    return _out(updated, ctx.role.value)


@router.delete(
    "/{workspace}",
    summary="Delete a workspace with every flow, run and document in it (owner)",
    status_code=204,
)
async def delete_workspace(ctx: OwnerDep, container: ContainerDep, session: SessionDep) -> None:
    await WorkspaceService(container, session).delete(ctx.workspace)


@router.get("/{workspace}/members", summary="Members and their roles")
async def list_members(
    ctx: ViewerDep,
    container: ContainerDep,
    session: SessionDep,
    limit: Limit = 50,
    offset: Offset = 0,
) -> Page[MemberOut]:
    rows, total = await WorkspaceService(container, session).members(
        ctx.id, limit=limit, offset=offset
    )
    return Page(items=[_member(m, u) for m, u in rows], total=total, limit=limit, offset=offset)


@router.post(
    "/{workspace}/members", summary="Add a member (creates the account if needed)", status_code=201
)
async def add_member(
    body: MemberAdd, ctx: OwnerDep, container: ContainerDep, session: SessionDep
) -> MemberAdded:
    membership, user, password = await WorkspaceService(container, session).add_member(
        ctx.workspace, ctx.principal, body.email, body.name, Role(body.role)
    )
    return MemberAdded(member=_member(membership, user), temporary_password=password)


@router.patch("/{workspace}/members/{user_id}", summary="Change a member's role")
async def update_member(
    user_id: uuid.UUID,
    body: MemberUpdate,
    ctx: OwnerDep,
    container: ContainerDep,
    session: SessionDep,
) -> MemberOut:
    membership, user = await WorkspaceService(container, session).change_role(
        ctx.workspace, ctx.principal, user_id, Role(body.role)
    )
    return _member(membership, user)


@router.delete(
    "/{workspace}/members/{user_id}", summary="Remove a member (or leave)", status_code=204
)
async def remove_member(
    user_id: uuid.UUID, ctx: ViewerDep, container: ContainerDep, session: SessionDep
) -> None:
    leaving = ctx.principal.user_id == user_id
    if not leaving and ctx.role != Role.OWNER:
        raise ForbiddenError("Only owners can remove other members.")
    await WorkspaceService(container, session).remove_member(ctx.workspace, ctx.principal, user_id)


@router.get("/{workspace}/audit", summary="Who changed what in this workspace (owner)")
async def audit_log(
    ctx: OwnerDep,
    session: SessionDep,
    limit: Limit = 50,
    offset: Offset = 0,
    action: Annotated[str | None, Query(max_length=64, description="Action prefix.")] = None,
) -> Page[AuditEventOut]:
    rows, total = await audit.page(session, ctx.id, limit=limit, offset=offset, action=action)
    return Page(
        items=[
            AuditEventOut(
                id=event.id,
                action=event.action,
                target_type=event.target_type,
                target_id=event.target_id,
                details=event.details,
                actor_name=name,
                created_at=event.created_at,
            )
            for event, name in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )
