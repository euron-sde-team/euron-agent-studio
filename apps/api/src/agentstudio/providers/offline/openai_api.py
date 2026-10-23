"""The offline provider spoken over the OpenAI Chat Completions wire format.

`POST /api/v1/offline/v1/chat/completions` uses this, so anything that talks to OpenAI, an
exported flow script included, can run against the offline model with no key and no
network. The request is turned into exactly the `ChatRequest` the engine would build, which
is what makes an exported script's results identical to the engine's.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any

import orjson
from pydantic import BaseModel, ConfigDict, Field

from agentstudio.providers.base import ChatRequest, ChatResponse
from agentstudio.providers.offline.provider import OFFLINE_MODEL


class ChatCompletionRequest(BaseModel):
    """The subset of the OpenAI request the offline model uses; other fields are ignored."""

    model_config = ConfigDict(extra="ignore")

    model: str = OFFLINE_MODEL
    messages: list[dict[str, Any]] = Field(min_length=1, max_length=500)
    temperature: float = Field(default=0.2, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1, le=32_000)
    max_completion_tokens: int | None = Field(default=None, ge=1, le=32_000)
    tools: list[dict[str, Any]] | None = Field(default=None, max_length=64)
    response_format: dict[str, Any] | None = None

    def to_request(self) -> ChatRequest:
        return ChatRequest(
            model=OFFLINE_MODEL,
            messages=self.messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens or self.max_completion_tokens or 800,
            tools=self.tools or None,
            response_format=self.response_format,
        )


def completion_id(body: ChatCompletionRequest) -> str:
    digest = hashlib.sha256(
        orjson.dumps(body.model_dump(), option=orjson.OPT_SORT_KEYS)
    ).hexdigest()
    return f"chatcmpl-offline-{digest[:24]}"


def to_openai(body: ChatCompletionRequest, response: ChatResponse) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": response.content}
    if response.tool_calls:
        message["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": call.arguments},
            }
            for call in response.tool_calls
        ]
    return {
        "id": completion_id(body),
        "object": "chat.completion",
        "created": int(time.time()),
        "model": OFFLINE_MODEL,
        "choices": [{"index": 0, "message": message, "finish_reason": response.finish_reason}],
        "usage": {
            "prompt_tokens": response.prompt_tokens,
            "completion_tokens": response.completion_tokens,
            "total_tokens": response.prompt_tokens + response.completion_tokens,
        },
    }


MODELS_LIST = {
    "object": "list",
    "data": [{"id": OFFLINE_MODEL, "object": "model", "created": 0, "owned_by": "agentstudio"}],
}
