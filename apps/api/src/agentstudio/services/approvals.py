"""Human approvals: the inbox, decisions, and expiry. A decision re-queues the paused run."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from agentstudio.core import metrics
from agentstudio.core.errors import ConflictError, NotFoundError
from agentstudio.core.logging import get_logger
from agentstudio.integrations.queue import RunJob
from agentstudio.models import Approval, User, Workspace
from agentstudio.models.enums import ApprovalStatus, RunStatus
from agentstudio.repositories.approvals import ApprovalRepository
from agentstudio.repositories.flows import FlowRepository
from agentstudio.repositories.runs import RunRepository
from agentstudio.repositories.users import UserRepository
from agentstudio.services import audit
from agentstudio.services.cache import dashboard_key
from agentstudio.services.container import Container
from agentstudio.services.principal import Principal

log = get_logger("agentstudio.approvals")


@dataclass(frozen=True, slots=True)
class ApprovalView:
    approval: Approval
    flow_name: str
    run_status: str
    decided_by_name: str | None


class ApprovalService:
    def __init__(self, container: Container, session: AsyncSession) -> None:
        self.c = container
        self.session = session
        self.approvals = ApprovalRepository(session)

    async def page(
        self, workspace_id: uuid.UUID, *, status: str | None, limit: int, offset: int
    ) -> tuple[list[ApprovalView], int]:
        rows, total = await self.approvals.page(
            workspace_id, status=status, limit=limit, offset=offset
        )
        names = await UserRepository(self.session).names(
            {a.decided_by for a, _, _ in rows if a.decided_by}
        )
        return [
            ApprovalView(
                a, flow_name, run.status, names.get(a.decided_by) if a.decided_by else None
            )
            for a, flow_name, run in rows
        ], total

    async def pending_count(self, workspace_id: uuid.UUID) -> int:
        return await self.approvals.pending_count(workspace_id)

    async def view(self, workspace_id: uuid.UUID, approval_id: uuid.UUID) -> ApprovalView:
        approval = await self.approvals.get(workspace_id, approval_id)
        if approval is None:
            raise NotFoundError("Approval not found.")
        flow = await FlowRepository(self.session).get(workspace_id, approval.flow_id)
        run = await RunRepository(self.session).get(workspace_id, approval.run_id)
        names = await UserRepository(self.session).names(
            {approval.decided_by} if approval.decided_by else set()
        )
        return ApprovalView(
            approval,
            flow.name if flow else "",
            run.status if run else "",
            names.get(approval.decided_by) if approval.decided_by else None,
        )

    async def decide(
        self,
        workspace: Workspace,
        principal: Principal,
        user: User,
        approval_id: uuid.UUID,
        *,
        approve: bool,
        comment: str,
    ) -> ApprovalView:
        approval = await self.approvals.get_for_update(workspace.id, approval_id)
        if approval is None:
            raise NotFoundError("Approval not found.")
        if approval.status != ApprovalStatus.PENDING:
            raise ConflictError(
                f"This approval was already {approval.status}.", code="already_decided"
            )
        now = datetime.now(UTC)
        approval.status = ApprovalStatus.APPROVED if approve else ApprovalStatus.REJECTED
        approval.decided_by = user.id
        approval.decided_at = now
        approval.comment = comment.strip()
        runs = RunRepository(self.session)
        resumed = await runs.set_status(
            approval.run_id, RunStatus.QUEUED, expected=(RunStatus.WAITING,)
        )
        await audit.record(
            self.session,
            workspace_id=workspace.id,
            principal=principal,
            action="approval.decided",
            target_type="approval",
            target_id=approval.id,
            details={
                "decision": approval.status,
                "title": approval.title,
                "run_id": str(approval.run_id),
                "node_id": approval.node_id,
            },
        )
        await self.session.commit()
        await _after_decision(self.c, approval, resumed, decided_by=user.name)
        return await self.view(workspace.id, approval.id)


async def _after_decision(
    container: Container, approval: Approval, resumed: bool, *, decided_by: str | None
) -> None:
    await container.trace.publish(
        approval.run_id,
        "approval.decided",
        {
            "approval_id": str(approval.id),
            "node_id": approval.node_id,
            "status": approval.status,
            "decided_by": decided_by,
            "comment": approval.comment,
        },
    )
    if resumed:
        await container.queue.enqueue(RunJob(approval.run_id, approval.workspace_id))
    await container.redis.delete(dashboard_key(approval.workspace_id))


async def expire_due(container: Container, now: datetime) -> int:
    """Approvals past their deadline count as rejected; their runs continue."""
    decided: list[tuple[Approval, bool]] = []
    async with container.db.session() as session:
        runs = RunRepository(session)
        for approval in await ApprovalRepository(session).expired(now):
            approval.status = ApprovalStatus.EXPIRED
            approval.decided_at = now
            approval.comment = "Expired before anyone decided."
            resumed = await runs.set_status(
                approval.run_id, RunStatus.QUEUED, expected=(RunStatus.WAITING,)
            )
            await audit.record(
                session,
                workspace_id=approval.workspace_id,
                principal=None,
                action="approval.expired",
                target_type="approval",
                target_id=approval.id,
                details={
                    "title": approval.title,
                    "run_id": str(approval.run_id),
                    "node_id": approval.node_id,
                },
            )
            decided.append((approval, resumed))
        await session.commit()
    for approval, resumed in decided:
        metrics.REAPED.labels("approval").inc()
        log.info("approval_expired", approval_id=str(approval.id))
        await _after_decision(container, approval, resumed, decided_by=None)
    return len(decided)
