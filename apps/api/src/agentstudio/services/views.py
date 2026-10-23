"""Read models shared by the run, approval and dashboard services."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from agentstudio.models import Approval, Run, RunStep
from agentstudio.models.enums import RunTrigger
from agentstudio.repositories.api_keys import ApiKeyRepository
from agentstudio.repositories.users import UserRepository


@dataclass(frozen=True, slots=True)
class RunView:
    run: Run
    flow_name: str
    triggered_by: str | None


@dataclass(frozen=True, slots=True)
class RunDetailView:
    view: RunView
    graph: dict[str, Any]
    steps: list[RunStep]
    approvals: list[tuple[Approval, str | None]]


async def triggered_by(session: AsyncSession, runs: list[Run]) -> dict[uuid.UUID, str]:
    """Who started each run: a person, an API key or a webhook. Two queries for any page."""
    users = await UserRepository(session).names(
        {r.triggered_by_user_id for r in runs if r.triggered_by_user_id}
    )
    keys = await ApiKeyRepository(session).names(
        {r.triggered_by_api_key_id for r in runs if r.triggered_by_api_key_id}
    )
    names: dict[uuid.UUID, str] = {}
    for run in runs:
        if run.triggered_by_user_id and run.triggered_by_user_id in users:
            names[run.id] = users[run.triggered_by_user_id]
        elif run.triggered_by_api_key_id and run.triggered_by_api_key_id in keys:
            names[run.id] = f"API key {keys[run.triggered_by_api_key_id]}"
        elif run.trigger == RunTrigger.WEBHOOK:
            names[run.id] = "Webhook"
    return names
