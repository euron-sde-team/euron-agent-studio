from __future__ import annotations

import uuid

from sqlalchemy import select

from agentstudio.models import AuditEvent, User
from agentstudio.repositories.base import Repository


class AuditRepository(Repository):
    async def add(self, event: AuditEvent) -> None:
        self.session.add(event)

    async def page(
        self, workspace_id: uuid.UUID, *, limit: int, offset: int, action: str | None = None
    ) -> tuple[list[tuple[AuditEvent, str | None]], int]:
        query = (
            select(AuditEvent, User.name)
            .outerjoin(User, User.id == AuditEvent.actor_user_id)
            .where(AuditEvent.workspace_id == workspace_id)
        )
        if action:
            query = query.where(AuditEvent.action.startswith(action))
        total = await self.count(query)
        result = await self.session.execute(
            query.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return [(event, name) for event, name in result.all()], total
