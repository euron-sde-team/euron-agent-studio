"""The offline model over the OpenAI Chat Completions format, for exported scripts and tools."""

from __future__ import annotations

from typing import Any

import anyio
from fastapi import APIRouter, Depends

from agentstudio.api.deps import PrincipalDep, rate_limit
from agentstudio.providers.offline import respond
from agentstudio.providers.offline.openai_api import MODELS_LIST, ChatCompletionRequest, to_openai

router = APIRouter(prefix="/api/v1/offline/v1", tags=["offline model"])


@router.post(
    "/chat/completions",
    summary="Chat completions from the deterministic offline model",
    dependencies=[Depends(rate_limit("offline", "rate_limit_offline"))],
)
async def chat_completions(body: ChatCompletionRequest, principal: PrincipalDep) -> dict[str, Any]:
    response = await anyio.to_thread.run_sync(respond, body.to_request())
    return to_openai(body, response)


@router.get("/models", summary="The offline model")
async def models(principal: PrincipalDep) -> dict[str, Any]:
    return MODELS_LIST
