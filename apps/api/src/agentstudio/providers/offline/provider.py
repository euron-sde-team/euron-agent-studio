"""The offline model: deterministic answers without a network or an API key.

It reads the request (`prompt.py`), decides what is being asked, and answers with the
matching technique: tool calls (`tools.py`), a filled JSON schema (`structured.py`), a label
(`classify.py`), a summary or action items (`summarize.py`), or templated writing
(`draft.py`). The same request always gets the same response, which is what makes runs,
tests, demos and exported scripts reproducible.
"""

from __future__ import annotations

import asyncio
import json
import re

from agentstudio.providers.base import ChatRequest, ChatResponse
from agentstudio.providers.offline import draft, structured, tools
from agentstudio.providers.offline.classify import candidate_labels, classify
from agentstudio.providers.offline.prompt import Prompt, parse_request
from agentstudio.providers.offline.summarize import one_sentence, summary
from agentstudio.providers.offline.tokens import count_request, count_tokens

OFFLINE_MODEL = "offline"

_COUNT_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7}
_BULLETS = re.compile(
    r"\b(\d|one|two|three|four|five|six|seven)\s+(?:short\s+)?"
    r"(?:bullet|bullets|points|key points|sentences)\b"
)


def _wants(prompt: Prompt, *patterns: str) -> bool:
    return any(re.search(pattern, prompt.request) for pattern in patterns)


def _count(prompt: Prompt, default: int) -> int:
    match = _BULLETS.search(prompt.request)
    if not match:
        return default
    raw = match.group(1)
    return _COUNT_WORDS.get(raw) or int(raw)


def write(prompt: Prompt) -> str:
    """Free-text answers, by what the instruction asks for."""
    if prompt.tool_results:
        return tools.final_answer(prompt)
    if _wants(prompt, r"\b(classify|categori[sz]e|label|which category)\b"):
        labels = candidate_labels(prompt.request) or candidate_labels(prompt.user)
        if labels:
            return classify(prompt.content, labels)
    if _wants(prompt, r"\baction items?\b", r"\bnext steps\b", r"\bto-?dos?\b"):
        return draft.action_item_lines(prompt.content)
    if _wants(prompt, r"\b(research )?brief\b", r"\breport\b") and (
        prompt.context or prompt.content
    ):
        return draft.brief(prompt)
    if _wants(prompt, r"\bsummar", r"\btl;?dr\b", r"\bkey points\b", r"\brecap\b"):
        if _wants(prompt, r"\bbullet", r"\bpoints\b", r"\blist\b"):
            return draft.bullet_summary(prompt.content, _count(prompt, 3))
        return summary(prompt.content, count=_count(prompt, 2))
    if _wants(prompt, r"\b(reply|respond|response)\b") and _wants(
        prompt, r"\b(ticket|customer|support|complaint)\b"
    ):
        return draft.support_reply(prompt)
    if _wants(prompt, r"\b(email|e-mail|outreach|follow-up email|message to)\b"):
        return draft.email(prompt, [])
    if prompt.context and _wants(prompt, r"\b(answer|question|explain|according)\b"):
        return draft.answer(draft.question_of(prompt), prompt.context)
    if prompt.context:
        return draft.answer(draft.question_of(prompt), prompt.context)
    if _wants(prompt, r"\b(draft|write|compose)\b"):
        return draft.email(prompt, [])
    return (
        one_sentence(prompt.content) if prompt.content else "I need more detail to help with that."
    )


def respond(request: ChatRequest) -> ChatResponse:
    prompt = parse_request(request.messages)
    prompt_tokens = count_request(request.messages, request.tools)
    if request.tools:
        calls = tools.plan(prompt, request.tools)
        if calls:
            completion = sum(count_tokens(c.name) + count_tokens(c.arguments) for c in calls)
            return ChatResponse(
                content=None,
                tool_calls=calls,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion + 3 * len(calls),
                finish_reason="tool_calls",
            )
    schema = structured.schema_of(request.response_format)
    if schema is not None:
        content = json.dumps(structured.fill(schema, prompt), ensure_ascii=False, indent=2)
    else:
        content = write(prompt)
    completion_tokens = min(count_tokens(content), max(1, request.max_tokens))
    finish = "length" if count_tokens(content) > request.max_tokens else "stop"
    return ChatResponse(
        content=content,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        finish_reason=finish,
    )


class OfflineProvider:
    """The built-in provider. `delay_ms_per_100_tokens` paces output for live demos."""

    name = "offline"

    def __init__(self, *, delay_ms_per_100_tokens: int = 0) -> None:
        self.delay_ms_per_100_tokens = delay_ms_per_100_tokens

    async def complete(self, request: ChatRequest) -> ChatResponse:
        # Heuristics over long inputs are CPU work; keep them off the event loop.
        response = await asyncio.to_thread(respond, request)
        if self.delay_ms_per_100_tokens:
            await asyncio.sleep(
                response.completion_tokens / 100 * self.delay_ms_per_100_tokens / 1000
            )
        return response

    async def aclose(self) -> None:
        return None
