from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, case, func, or_, select, update

from agentstudio.models import Flow, FlowVersion, Run
from agentstudio.models.enums import RunStatus
from agentstudio.repositories.base import Repository


@dataclass(frozen=True, slots=True)
class FlowStats:
    runs: int = 0
    succeeded: int = 0
    failed: int = 0


class FlowRepository(Repository):
    async def get(self, workspace_id: uuid.UUID, flow_id: uuid.UUID) -> Flow | None:
        result = await self.session.execute(
            select(Flow).where(Flow.id == flow_id, Flow.workspace_id == workspace_id)
        )
        return result.scalar_one_or_none()

    async def get_for_update(self, workspace_id: uuid.UUID, flow_id: uuid.UUID) -> Flow | None:
        result = await self.session.execute(
            select(Flow)
            .where(Flow.id == flow_id, Flow.workspace_id == workspace_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def by_webhook(self, hook_id: str) -> Flow | None:
        result = await self.session.execute(select(Flow).where(Flow.webhook_id == hook_id))
        return result.scalar_one_or_none()

    def _filtered(
        self,
        workspace_id: uuid.UUID,
        *,
        search: str | None,
        tag: str | None,
        published: bool | None,
    ) -> Select[Flow]:
        query = select(Flow).where(Flow.workspace_id == workspace_id)
        if search:
            pattern = f"%{search.strip()}%"
            query = query.where(or_(Flow.name.ilike(pattern), Flow.description.ilike(pattern)))
        if tag:
            query = query.where(Flow.tags.contains([tag]))
        if published is True:
            query = query.where(Flow.published_version_id.is_not(None))
        elif published is False:
            query = query.where(Flow.published_version_id.is_(None))
        return query

    async def page(
        self,
        workspace_id: uuid.UUID,
        *,
        limit: int,
        offset: int,
        search: str | None = None,
        tag: str | None = None,
        published: bool | None = None,
    ) -> tuple[list[Flow], int]:
        query = self._filtered(workspace_id, search=search, tag=tag, published=published)
        total = await self.count(query)
        result = await self.session.execute(
            query.order_by(Flow.updated_at.desc(), Flow.id.desc()).limit(limit).offset(offset)
        )
        return list(result.scalars()), total

    async def stats(
        self, workspace_id: uuid.UUID, flow_ids: list[uuid.UUID], since: datetime
    ) -> dict[uuid.UUID, FlowStats]:
        """Run counts per flow since a moment, in one grouped query."""
        if not flow_ids:
            return {}
        result = await self.session.execute(
            select(
                Run.flow_id,
                func.count(),
                func.count(case((Run.status == RunStatus.SUCCEEDED, 1))),
                func.count(case((Run.status == RunStatus.FAILED, 1))),
            )
            .where(
                Run.workspace_id == workspace_id,
                Run.flow_id.in_(flow_ids),
                Run.created_at >= since,
            )
            .group_by(Run.flow_id)
        )
        return {flow_id: FlowStats(total, ok, bad) for flow_id, total, ok, bad in result.all()}

    async def counts(self, workspace_id: uuid.UUID) -> tuple[int, int]:
        """(flows, published flows) in a workspace."""
        row = (
            await self.session.execute(
                select(
                    func.count(),
                    func.count(case((Flow.published_version_id.is_not(None), 1))),
                ).where(Flow.workspace_id == workspace_id)
            )
        ).one()
        return int(row[0]), int(row[1])

    async def tags(self, workspace_id: uuid.UUID) -> list[str]:
        tag = func.unnest(Flow.tags).label("tag")
        result = await self.session.execute(
            select(tag).where(Flow.workspace_id == workspace_id).distinct().order_by(tag)
        )
        return [str(value) for value in result.scalars()]

    async def add(self, flow: Flow) -> Flow:
        self.session.add(flow)
        await self.session.flush()
        return flow

    async def record_run(self, flow_id: uuid.UUID, at: datetime, status: str) -> None:
        await self.session.execute(
            update(Flow)
            .where(Flow.id == flow_id)
            .values(last_run_at=at, last_run_status=status, updated_at=Flow.updated_at)
        )

    # Versions ---------------------------------------------------------------------------

    async def version(self, flow_id: uuid.UUID, number: int) -> FlowVersion | None:
        result = await self.session.execute(
            select(FlowVersion).where(FlowVersion.flow_id == flow_id, FlowVersion.version == number)
        )
        return result.scalar_one_or_none()

    async def version_by_id(
        self, workspace_id: uuid.UUID, version_id: uuid.UUID
    ) -> FlowVersion | None:
        result = await self.session.execute(
            select(FlowVersion).where(
                FlowVersion.id == version_id, FlowVersion.workspace_id == workspace_id
            )
        )
        return result.scalar_one_or_none()

    async def versions(
        self, flow_id: uuid.UUID, *, limit: int, offset: int
    ) -> tuple[list[FlowVersion], int]:
        query = select(FlowVersion).where(FlowVersion.flow_id == flow_id)
        total = await self.count(query)
        result = await self.session.execute(
            query.order_by(FlowVersion.version.desc()).limit(limit).offset(offset)
        )
        return list(result.scalars()), total

    async def add_version(self, version: FlowVersion) -> FlowVersion:
        self.session.add(version)
        await self.session.flush()
        return version
