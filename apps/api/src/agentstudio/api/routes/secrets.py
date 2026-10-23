"""Workspace secrets for flows. Values are write-only: the API never returns them."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, status

from agentstudio.api.deps import ContainerDep, EditorDep, OwnerDep, SessionDep
from agentstudio.schemas.common import Limit, Offset, Page
from agentstudio.schemas.secrets import SECRET_NAME_PATTERN, SecretCreate, SecretOut, SecretUpdate
from agentstudio.services.secrets import SecretService

router = APIRouter(prefix="/api/v1/workspaces/{workspace}/secrets", tags=["secrets"])
SecretName = Annotated[str, Path(pattern=SECRET_NAME_PATTERN)]


@router.get("", summary="Secret names and descriptions (never values)")
async def list_secrets(
    ctx: EditorDep,
    container: ContainerDep,
    session: SessionDep,
    limit: Limit = 50,
    offset: Offset = 0,
) -> Page[SecretOut]:
    secrets, total = await SecretService(container, session).page(
        ctx.id, limit=limit, offset=offset
    )
    return Page(
        items=[SecretOut.model_validate(s) for s in secrets],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("", summary="Store a secret", status_code=status.HTTP_201_CREATED)
async def create_secret(
    body: SecretCreate, ctx: OwnerDep, container: ContainerDep, session: SessionDep
) -> SecretOut:
    secret = await SecretService(container, session).create(
        ctx.workspace, ctx.principal, body.name, body.value, body.description
    )
    return SecretOut.model_validate(secret)


@router.patch("/{name}", summary="Replace a secret's value or description")
async def update_secret(
    name: SecretName,
    body: SecretUpdate,
    ctx: OwnerDep,
    container: ContainerDep,
    session: SessionDep,
) -> SecretOut:
    secret = await SecretService(container, session).update(
        ctx.workspace, ctx.principal, name, value=body.value, description=body.description
    )
    return SecretOut.model_validate(secret)


@router.delete("/{name}", summary="Delete a secret", status_code=204)
async def delete_secret(
    name: SecretName, ctx: OwnerDep, container: ContainerDep, session: SessionDep
) -> None:
    await SecretService(container, session).delete(ctx.workspace, ctx.principal, name)
