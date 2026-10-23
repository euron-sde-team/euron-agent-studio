"""A deterministic token estimate close to what BPE tokenizers report for English.

Short words are one token, long words split roughly every five characters, digit runs every
three, and punctuation is a token each. It needs no vocabulary file, so it works offline and
gives the same count on every machine, which is all usage and simulated cost need.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable
from typing import Any

_PIECE = re.compile(r"[A-Za-z]+|\d+|[^\sA-Za-z\d]")
_MESSAGE_OVERHEAD = 4


def count_tokens(text: str) -> int:
    total = 0
    for piece in _PIECE.findall(text):
        if piece[0].isalpha():
            total += 1 if len(piece) <= 6 else math.ceil(len(piece) / 5)
        elif piece[0].isdigit():
            total += math.ceil(len(piece) / 3)
        else:
            total += 1
    return total


def count_request(messages: Iterable[dict[str, Any]], tools: list[dict[str, Any]] | None) -> int:
    total = 3
    for message in messages:
        total += _MESSAGE_OVERHEAD
        content = message.get("content")
        if isinstance(content, str):
            total += count_tokens(content)
        for call in message.get("tool_calls") or []:
            function = call.get("function", {})
            total += count_tokens(function.get("name", "")) + count_tokens(
                str(function.get("arguments", ""))
            )
    if tools:
        total += count_tokens(json.dumps(tools))
    return total
