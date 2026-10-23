from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from agentstudio.models import Approval, Flow, Run
from agentstudio.models.enums import ApprovalStatus
from agentstudio.repositories.base import Repository


class ApprovalRepository(Repository):
    async def add_once(self, approval: Approval) -> Approval:
        """Create the approval, or return the one this run already has for the node."""
        values = {
            column.key: getattr(approval, column.key)
            for column in Approval.__table__.columns
            if getattr(approval, column.key, None) is not None
        }
        await self.session.execute(
            insert(Approval)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["run_id", "node_id"])
        )
        result = await self.session.execute(
            select(Approval).where(
                Approval.run_id == approval.run_id, Approval.node_id == approval.node_id
            )
        )
        return result.scalar_one()

    async def get(self, workspace_id: uuid.UUID, approval_id: uuid.UUID) -> Approval | None:
        result = await self.session.execute(
            select(Approval).where(
                Approval.id == approval_id, Approval.workspace_id == workspace_id
            )
        )
        return result.scalar_one_or_none()

    async def get_for_update(
        self, workspace_id: uuid.UUID, approval_id: uuid.UUID
    ) -> Approval | None:
        result = await self.session.execute(
            select(Approval)
            .where(Approval.id == approval_id, Approval.workspace_id == workspace_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def for_run(self, run_id: uuid.UUID) -> list[Approval]:
        result = await self.session.execute(
            select(Approval).where(Approval.run_id == run_id).order_by(Approval.created_at)
        )
        return list(result.scalars())

    async def page(
        self, workspace_id: uuid.UUID, *, status: str | None, limit: int, offset: int
    ) -> tuple[list[tuple[Approval, str, Run]], int]:
        query = (
            select(Approval, Flow.name, Run)
            .join(Flow, Flow.id == Approval.flow_id)
            .join(Run, Run.id == Approval.run_id)
            .where(Approval.workspace_id == workspace_id)
        )
        if status:
            query = query.where(Approval.status == status)
        total = await self.count(query)
        result = await self.session.execute(
            query.order_by(Approval.created_at.desc(), Approval.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return [(approval, name, run) for approval, name, run in result.all()], total

    async def pending_count(self, workspace_id: uuid.UUID) -> int:
        return int(
            await self.session.scalar(
                select(func.count()).where(
                    Approval.workspace_id == workspace_id, Approval.status == ApprovalStatus.PENDING
                )
            )
            or 0
        )

    async def expired(self, now: datetime, limit: int = 50) -> list[Approval]:
        result = await self.session.execute(
            select(Approval)
            .where(Approval.status == ApprovalStatus.PENDING, Approval.expires_at <= now)
            .order_by(Approval.expires_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(result.scalars())
