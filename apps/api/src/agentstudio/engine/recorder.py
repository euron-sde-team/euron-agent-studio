"""How the executor reports what happens, step by step.

The run service implements `RunRecorder` (Postgres rows plus Redis stream events); tests use
`MemoryRecorder`. Everything handed to a recorder is already masked and size-capped.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class StepStart:
    node_id: str
    node_type: str
    label: str
    iteration: str
    seq: int
    attempt: int
    input: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class StepEnd:
    node_id: str
    node_type: str
    iteration: str
    status: str
    attempt: int
    output: Any = None
    error: dict[str, Any] | None = None
    handles: tuple[str, ...] = ()
    model: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: Decimal = Decimal(0)
    cost_simulated: bool = False
    cached: bool = False
    continued: bool = False
    latency_ms: int = 0


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    node_id: str
    title: str
    message: str
    context: dict[str, Any]
    expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class ApprovalTicket:
    approval_id: uuid.UUID


class RunRecorder(Protocol):
    async def step_started(self, step: StepStart) -> None: ...

    async def step_event(self, node_id: str, iteration: str, event: dict[str, Any]) -> None: ...

    async def step_finished(self, step: StepEnd) -> None: ...

    async def approval_requested(self, request: ApprovalRequest) -> ApprovalTicket: ...


@dataclass(slots=True)
class MemoryRecorder:
    """Keeps everything in lists; used by unit tests and by in-process previews."""

    started: list[StepStart] = field(default_factory=list)
    events: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)
    finished: list[StepEnd] = field(default_factory=list)
    approvals: list[ApprovalRequest] = field(default_factory=list)

    async def step_started(self, step: StepStart) -> None:
        self.started.append(step)

    async def step_event(self, node_id: str, iteration: str, event: dict[str, Any]) -> None:
        self.events.append((node_id, iteration, event))

    async def step_finished(self, step: StepEnd) -> None:
        self.finished.append(step)

    async def approval_requested(self, request: ApprovalRequest) -> ApprovalTicket:
        self.approvals.append(request)
        return ApprovalTicket(uuid.uuid5(uuid.NAMESPACE_URL, f"approval:{request.node_id}"))

    def status_of(self, node_id: str, iteration: str = "") -> str | None:
        for step in reversed(self.finished):
            if step.node_id == node_id and step.iteration == iteration:
                return step.status
        return None

    def output_of(self, node_id: str, iteration: str = "") -> Any:
        for step in reversed(self.finished):
            if step.node_id == node_id and step.iteration == iteration:
                return step.output
        return None
