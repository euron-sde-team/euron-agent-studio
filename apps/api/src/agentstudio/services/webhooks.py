"""Signed webhooks: verify, refuse replays, and start a run of the published version."""

from __future__ import annotations

import hashlib
import time
from typing import Any

import orjson
from sqlalchemy.ext.asyncio import AsyncSession

from agentstudio.core import metrics
from agentstudio.core.crypto import DecryptionError, verify_webhook, webhook_context
from agentstudio.core.errors import AppError, ConflictError, NotFoundError, UnprocessableError
from agentstudio.models import Run
from agentstudio.models.enums import RunTrigger
from agentstudio.repositories.flows import FlowRepository
from agentstudio.repositories.workspaces import WorkspaceRepository
from agentstudio.services.container import Container
from agentstudio.services.runs import RunService


class WebhookService:
    def __init__(self, container: Container, session: AsyncSession) -> None:
        self.c = container
        self.session = session

    async def deliver(self, hook_id: str, signature: str | None, body: bytes) -> Run:
        try:
            return await self._deliver(hook_id, signature, body)
        except AppError as exc:
            metrics.WEBHOOKS.labels(exc.code).inc()
            raise

    async def _deliver(self, hook_id: str, signature: str | None, body: bytes) -> Run:
        flow = await FlowRepository(self.session).by_webhook(hook_id)
        # One answer for unknown, disabled and secretless hooks: nothing to probe.
        if flow is None or not flow.webhook_enabled or flow.webhook_secret is None:
            raise NotFoundError("Webhook not found.")
        try:
            secret = self.c.cipher.decrypt(flow.webhook_secret, context=webhook_context(flow.id))
        except DecryptionError as exc:
            raise NotFoundError("Webhook not found.") from exc
        tolerance = self.c.settings.webhook_tolerance_s
        verify_webhook(secret, signature, body, now=int(time.time()), tolerance_s=tolerance)
        # A verified signature is unique to this delivery: seeing it twice means a replay.
        seen = "hook:seen:" + hashlib.sha256((signature or "").encode()).hexdigest()
        if not await self.c.redis.set(seen, b"1", ex=tolerance * 2, nx=True):
            raise ConflictError("This delivery was already received.", code="replayed")
        try:
            payload: Any = orjson.loads(body) if body.strip() else {}
        except orjson.JSONDecodeError as exc:
            raise UnprocessableError("The body is not JSON.", code="invalid_json") from exc
        inputs = payload if isinstance(payload, dict) else {"payload": payload}
        workspace = await WorkspaceRepository(self.session).get(flow.workspace_id)
        if workspace is None:
            raise NotFoundError("Webhook not found.")
        run = await RunService(self.c, self.session).start(
            workspace, None, flow.id, inputs, "published", trigger=RunTrigger.WEBHOOK
        )
        metrics.WEBHOOKS.labels("accepted").inc()
        return run
