"""Markdown-aware chunking for knowledge documents.

Chunks follow the document's structure: a heading starts a new chunk and is remembered as
the chunk's heading path ("Billing > Refunds"), paragraphs are packed together up to a token
budget, and a paragraph longer than the budget is split at sentence boundaries. Searching
chunks of one topic each keeps results precise, and the heading path tells a reader (and a
model) where a passage came from.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from agentstudio.core.text import normalize, split_sentences
from agentstudio.providers.offline.tokens import count_tokens

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FRONT_MATTER = re.compile(r"\A---\n.*?\n---\n", re.S)


@dataclass(frozen=True, slots=True)
class Chunk:
    ordinal: int
    heading: str
    text: str
    token_count: int


def title_of(text: str, fallback: str) -> str:
    for line in text.splitlines():
        match = _HEADING.match(line.strip())
        if match and len(match.group(1)) == 1:
            return match.group(2).strip()[:300]
    return fallback[:300]


def _split_long(paragraph: str, budget: int) -> list[str]:
    pieces: list[str] = []
    current: list[str] = []
    size = 0
    for sentence in split_sentences(paragraph) or [paragraph]:
        tokens = count_tokens(sentence)
        if current and size + tokens > budget:
            pieces.append(" ".join(current))
            current, size = [], 0
        current.append(sentence)
        size += tokens
    if current:
        pieces.append(" ".join(current))
    return pieces


def chunk_document(text: str, *, title: str, max_tokens: int = 280) -> list[Chunk]:
    body = _FRONT_MATTER.sub("", normalize(text))
    chunks: list[Chunk] = []
    path: list[str] = []
    buffer: list[str] = []
    size = 0

    def heading() -> str:
        trimmed = path[1:] if path and path[0] == title else path
        return " > ".join(part for part in trimmed if part)

    def flush() -> None:
        nonlocal buffer, size
        text_block = "\n\n".join(buffer).strip()
        if text_block:
            chunks.append(Chunk(len(chunks), heading(), text_block, count_tokens(text_block)))
        buffer, size = [], 0

    paragraphs = re.split(r"\n\s*\n", body)
    for paragraph in paragraphs:
        lines = paragraph.strip().splitlines()
        if not lines:
            continue
        match = _HEADING.match(lines[0].strip())
        if match:
            flush()
            level = len(match.group(1))
            path[:] = [*path[: level - 1], *[""] * max(0, level - 1 - len(path))][: level - 1]
            path.append(match.group(2).strip())
            lines = lines[1:]
            if not lines:
                continue
        block = "\n".join(lines).strip()
        tokens = count_tokens(block)
        if tokens > max_tokens:
            flush()
            for piece in _split_long(block, max_tokens):
                buffer = [piece]
                flush()
            continue
        if buffer and size + tokens > max_tokens:
            flush()
        buffer.append(block)
        size += tokens
    flush()
    return chunks
