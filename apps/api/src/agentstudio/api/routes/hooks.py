"""Inbound webhooks: a signed POST starts a run of the flow's published version."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Path, Request, Response, status

from agentstudio.api.deps import ContainerDep, SessionDep
from agentstudio.core.crypto import SIGNATURE_HEADER
from agentstudio.core.errors import PayloadTooLargeError, RateLimitedError
from agentstudio.schemas.common import ApiModel
from agentstudio.services.webhooks import WebhookService

router = APIRouter(prefix="/api/v1/hooks", tags=["webhooks"])
MAX_BODY_BYTES = 256 * 1024


class HookAccepted(ApiModel):
    run_id: str
    status: str


@router.post(
    "/{hook_id}",
    summary="Start a run from a signed webhook",
    description=(
        f"Sign the raw body: `{SIGNATURE_HEADER}: t=<unix seconds>,v1=<hex HMAC-SHA256 of "
        '"<t>.<body>" with the webhook secret>`. Deliveries older than five minutes and repeated '
        "signatures are refused. The JSON body becomes the run's inputs."
    ),
    status_code=status.HTTP_202_ACCEPTED,
)
async def deliver(
    hook_id: Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{8,32}$")],
    request: Request,
    response: Response,
    container: ContainerDep,
    session: SessionDep,
    signature: Annotated[str | None, Header(alias=SIGNATURE_HEADER, max_length=512)] = None,
) -> HookAccepted:
    limited = await container.limiter.hit(f"hook:{hook_id}", container.settings.rate_limit_webhooks)
    response.headers.update(limited.headers())
    if not limited.allowed:
        raise RateLimitedError(headers={"retry-after": str(limited.reset_s)})
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise PayloadTooLargeError("Webhook bodies are limited to 256 KB.")
    run = await WebhookService(container, session).deliver(hook_id, signature, body)
    return HookAccepted(run_id=str(run.id), status=run.status)
