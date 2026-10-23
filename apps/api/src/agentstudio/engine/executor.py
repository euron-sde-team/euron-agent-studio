"""The DAG executor.

Walks a plan scope by scope. A node is ready when every node feeding it has resolved; it
runs when at least one of its incoming edges fired, and is skipped otherwise, which is how
the branch a Condition did not take disappears (and how merges after a branch run once).
Ready nodes start at once, so independent branches run in parallel, bounded by a per-run
semaphore. Each node runs under its own timeout and retry policy.

A run can stop in four ways: it succeeds, a node fails it, it is cancelled (or times out),
or it waits for Human approvals. Waiting is not a suspended coroutine: the executor
returns, and the next execution of the same run rebuilds its state from the steps it
recorded (`ResumeState`). The same mechanism resumes runs after a worker crash.
"""

from __future__ import annotations

import asyncio
import itertools
import random
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

import orjson

from agentstudio.core.logging import get_logger
from agentstudio.engine import runtime
from agentstudio.engine.errors import NodeError, RunFailedError
from agentstudio.engine.graph import ApprovalConfig, LoopConfig
from agentstudio.engine.nodes import (
    HANDLERS,
    NodeContext,
    NodeResult,
    Prepared,
    prepare_approval,
    prepare_loop,
)
from agentstudio.engine.plan import Plan, PlanNode, Scope, config_of
from agentstudio.engine.ports import EngineServices
from agentstudio.engine.recorder import ApprovalRequest, RunRecorder, StepEnd, StepStart

ResultStatus = Literal["succeeded", "failed", "waiting", "cancelled"]
log = get_logger("agentstudio.engine")


@dataclass(frozen=True, slots=True)
class Limits:
    max_parallel_steps: int = 4
    run_timeout_s: float = 900.0
    max_loop_items: int = 200
    max_payload_bytes: int = 256 * 1024
    cancel_poll_s: float = 0.5


@dataclass(frozen=True, slots=True)
class RestoredStep:
    status: str
    output: Any
    handles: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Decision:
    approved: bool
    comment: str = ""
    decided_by: str | None = None
    decided_at: str | None = None


@dataclass(slots=True)
class ResumeState:
    """What earlier executions of this run already did (top-level steps only)."""

    steps: dict[str, RestoredStep] = field(default_factory=dict)
    decisions: dict[str, Decision] = field(default_factory=dict)
    next_seq: int = 1


@dataclass(slots=True)
class ExecutionResult:
    status: ResultStatus
    outputs: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None
    waiting_on: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _Frame:
    """Where a scope runs: its loop context and its iteration key."""

    loops: tuple[tuple[str, Any, int], ...] = ()
    iteration: str = ""
    outer_outputs: Mapping[str, Any] = field(default_factory=dict)
    resume: ResumeState | None = None


@dataclass(slots=True)
class _Outcome:
    status: str
    output: Any = None
    handles: tuple[str, ...] = ()
    waiting: bool = False


@dataclass(slots=True)
class _ScopeResult:
    outputs: dict[str, Any]
    resolved: dict[str, str]
    waiting: list[str]


class _Masker:
    """Replaces secret values with `[secret:NAME]` everywhere a value is recorded."""

    def __init__(self, secrets: Mapping[str, str]) -> None:
        # Longest first, so a secret that contains another is masked whole.
        self._pairs = sorted(
            ((value, f"[secret:{name}]") for name, value in secrets.items() if len(value) >= 4),
            key=lambda pair: -len(pair[0]),
        )

    def __call__(self, value: Any) -> Any:
        if not self._pairs:
            return value
        if isinstance(value, str):
            for secret, label in self._pairs:
                if secret in value:
                    value = value.replace(secret, label)
            return value
        if isinstance(value, dict):
            return {key: self(item) for key, item in value.items()}
        if isinstance(value, list | tuple):
            return [self(item) for item in value]
        return value


def cap_payload(value: Any, max_bytes: int) -> Any:
    """Keep recorded payloads bounded; oversized values become a truncated preview."""
    try:
        encoded = orjson.dumps(value, default=str)
    except TypeError:
        encoded = orjson.dumps(str(value))
    if len(encoded) <= max_bytes:
        return orjson.loads(encoded)
    preview = encoded[: max_bytes // 2].decode(errors="ignore")
    return {"_truncated": True, "_bytes": len(encoded), "preview": preview}


def _fallback_handle(node: PlanNode) -> tuple[str, ...]:
    """The handle a failed node fires when it is set to continue on error."""
    if node.type == "condition":
        return ("else",)
    if node.type == "loop":
        return ("done",)
    if node.type == "output":
        return ()
    return ("out",)


class Executor:
    def __init__(
        self,
        plan: Plan,
        services: EngineServices,
        recorder: RunRecorder,
        *,
        limits: Limits | None = None,
        secrets: Mapping[str, str] | None = None,
        now: Any = None,
    ) -> None:
        self.plan = plan
        self.services = services
        self.recorder = recorder
        self.limits = limits or Limits()
        self._secrets = dict(secrets or {})
        self._mask = _Masker(self._secrets)
        self._semaphore = asyncio.Semaphore(self.limits.max_parallel_steps)
        self._seq = itertools.count(1)
        self._inputs: dict[str, Any] = {}
        self._raw_inputs: dict[str, Any] = {}
        self._running: set[tuple[str, str]] = set()
        self._now = now or (lambda: datetime.now(UTC))

    # ----------------------------------------------------------------------------------
    # Entry point
    # ----------------------------------------------------------------------------------

    async def execute(
        self, inputs: Mapping[str, Any], resume: ResumeState | None = None
    ) -> ExecutionResult:
        resume = resume or ResumeState()
        self._raw_inputs = dict(inputs)
        self._seq = itertools.count(resume.next_seq)
        main = asyncio.create_task(self._run_scope(self.plan.top, _Frame(resume=resume)))
        watch = asyncio.create_task(self._watch_cancel())
        try:
            done, _ = await asyncio.wait(
                {main, watch},
                timeout=self.limits.run_timeout_s,
                return_when=asyncio.FIRST_COMPLETED,
            )
        except asyncio.CancelledError:
            # The worker is shutting down: stop everything; the run resumes elsewhere.
            await self._stop(main, watch)
            raise
        if main not in done:
            await self._stop(main, watch)
            if watch in done:
                return ExecutionResult("cancelled")
            return ExecutionResult(
                "failed",
                error={
                    "code": "run_timeout",
                    "message": (
                        f"The run took longer than {int(self.limits.run_timeout_s)} seconds."
                    ),
                },
            )
        watch.cancel()
        try:
            result = main.result()
        except RunFailedError as exc:
            return ExecutionResult("failed", error={**exc.error.as_dict(), "node_id": exc.node_id})
        if result.waiting:
            return ExecutionResult("waiting", waiting_on=result.waiting)
        outputs: dict[str, Any] = {}
        for node_id in self.plan.output_ids:
            if result.resolved.get(node_id) == "succeeded" and isinstance(
                result.outputs.get(node_id), dict
            ):
                outputs.update(result.outputs[node_id])
        return ExecutionResult("succeeded", outputs=outputs)

    async def _stop(self, *tasks: asyncio.Task[Any]) -> None:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _watch_cancel(self) -> None:
        while True:
            try:
                if await self.services.cancel.requested():
                    return
            except Exception:
                # A failing probe (Redis briefly unavailable) must not read as a cancellation.
                log.warning("cancel_probe_failed", exc_info=True)
            await asyncio.sleep(self.limits.cancel_poll_s)

    # ----------------------------------------------------------------------------------
    # Scopes
    # ----------------------------------------------------------------------------------

    async def _run_scope(self, scope: Scope, frame: _Frame) -> _ScopeResult:
        plan = self.plan
        outputs: dict[str, Any] = dict(frame.outer_outputs)
        resolved: dict[str, str] = {}
        fired: set[tuple[str, str]] = set()
        waiting: set[str] = set()
        if scope.owner is not None:
            fired.add((scope.owner, "body"))
        if frame.resume is not None and scope.owner is None:
            self._restore(scope, frame.resume, outputs, resolved, fired)

        running: dict[asyncio.Task[_Outcome], str] = {}
        try:
            while True:
                progressed = False
                started = set(running.values())
                for node_id in scope.order:
                    if node_id in resolved or node_id in waiting or node_id in started:
                        continue
                    edges = plan.incoming.get(node_id, [])
                    sources = [e.source for e in edges if e.source != scope.owner]
                    if any(source not in resolved for source in sources):
                        continue
                    entry = node_id == plan.start_id and scope.owner is None
                    if not entry and not any((e.source, e.source_handle) in fired for e in edges):
                        resolved[node_id] = "skipped"
                        outputs[node_id] = None
                        await self._record_skip(plan.nodes[node_id], frame.iteration)
                        progressed = True
                        continue
                    task = asyncio.create_task(self._run_node(plan.nodes[node_id], outputs, frame))
                    running[task] = node_id
                    started.add(node_id)
                    progressed = True
                if not running:
                    if progressed:
                        continue
                    break
                done, _ = await asyncio.wait(running, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    node_id = running.pop(task)
                    outcome = task.result()
                    if outcome.waiting:
                        waiting.add(node_id)
                        continue
                    resolved[node_id] = outcome.status
                    outputs[node_id] = outcome.output
                    if plan.nodes[node_id].type == "start" and scope.owner is None:
                        self._inputs = dict(outcome.output or {})
                    fired.update((node_id, handle) for handle in outcome.handles)
        except BaseException:
            for task in running:
                task.cancel()
            await asyncio.gather(*running, return_exceptions=True)
            raise
        return _ScopeResult(outputs, resolved, sorted(waiting))

    def _restore(
        self,
        scope: Scope,
        resume: ResumeState,
        outputs: dict[str, Any],
        resolved: dict[str, str],
        fired: set[tuple[str, str]],
    ) -> None:
        for node_id in scope.order:
            restored = resume.steps.get(node_id)
            if restored is None:
                continue
            resolved[node_id] = restored.status
            outputs[node_id] = restored.output
            fired.update((node_id, handle) for handle in restored.handles)
            if node_id == self.plan.start_id:
                self._inputs = dict(restored.output or {})

    # ----------------------------------------------------------------------------------
    # One node
    # ----------------------------------------------------------------------------------

    def _context(self, node: PlanNode, outputs: Mapping[str, Any], frame: _Frame) -> NodeContext:
        scope = runtime.build_scope(self._inputs, outputs, loops=frame.loops, secrets=self._secrets)

        async def emit(event: dict[str, Any]) -> None:
            await self.recorder.step_event(node.id, frame.iteration, self._record(event))

        return NodeContext(
            plan=self.plan,
            node=node,
            scope=scope,
            raw_inputs=self._raw_inputs,
            services=self.services,
            emit=emit,
        )

    def _record(self, value: Any) -> Any:
        return cap_payload(self._mask(value), self.limits.max_payload_bytes)

    async def _record_skip(self, node: PlanNode, iteration: str) -> None:
        seq = next(self._seq)
        await self.recorder.step_started(
            StepStart(node.id, node.type, node.label, iteration, seq, 1, None)
        )
        await self.recorder.step_finished(StepEnd(node.id, node.type, iteration, "skipped", 1))

    async def _run_node(
        self, node: PlanNode, outputs: Mapping[str, Any], frame: _Frame
    ) -> _Outcome:
        ctx = self._context(node, outputs, frame)
        seq = next(self._seq)
        prepared: Prepared | None = None
        failure: NodeError | None = None
        try:
            if node.type == "loop":
                prepared = prepare_loop(ctx, self.limits.max_loop_items)
            elif node.type == "approval":
                prepared = prepare_approval(ctx)
            else:
                prepared = HANDLERS[node.type].prepare(ctx)
        except NodeError as exc:
            failure = exc
        except runtime.ExpressionError as exc:
            failure = NodeError("invalid_expression", str(exc))

        record = self._record(prepared.record) if prepared is not None else None
        await self.recorder.step_started(
            StepStart(node.id, node.type, node.label, frame.iteration, seq, 1, record)
        )
        key = (node.id, frame.iteration)
        self._running.add(key)
        started = time.monotonic()
        attempt = 1
        try:
            if failure is None and prepared is not None:
                if node.type == "approval":
                    return await self._approval(node, prepared, frame, started)
                while True:
                    try:
                        async with asyncio.timeout(node.settings.timeout_s):
                            result = await self._invoke(node, ctx, prepared, outputs, frame)
                        return await self._succeed(node, frame, result, attempt, started)
                    except TimeoutError:
                        failure = NodeError(
                            "timeout",
                            f"The step did not finish within {node.settings.timeout_s:g} seconds.",
                            retryable=True,
                        )
                    except NodeError as exc:
                        failure = exc
                    except RunFailedError as exc:
                        if node.type != "loop":
                            raise
                        # A step inside the loop body failed: the loop step fails with it.
                        failure = NodeError(
                            "loop_item_failed",
                            f"A loop item failed at {exc.node_id!r}: {exc.error.message}",
                            details={"node_id": exc.node_id, **exc.error.as_dict()},
                        )
                    except Exception as exc:
                        failure = NodeError("internal_error", f"{type(exc).__name__}: {exc}")
                    if attempt > node.settings.retries or not failure.retryable:
                        break
                    delay = node.settings.retry_backoff_s * (2 ** (attempt - 1))
                    delay *= 1 + random.random() * 0.25
                    await self.recorder.step_event(
                        node.id,
                        frame.iteration,
                        self._record(
                            {
                                "type": "retry",
                                "attempt": attempt,
                                "error": failure.as_dict(),
                                "delay_s": round(delay, 2),
                            }
                        ),
                    )
                    await asyncio.sleep(delay)
                    attempt += 1
            if failure is None:
                failure = NodeError("internal_error", "The step could not be prepared.")
            return await self._fail(node, frame, failure, attempt, started)
        except asyncio.CancelledError:
            await asyncio.shield(
                self.recorder.step_finished(
                    StepEnd(
                        node.id,
                        node.type,
                        frame.iteration,
                        "cancelled",
                        attempt,
                        latency_ms=int((time.monotonic() - started) * 1000),
                    )
                )
            )
            raise
        finally:
            self._running.discard(key)

    async def _invoke(
        self,
        node: PlanNode,
        ctx: NodeContext,
        prepared: Prepared,
        outputs: Mapping[str, Any],
        frame: _Frame,
    ) -> NodeResult:
        if node.type == "loop":
            # A loop holds no slot of its own: its body steps take them, and holding one
            # while waiting for them could deadlock the run.
            return await self._loop(node, prepared, outputs, frame)
        async with self._semaphore:
            return await HANDLERS[node.type].run(ctx, prepared)

    async def _succeed(
        self, node: PlanNode, frame: _Frame, result: NodeResult, attempt: int, started: float
    ) -> _Outcome:
        usage = result.usage
        await self.recorder.step_finished(
            StepEnd(
                node.id,
                node.type,
                frame.iteration,
                "succeeded",
                attempt,
                output=self._record(result.output),
                handles=result.handles,
                model=usage.model if usage else None,
                prompt_tokens=usage.prompt_tokens if usage else 0,
                completion_tokens=usage.completion_tokens if usage else 0,
                cost_usd=usage.cost_usd if usage else Decimal(0),
                cost_simulated=usage.simulated if usage else False,
                cached=bool(usage and usage.calls and usage.cached),
                latency_ms=int((time.monotonic() - started) * 1000),
            )
        )
        return _Outcome("succeeded", result.output, result.handles)

    async def _fail(
        self, node: PlanNode, frame: _Frame, error: NodeError, attempt: int, started: float
    ) -> _Outcome:
        continued = node.settings.continue_on_error
        output = {"error": error.as_dict()} if continued else None
        await self.recorder.step_finished(
            StepEnd(
                node.id,
                node.type,
                frame.iteration,
                "failed",
                attempt,
                output=self._record(output) if output else None,
                error=self._record(error.as_dict()),
                handles=_fallback_handle(node) if continued else (),
                continued=continued,
                latency_ms=int((time.monotonic() - started) * 1000),
            )
        )
        if continued:
            return _Outcome("failed", output, _fallback_handle(node))
        raise RunFailedError(node.id, error)

    # ----------------------------------------------------------------------------------
    # Loops
    # ----------------------------------------------------------------------------------

    async def _loop(
        self, node: PlanNode, prepared: Prepared, outputs: Mapping[str, Any], frame: _Frame
    ) -> NodeResult:
        config = config_of(node, LoopConfig)
        items: list[Any] = prepared.values["items"]
        body = self.plan.bodies[node.id]
        gate = asyncio.Semaphore(config.concurrency)
        results: list[Any] = [None] * len(items)
        failed = 0
        terminals = self.plan.terminal_nodes(node.id)

        async def iteration(index: int, item: Any) -> None:
            nonlocal failed
            key = f"{frame.iteration}/{index}" if frame.iteration else str(index)
            inner = _Frame(
                loops=(*frame.loops, (node.id, item, index)),
                iteration=key,
                outer_outputs=outputs,
            )
            async with gate:
                try:
                    scope_result = await self._run_scope(body, inner)
                except RunFailedError as exc:
                    if not config.continue_on_item_error:
                        raise
                    failed += 1
                    results[index] = {"error": exc.error.as_dict(), "node_id": exc.node_id}
                    return
            results[index] = self._collect(config, terminals, scope_result, inner)

        tasks = [asyncio.create_task(iteration(index, item)) for index, item in enumerate(items)]
        try:
            await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        return NodeResult(
            {"results": results, "count": len(items), "failed": failed}, handles=("done",)
        )

    def _collect(
        self, config: LoopConfig, terminals: Sequence[str], result: _ScopeResult, frame: _Frame
    ) -> Any:
        if config.collect.strip():
            scope = runtime.build_scope(
                self._inputs, result.outputs, loops=frame.loops, secrets=self._secrets
            )
            try:
                return runtime.render_value(config.collect, scope)
            except runtime.ExpressionError as exc:
                raise NodeError("invalid_expression", str(exc)) from exc
        ran = [node_id for node_id in terminals if result.resolved.get(node_id) == "succeeded"]
        if len(ran) == 1:
            return result.outputs[ran[0]]
        return {node_id: result.outputs.get(node_id) for node_id in ran}

    # ----------------------------------------------------------------------------------
    # Human approval
    # ----------------------------------------------------------------------------------

    async def _approval(
        self, node: PlanNode, prepared: Prepared, frame: _Frame, started: float
    ) -> _Outcome:
        decision = frame.resume.decisions.get(node.id) if frame.resume else None
        if decision is not None:
            output = {
                "decision": "approved" if decision.approved else "rejected",
                "comment": decision.comment,
                "decided_by": decision.decided_by,
                "decided_at": decision.decided_at,
            }
            handle = "approved" if decision.approved else "rejected"
            return await self._succeed(node, frame, NodeResult(output, (handle,)), 1, started)
        config = config_of(node, ApprovalConfig)
        record = prepared.record or {}
        expires_at = (
            self._now() + timedelta(hours=config.expires_after_hours)
            if config.expires_after_hours
            else None
        )
        await self.recorder.approval_requested(
            ApprovalRequest(
                node_id=node.id,
                title=str(record.get("title", "Review required")),
                message=str(self._mask(record.get("message", ""))),
                context=self._record({"inputs": self._inputs}),
                expires_at=expires_at,
            )
        )
        return _Outcome("waiting", waiting=True)
