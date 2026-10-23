from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select

from agentstudio.models import Flow, Membership, User, Workspace
from agentstudio.models.enums import Role
from agentstudio.repositories.base import Repository


@dataclass(frozen=True, slots=True)
class WorkspaceSummary:
    workspace: Workspace
    role: str
    flow_count: int
    member_count: int


class WorkspaceRepository(Repository):
    async def get(self, workspace_id: uuid.UUID) -> Workspace | None:
        return await self.session.get(Workspace, workspace_id)

    async def by_slug(self, slug: str) -> Workspace | None:
        result = await self.session.execute(select(Workspace).where(Workspace.slug == slug))
        return result.scalar_one_or_none()

    async def slug_taken(self, slug: str) -> bool:
        return bool(await self.session.scalar(select(func.count()).where(Workspace.slug == slug)))

    async def add(self, workspace: Workspace) -> Workspace:
        self.session.add(workspace)
        await self.session.flush()
        return workspace

    async def membership(self, workspace_id: uuid.UUID, user_id: uuid.UUID) -> Membership | None:
        return await self.session.get(Membership, (workspace_id, user_id))

    async def for_user(self, user_id: uuid.UUID) -> list[WorkspaceSummary]:
        flows = select(func.count()).where(Flow.workspace_id == Workspace.id).scalar_subquery()
        members = (
            select(func.count()).where(Membership.workspace_id == Workspace.id).scalar_subquery()
        )
        result = await self.session.execute(
            select(Workspace, Membership.role, flows, members)
            .join(Membership, Membership.workspace_id == Workspace.id)
            .where(Membership.user_id == user_id)
            .order_by(Workspace.name)
        )
        return [WorkspaceSummary(w, role, count, people) for w, role, count, people in result.all()]

    async def members(
        self, workspace_id: uuid.UUID, *, limit: int, offset: int
    ) -> tuple[list[tuple[Membership, User]], int]:
        query = (
            select(Membership, User)
            .join(User, User.id == Membership.user_id)
            .where(Membership.workspace_id == workspace_id)
        )
        total = await self.count(query)
        result = await self.session.execute(
            query.order_by(Membership.created_at, User.id).limit(limit).offset(offset)
        )
        return [(m, u) for m, u in result.all()], total

    async def member(
        self, workspace_id: uuid.UUID, user_id: uuid.UUID
    ) -> tuple[Membership, User] | None:
        result = await self.session.execute(
            select(Membership, User)
            .join(User, User.id == Membership.user_id)
            .where(Membership.workspace_id == workspace_id, Membership.user_id == user_id)
        )
        row = result.first()
        return (row[0], row[1]) if row else None

    async def owner_count(self, workspace_id: uuid.UUID) -> int:
        return int(
            await self.session.scalar(
                select(func.count()).where(
                    Membership.workspace_id == workspace_id, Membership.role == Role.OWNER
                )
            )
            or 0
        )

    async def add_member(
        self, workspace_id: uuid.UUID, user_id: uuid.UUID, role: Role
    ) -> Membership:
        membership = Membership(workspace_id=workspace_id, user_id=user_id, role=role.value)
        self.session.add(membership)
        await self.session.flush()
        return membership
