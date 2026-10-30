"""Runs: starting, waiting, cancelling and re-running, and executing them on a worker.

`RunService` is the request side: it validates, stores the run as `queued`, publishes the
first trace event and puts the run id on the queue. `RunExecution` is the worker side: it
claims a queued run with a conditional update, rebuilds state from recorded steps (resume
after an approval or a crash), executes the plan while heartbeating, and finalises the row.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from datetime import UTC, datetime
from typing import Any, NamedTuple

from sqlalchemy.ext.asyncio import AsyncSession

from agentstudio.core import metrics
from agentstudio.core.errors import (
    ConflictError,
    NotFoundError,
    RateLimitedError,
    UnprocessableError,
)
from agentstudio.core.logging import get_logger
from agentstudio.engine import runtime
from agentstudio.engine.executor import (
    Decision,
    ExecutionResult,
    Executor,
    Limits,
    RestoredStep,
    ResumeState,
)
from agentstudio.engine.graph import GraphDocument, StartConfig
from agentstudio.engine.plan import InvalidGraphError, build_plan, secret_names
from agentstudio.engine.ports import EngineServices
from agentstudio.engine.recorder import ApprovalRequest, ApprovalTicket, StepEnd, StepStart
from agentstudio.integrations.queue import RunJob, send_or_defer
from agentstudio.models import Approval, Run, RunStep, Workspace
from agentstudio.models.enums import ApprovalStatus, RunStatus, RunTrigger, StepStatus
from agentstudio.providers.registry import WorkspaceModels
from agentstudio.repositories.approvals import ApprovalRepository
from agentstudio.repositories.flows import FlowRepository
from agentstudio.repositories.runs import RunRepository
from agentstudio.repositories.users import UserRepository
from agentstudio.services import audit
from agentstudio.services.approvals import expire_due
from agentstudio.services.cache import dashboard_key
from agentstudio.services.container import Container
from agentstudio.services.flows import FlowService, VersionRef
from agentstudio.services.knowledge import WorkspaceKnowledge
from agentstudio.services.principal import Principal
from agentstudio.services.secrets import SecretService
from agentstudio.services.views import RunDetailView, RunView, triggered_by

log = get_logger("agentstudio.runs")
FINAL = frozenset({RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED})
MAX_CLAIMS = 5
# A queued run is claimed seconds after its message arrives. One still queued this long after
# it was sent lost the message (or never had one), so the reaper sends it again; duplicates
# are harmless because claims are conditional.
RESEND_AFTER_S = 300


class Reaped(NamedTuple):
    requeued: int  # running runs whose worker vanished, handed out again
    resent: int  # queued runs whose message was lost, sent again
    expired: int  # approvals past their deadline


class RunService:
    def __init__(self, container: Container, session: AsyncSession) -> None:
        self.c = container
        self.session = session
        self.runs = RunRepository(session)

    async def start(
        self,
        workspace: Workspace,
        principal: Principal | None,
        flow_id: uuid.UUID,
        inputs: dict[str, Any],
        version: VersionRef,
        *,
        trigger: RunTrigger,
        rerun_of: Run | None = None,
    ) -> Run:
        flows = FlowService(self.c, self.session)
        flow = await flows.get(workspace.id, flow_id)
        if rerun_of is not None and rerun_of.graph is not None:
            document = GraphDocument.model_validate(rerun_of.graph)
            number, version_id = 0, None
        else:
            resolved = await flows.resolve(flow, version)
            document, number, version_id = resolved.document, resolved.version, resolved.version_id
        plan = await flows.plan(workspace.id, document)
        start = plan.nodes[plan.start_id].config
        fields = (
            [field.model_dump() for field in start.inputs] if isinstance(start, StartConfig) else []
        )
        try:
            runtime.validate_inputs(inputs, fields)
        except runtime.ExpressionError as exc:
            raise UnprocessableError(str(exc), code="invalid_inputs") from exc
        if (
            await self.runs.active_count(workspace.id)
            >= self.c.settings.max_active_runs_per_workspace
        ):
            raise RateLimitedError(
                "Too many runs are queued or running in this workspace. Try again shortly.",
                code="too_many_active_runs",
            )
        run = await self.runs.add(
            Run(
                workspace_id=workspace.id,
                flow_id=flow.id,
                flow_version_id=version_id,
                version=number,
                graph=document.model_dump(mode="json") if version_id is None else None,
                status=RunStatus.QUEUED,
                trigger=trigger,
                inputs=inputs,
                enqueued_at=datetime.now(UTC),
                triggered_by_user_id=principal.user_id if principal else None,
                triggered_by_api_key_id=principal.api_key_id if principal else None,
                rerun_of_id=rerun_of.id if rerun_of else None,
            )
        )
        await self.session.commit()
        metrics.RUNS_STARTED.labels(trigger.value).inc()
        await self.c.trace.publish(
            run.id,
            "run.queued",
            {
                "run_id": str(run.id),
                "status": RunStatus.QUEUED,
                "version": number,
                "trigger": trigger,
            },
        )
        await send_or_defer(self.c.queue, RunJob(run.id, workspace.id))
        await self.c.redis.delete(dashboard_key(workspace.id))
        return run

    async def wait(self, workspace_id: uuid.UUID, run: Run, timeout_s: float) -> Run:
        """Block until the run finishes or pauses, or the timeout passes, then reload it."""
        deadline = time.monotonic() + timeout_s
        cursor = "0-0"
        while (remaining := deadline - time.monotonic()) > 0:
            events = await self.c.trace.read(
                run.id, cursor, block_ms=int(min(remaining, 15) * 1000)
            )
            if events:
                cursor = events[-1].id
                if any(e.type in {"run.finished", "run.waiting"} for e in events):
                    break
        return await self.get(workspace_id, run.id, fresh=True)

    async def get(self, workspace_id: uuid.UUID, run_id: uuid.UUID, *, fresh: bool = False) -> Run:
        run = await self.runs.get(workspace_id, run_id, fresh=fresh)
        if run is None:
            raise NotFoundError("Run not found.")
        return run

    async def view(self, workspace_id: uuid.UUID, run_id: uuid.UUID) -> RunView:
        run = await self.get(workspace_id, run_id, fresh=True)
        flow = await FlowRepository(self.session).get(workspace_id, run.flow_id)
        names = await triggered_by(self.session, [run])
        return RunView(run, flow.name if flow else "", names.get(run.id))

    async def page(
        self,
        workspace_id: uuid.UUID,
        *,
        limit: int,
        offset: int,
        flow_id: uuid.UUID | None = None,
        status: str | None = None,
        trigger: str | None = None,
    ) -> tuple[list[RunView], int]:
        rows, total = await self.runs.page(
            workspace_id,
            limit=limit,
            offset=offset,
            flow_id=flow_id,
            status=status,
            trigger=trigger,
        )
        names = await triggered_by(self.session, [run for run, _ in rows])
        return [RunView(run, flow_name, names.get(run.id)) for run, flow_name in rows], total

    async def detail(self, workspace_id: uuid.UUID, run_id: uuid.UUID) -> RunDetailView:
        view = await self.view(workspace_id, run_id)
        run = view.run
        graph = run.graph
        if graph is None and run.flow_version_id is not None:
            version = await FlowRepository(self.session).version_by_id(
                workspace_id, run.flow_version_id
            )
            graph = version.graph if version else {}
        approvals = await ApprovalRepository(self.session).for_run(run.id)
        deciders = await UserRepository(self.session).names(
            {a.decided_by for a in approvals if a.decided_by}
        )
        return RunDetailView(
            view=view,
            graph=graph or {},
            steps=await self.runs.steps(run.id),
            approvals=[
                (a, deciders.get(a.decided_by) if a.decided_by else None) for a in approvals
            ],
        )

    async def cancel(self, workspace: Workspace, principal: Principal, run_id: uuid.UUID) -> Run:
        run = await self.get(workspace.id, run_id)
        if RunStatus(run.status) in FINAL:
            raise ConflictError("This run has already finished.", code="run_finished")
        now = datetime.now(UTC)
        if run.status in (RunStatus.QUEUED, RunStatus.WAITING):
            done = await self.runs.set_status(
                run.id,
                RunStatus.CANCELLED,
                expected=(RunStatus.QUEUED, RunStatus.WAITING),
                values={"finished_at": now, "cancel_requested_at": now},
            )
            if done:
                await _cancel_pending_approvals(self.session, run.id, now)
                await FlowRepository(self.session).record_run(run.flow_id, now, RunStatus.CANCELLED)
        else:
            run.cancel_requested_at = now
            done = False
        await audit.record(
            self.session,
            workspace_id=workspace.id,
            principal=principal,
            action="run.cancelled",
            target_type="run",
            target_id=run.id,
            details={"flow_id": str(run.flow_id), "status": run.status},
        )
        await self.session.commit()
        if done:
            await self.c.trace.publish(run.id, "run.finished", {"status": RunStatus.CANCELLED})
            await self.c.trace.finished(run.id)
            metrics.RUNS_FINISHED.labels(RunStatus.CANCELLED.value).inc()
        else:
            # The worker executing it sees the flag within half a second and stops.
            await self.c.trace.request_cancel(run.id)
        await self.c.redis.delete(dashboard_key(workspace.id))
        return await self.get(workspace.id, run.id, fresh=True)

    async def rerun(self, workspace: Workspace, principal: Principal, run_id: uuid.UUID) -> Run:
        source = await self.get(workspace.id, run_id)
        version: VersionRef = source.version if source.version else "draft"
        return await self.start(
            workspace,
            principal,
            source.flow_id,
            dict(source.inputs),
            version,
            trigger=RunTrigger.RERUN,
            rerun_of=source,
        )


async def _cancel_pending_approvals(
    session: AsyncSession, run_id: uuid.UUID, now: datetime
) -> None:
    for approval in await ApprovalRepository(session).for_run(run_id):
        if approval.status == ApprovalStatus.PENDING:
            approval.status = ApprovalStatus.CANCELLED
            approval.decided_at = now


# ----------------------------------------------------------------------------------------
# Execution
# ----------------------------------------------------------------------------------------


class RedisCancel:
    """The executor's cancel port: the run's flag in Redis."""

    def __init__(self, container: Container, run_id: uuid.UUID) -> None:
        self.c = container
        self.run_id = run_id

    async def requested(self) -> bool:
        return await self.c.trace.cancel_requested(self.run_id)


class DbRecorder:
    """The executor's recorder port: step rows in Postgres, events on the run's stream."""

    def __init__(self, container: Container, run: Run) -> None:
        self.c = container
        self.run = run

    async def step_started(self, step: StepStart) -> None:
        async with self.c.db.session() as session:
            await RunRepository(session).start_step(
                {
                    "id": uuid.uuid4(),
                    "run_id": self.run.id,
                    "workspace_id": self.run.workspace_id,
                    "node_id": step.node_id,
                    "node_type": step.node_type,
                    "label": step.label[:120],
                    "iteration": step.iteration,
                    "seq": step.seq,
                    "status": StepStatus.RUNNING,
                    "attempt": step.attempt,
                    "input": step.input,
                    "started_at": datetime.now(UTC),
                }
            )
            await session.commit()
        await self.c.trace.publish(
            self.run.id,
            "step.started",
            {
                "node_id": step.node_id,
                "node_type": step.node_type,
                "label": step.label,
                "iteration": step.iteration,
                "seq": step.seq,
                "attempt": step.attempt,
                "input": step.input,
            },
        )

    async def step_event(self, node_id: str, iteration: str, event: dict[str, Any]) -> None:
        async with self.c.db.session() as session:
            await RunRepository(session).append_event(self.run.id, node_id, iteration, event)
            await session.commit()
        await self.c.trace.publish(
            self.run.id,
            "step.progress",
            {"node_id": node_id, "iteration": iteration, "event": event},
        )

    async def step_finished(self, step: StepEnd) -> None:
        now = datetime.now(UTC)
        latency = step.latency_ms
        async with self.c.db.session() as session:
            repo = RunRepository(session)
            if step.node_type == "approval":
                # An approval's latency is the time it waited for a person, not the resume.
                row = await repo.step(self.run.id, step.node_id, step.iteration)
                if row is not None:
                    latency = int((now - row.started_at).total_seconds() * 1000)
            await repo.update_step(
                self.run.id,
                step.node_id,
                step.iteration,
                {
                    "status": step.status,
                    "attempt": step.attempt,
                    "output": step.output,
                    "error": step.error,
                    "handles": list(step.handles),
                    "model": step.model,
                    "prompt_tokens": step.prompt_tokens,
                    "completion_tokens": step.completion_tokens,
                    "cost_usd": step.cost_usd,
                    "cached": step.cached,
                    "continued": step.continued,
                    "finished_at": now,
                    "latency_ms": latency,
                },
            )
            await session.commit()
        metrics.STEPS.labels(step.node_type, step.status).inc()
        metrics.STEP_LATENCY.labels(step.node_type).observe(latency / 1000)
        await self.c.trace.publish(
            self.run.id,
            "step.finished",
            {
                "node_id": step.node_id,
                "node_type": step.node_type,
                "iteration": step.iteration,
                "status": step.status,
                "attempt": step.attempt,
                "output": step.output,
                "error": step.error,
                "handles": list(step.handles),
                "model": step.model,
                "prompt_tokens": step.prompt_tokens,
                "completion_tokens": step.completion_tokens,
                "cost_usd": float(step.cost_usd),
                "cached": step.cached,
                "continued": step.continued,
                "latency_ms": latency,
            },
        )

    async def approval_requested(self, request: ApprovalRequest) -> ApprovalTicket:
        async with self.c.db.session() as session:
            approval = await ApprovalRepository(session).add_once(
                Approval(
                    id=uuid.uuid4(),
                    workspace_id=self.run.workspace_id,
                    run_id=self.run.id,
                    flow_id=self.run.flow_id,
                    node_id=request.node_id,
                    title=request.title[:200],
                    message=request.message,
                    context=request.context,
                    status=ApprovalStatus.PENDING,
                    expires_at=request.expires_at,
                )
            )
            await RunRepository(session).update_step(
                self.run.id, request.node_id, "", {"status": StepStatus.WAITING}
            )
            await session.commit()
        await self.c.trace.publish(
            self.run.id,
            "step.waiting",
            {"node_id": request.node_id, "approval_id": str(approval.id), "title": approval.title},
        )
        return ApprovalTicket(approval.id)


def resume_state(
    steps: list[RunStep], approvals: list[Approval], names: dict[uuid.UUID, str]
) -> ResumeState:
    """Everything earlier executions of a run already did, rebuilt from its rows."""
    state = ResumeState(next_seq=max((s.seq for s in steps), default=0) + 1)
    for step in steps:
        if step.iteration:
            continue
        finished = step.status in (StepStatus.SUCCEEDED, StepStatus.SKIPPED) or (
            step.status == StepStatus.FAILED and step.continued
        )
        if finished:
            state.steps[step.node_id] = RestoredStep(step.status, step.output, tuple(step.handles))
    for approval in approvals:
        if approval.status in (
            ApprovalStatus.APPROVED,
            ApprovalStatus.REJECTED,
            ApprovalStatus.EXPIRED,
        ):
            state.decisions[approval.node_id] = Decision(
                approved=approval.status == ApprovalStatus.APPROVED,
                comment=approval.comment,
                decided_by=names.get(approval.decided_by) if approval.decided_by else None,
                decided_at=approval.decided_at.isoformat() if approval.decided_at else None,
            )
    return state


class RunExecution:
    """Executes queued runs. Used by the worker, and by the API with the inline queue."""

    def __init__(self, container: Container) -> None:
        self.c = container

    def limits(self) -> Limits:
        settings = self.c.settings
        return Limits(
            max_parallel_steps=settings.max_parallel_steps,
            run_timeout_s=settings.run_timeout_s,
            max_loop_items=settings.max_loop_items,
            max_payload_bytes=settings.max_step_payload_kb * 1024,
        )

    async def execute(self, job: RunJob) -> str | None:
        """Claim and run one job. Returns the status it ended in, or None if not claimed."""
        now = datetime.now(UTC)
        async with self.c.db.session() as session:
            run = await RunRepository(session).claim(job.workspace_id, job.run_id, now)
            await session.commit()
            if run is None:
                log.info("run_not_claimed", run_id=str(job.run_id))
                return None
            graph = run.graph
            if graph is None and run.flow_version_id is not None:
                version = await FlowRepository(session).version_by_id(
                    run.workspace_id, run.flow_version_id
                )
                graph = version.graph if version else None
            repo = RunRepository(session)
            steps = await repo.steps(run.id)
            approvals = await ApprovalRepository(session).for_run(run.id)
            deciders = await UserRepository(session).names(
                {a.decided_by for a in approvals if a.decided_by}
            )
            resume = resume_state(steps, approvals, deciders)
            try:
                plan = build_plan(GraphDocument.model_validate(graph or {}))
            except (InvalidGraphError, ValueError):
                plan = None
            secrets = (
                await SecretService(self.c, session).resolve(run.workspace_id, secret_names(plan))
                if plan is not None
                else {}
            )
            await session.commit()

        started = time.monotonic()
        metrics.ACTIVE_RUNS.inc()
        await self.c.trace.publish(
            run.id, "run.started", {"status": RunStatus.RUNNING, "resumed": run.claims > 1}
        )
        heartbeat = asyncio.create_task(self._heartbeat(run.id))
        try:
            if plan is None:
                result = ExecutionResult(
                    "failed", error={"code": "invalid_flow", "message": "The flow is not valid."}
                )
            else:
                services = EngineServices(
                    models=WorkspaceModels(self.c.models, run.workspace_id),
                    knowledge=WorkspaceKnowledge(self.c, run.workspace_id),
                    http=self.c.http,
                    cancel=RedisCancel(self.c, run.id),
                )
                executor = Executor(
                    plan, services, DbRecorder(self.c, run), limits=self.limits(), secrets=secrets
                )
                try:
                    result = await executor.execute(run.inputs, resume)
                except asyncio.CancelledError:
                    await asyncio.shield(self._release(run.id))
                    raise
                except Exception as exc:
                    log.exception("run_crashed", run_id=str(run.id))
                    result = ExecutionResult(
                        "failed", error={"code": "internal_error", "message": type(exc).__name__}
                    )
        finally:
            heartbeat.cancel()
            metrics.ACTIVE_RUNS.dec()
            metrics.RUN_DURATION.observe(time.monotonic() - started)
        await self.finalize(run, result)
        return result.status

    async def _heartbeat(self, run_id: uuid.UUID) -> None:
        while True:
            await asyncio.sleep(self.c.settings.heartbeat_s)
            with contextlib.suppress(Exception):
                async with self.c.db.session() as session:
                    await RunRepository(session).heartbeat(run_id, datetime.now(UTC))
                    await session.commit()

    async def _release(self, run_id: uuid.UUID) -> None:
        """A worker shutting down mid-run hands the run back to the queue to resume."""
        async with self.c.db.session() as session:
            await RunRepository(session).set_status(
                run_id,
                RunStatus.QUEUED,
                expected=(RunStatus.RUNNING,),
                values={"heartbeat_at": None, "enqueued_at": datetime.now(UTC)},
            )
            await session.commit()
        log.info("run_released", run_id=str(run_id))

    async def finalize(self, run: Run, result: ExecutionResult) -> None:
        now = datetime.now(UTC)
        status = RunStatus(result.status)
        async with self.c.db.session() as session:
            repo = RunRepository(session)
            totals = await repo.totals(run.id)
            values: dict[str, Any] = {
                "prompt_tokens": totals.prompt_tokens,
                "completion_tokens": totals.completion_tokens,
                "cost_usd": totals.cost_usd,
                "cost_simulated": totals.simulated,
                "step_count": totals.step_count,
                "heartbeat_at": None,
            }
            if status != RunStatus.WAITING:
                started_at = run.started_at or now
                values.update(
                    outputs=result.outputs if status == RunStatus.SUCCEEDED else None,
                    error=result.error,
                    finished_at=now,
                    duration_ms=int((now - started_at).total_seconds() * 1000),
                )
                if status == RunStatus.CANCELLED:
                    await _cancel_pending_approvals(session, run.id, now)
            await repo.set_status(run.id, status, expected=(RunStatus.RUNNING,), values=values)
            await FlowRepository(session).record_run(run.flow_id, now, status)
            await session.commit()
        metrics.RUNS_FINISHED.labels(status.value).inc()
        if status == RunStatus.WAITING:
            await self.c.trace.publish(
                run.id, "run.waiting", {"status": status, "waiting_on": result.waiting_on}
            )
        else:
            await self.c.trace.publish(
                run.id,
                "run.finished",
                {
                    "status": status,
                    "outputs": result.outputs if status == RunStatus.SUCCEEDED else None,
                    "error": result.error,
                    "prompt_tokens": totals.prompt_tokens,
                    "completion_tokens": totals.completion_tokens,
                    "cost_usd": float(totals.cost_usd),
                    "duration_ms": values.get("duration_ms"),
                },
            )
            await self.c.trace.finished(run.id)
        await self.c.redis.delete(dashboard_key(run.workspace_id))

    async def reap(self) -> Reaped:
        """Re-queue runs whose worker vanished, resend lost messages, expire approvals.

        A run that keeps losing its worker (one that crashes the process, for example) is
        failed after MAX_CLAIMS attempts instead of being handed out forever.
        """
        now = datetime.now(UTC)
        cutoff = datetime.fromtimestamp(now.timestamp() - self.c.settings.stale_run_s, UTC)
        resend_before = datetime.fromtimestamp(now.timestamp() - RESEND_AFTER_S, UTC)
        requeued: list[RunJob] = []
        failed: list[Run] = []
        async with self.c.db.session() as session:
            repo = RunRepository(session)
            resent = [
                RunJob(run_id, workspace_id)
                for run_id, workspace_id in await repo.resend_due(resend_before, now)
            ]
            for run in await repo.stale(cutoff):
                if run.claims >= MAX_CLAIMS:
                    error = {
                        "code": "worker_lost",
                        "message": f"The run lost its worker {run.claims} times and was stopped.",
                    }
                    values = {"finished_at": now, "error": error, "heartbeat_at": None}
                    if await repo.set_status(
                        run.id, RunStatus.FAILED, expected=(RunStatus.RUNNING,), values=values
                    ):
                        failed.append(run)
                elif await repo.set_status(
                    run.id,
                    RunStatus.QUEUED,
                    expected=(RunStatus.RUNNING,),
                    values={"heartbeat_at": None, "enqueued_at": now},
                ):
                    requeued.append(RunJob(run.id, run.workspace_id))
            await session.commit()
        for run in failed:
            log.error("run_abandoned", run_id=str(run.id), claims=run.claims)
            await self.c.trace.publish(run.id, "run.finished", {"status": RunStatus.FAILED})
            await self.c.trace.finished(run.id)
        for job in requeued:
            metrics.REAPED.labels("run").inc()
            log.warning("run_requeued", run_id=str(job.run_id))
            await send_or_defer(self.c.queue, job)
        for job in resent:
            metrics.REAPED.labels("message").inc()
            log.warning("run_message_resent", run_id=str(job.run_id))
            await send_or_defer(self.c.queue, job)
        expired = await expire_due(self.c, now)
        return Reaped(len(requeued), len(resent), expired)
