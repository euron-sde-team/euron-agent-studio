"""Reading a chat request the way the offline model needs it.

Prompts written for real models usually look like this:

    Classify this support ticket.

    Subject: Charged twice for the March invoice
    Customer: dana@globex.example

    Ticket:
    Hi team, I was charged twice ...

The offline model splits that into the instruction (the request, plus the system prompt),
inline fields (`Subject`, `Customer`), and sections (`Ticket`, introduced by a label alone on
its line, running until the next such label). The main content is the section most likely
to hold the material to work on; reference material (sources, articles, findings) is kept
apart as context.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from agentstudio.core.text import normalize, split_sentences

# A label is at most four words ("Help center articles"), so a long instruction that happens
# to contain a colon ("Classify it as one of: a, b") is not mistaken for one.
_LABEL = r"([A-Za-z][A-Za-z0-9/&()'_.-]*(?: [A-Za-z0-9/&()'_.-]+){0,3})"
_SECTION = re.compile(rf"^\s*{_LABEL}:\s*$")
_FIELD = re.compile(rf"^\s*{_LABEL}:\s+(\S.*)$")
_CONTENT_NAMES = (
    "ticket",
    "message",
    "email",
    "text",
    "notes",
    "transcript",
    "invoice",
    "document",
    "content",
    "input",
    "body",
    "request",
    "conversation",
)
_CONTEXT_NAMES = (
    "sources",
    "source",
    "context",
    "articles",
    "help center articles",
    "knowledge",
    "findings",
    "results",
    "references",
    "documentation",
    "policy",
    "policies",
)
# Labels that structure a prompt. Inside a section, only these start a new one, so a
# "Bill To:" line inside an invoice stays part of the invoice.
_PROMPT_SECTIONS = (
    *_CONTENT_NAMES,
    *_CONTEXT_NAMES,
    "instructions",
    "task",
    "question",
    "questions",
    "topic",
    "examples",
    "format",
    "rules",
    "guidelines",
    "background",
    "data",
    "details",
)
_GREETING = re.compile(
    r"^(hi|hello|hey|dear|good (morning|afternoon|evening))\b[^.!?\n]{0,40}[,!.]?$", re.I
)
# "Ava: we agreed..." in a transcript: the speaker is not part of the sentence.
_SPEAKER_LABEL = re.compile(
    r"^(?:\[[^\]]{1,20}\]\s*)?[A-Z][a-zA-Z.'-]+(?: [A-Z][a-zA-Z.'-]+)?:\s+(?=\S)"
)
_LEADING_GREETING = re.compile(r"^(?:hi|hello|hey|dear)\b[^,.!?\n]{0,30}[,!]\s+", re.I)
_SIGNOFF = re.compile(
    r"^(thanks|thank you|many thanks|regards|best|best regards|kind regards|cheers|"
    r"sincerely)\b[ ,!.]*$",
    re.I,
)


@dataclass(slots=True)
class ToolResult:
    call_id: str
    name: str
    arguments: dict[str, Any]
    content: Any


@dataclass(slots=True)
class Prompt:
    system: str
    user: str
    instruction: str
    sections: dict[str, str]
    fields: dict[str, str]
    tool_results: list[ToolResult] = field(default_factory=list)
    calls_made: list[tuple[str, str]] = field(default_factory=list)

    @property
    def request(self) -> str:
        """The system prompt and the instruction, lowercased: what the task detectors read."""
        return f"{self.system}\n{self.instruction}".lower()

    @property
    def content(self) -> str:
        for name in _CONTENT_NAMES:
            for label, text in self.sections.items():
                if label == name or label.endswith(" " + name):
                    return text
        candidates = [text for label, text in self.sections.items() if label not in _CONTEXT_NAMES]
        if candidates:
            return max(candidates, key=len)
        return self.user

    @property
    def context(self) -> str:
        found = [
            text
            for label, text in self.sections.items()
            if label in _CONTEXT_NAMES or any(label.endswith(" " + n) for n in _CONTEXT_NAMES)
        ]
        return "\n\n".join(found)

    def field(self, *names: str) -> str | None:
        for name in names:
            value = self.fields.get(name)
            if value:
                return value
        return None


def message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # OpenAI content parts
        return "\n".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
    return str(content)


def parse_blocks(text: str) -> tuple[str, dict[str, str], dict[str, str]]:
    """Split text into (instruction, sections, fields)."""
    sections: dict[str, str] = {}
    fields: dict[str, str] = {}
    instruction_lines: list[str] = []
    current: str | None = None
    buffer: list[str] = []
    seen_structure = False

    def flush() -> None:
        if current is not None:
            body = "\n".join(buffer).strip()
            if body and current not in sections:
                sections[current] = body

    for line in text.splitlines():
        section = _SECTION.match(line)
        if section and _starts_section(section.group(1), inside=current is not None):
            flush()
            current = section.group(1).strip().lower()
            buffer = []
            seen_structure = True
            continue
        inline = _FIELD.match(line)
        if inline and current is None:
            label = inline.group(1).strip().lower()
            fields.setdefault(label, inline.group(2).strip())
            seen_structure = True
            continue
        if inline:
            fields.setdefault(inline.group(1).strip().lower(), inline.group(2).strip())
        if current is not None:
            buffer.append(line)
        elif not seen_structure:
            instruction_lines.append(line)
    flush()
    return "\n".join(instruction_lines).strip(), sections, fields


def _starts_section(label: str, *, inside: bool) -> bool:
    if not inside:
        return True
    name = label.strip().lower()
    return any(name == known or name.endswith(" " + known) for known in _PROMPT_SECTIONS)


def parse_request(messages: list[dict[str, Any]]) -> Prompt:
    system = "\n".join(message_text(m) for m in messages if m.get("role") == "system")
    users = [m for m in messages if m.get("role") == "user"]
    user = message_text(users[-1]) if users else ""
    instruction, sections, fields = parse_blocks(user)
    if not instruction and not sections and not fields:
        instruction = user
    prompt = Prompt(system, user, instruction, sections, fields)

    calls: dict[str, tuple[str, dict[str, Any]]] = {}
    for message in messages:
        if message.get("role") == "assistant":
            for call in message.get("tool_calls") or []:
                function = call.get("function", {})
                raw = function.get("arguments") or "{}"
                try:
                    args = json.loads(raw) if isinstance(raw, str) else dict(raw)
                except ValueError:
                    args = {}
                calls[call.get("id", "")] = (function.get("name", ""), args)
                prompt.calls_made.append(
                    (function.get("name", ""), json.dumps(args, sort_keys=True))
                )
        elif message.get("role") == "tool":
            call_id = message.get("tool_call_id", "")
            name, args = calls.get(call_id, ("", {}))
            raw_content = message_text(message)
            try:
                content: Any = json.loads(raw_content)
            except ValueError:
                content = raw_content
            prompt.tool_results.append(ToolResult(call_id, name, args, content))
    return prompt


_STRUCTURED_LINE = re.compile(
    r"^\s*(?:[-*#|>]|\d+[.)]\s|\[\d+\]|[A-Z][a-zA-Z.'-]+(?: [A-Z][a-zA-Z.'-]+)?:\s)"
)


def unwrap(text: str) -> str:
    """Join hard-wrapped prose lines (Markdown paragraphs) back into single lines.

    Lists, headings, tables, speaker lines and short lines (signatures, addresses) keep
    their line breaks; a long line followed by more prose is a wrapped sentence.
    """
    lines = normalize(text).split("\n")
    merged: list[str] = []
    for line in lines:
        stripped = line.strip()
        if (
            merged
            and stripped
            and merged[-1]
            and len(merged[-1].split()) >= 8
            and not merged[-1].endswith(":")
            and not _STRUCTURED_LINE.match(stripped)
            and not _STRUCTURED_LINE.match(merged[-1])
        ):
            merged[-1] = f"{merged[-1]} {stripped}"
        else:
            merged.append(stripped)
    return "\n".join(merged)


def sentences(text: str) -> list[str]:
    """Sentences of a text, line breaks respected, greetings and sign-offs dropped."""
    found: list[str] = []
    lines = [line.strip() for line in unwrap(text).split("\n")]
    for index, line in enumerate(lines):
        if not line or _GREETING.match(line) or _SIGNOFF.match(line):
            continue
        # A short line right after a sign-off is a signature (a name or a company).
        if index > 0 and _SIGNOFF.match(lines[index - 1] or "") and len(line.split()) <= 4:
            continue
        line = _LEADING_GREETING.sub("", _SPEAKER_LABEL.sub("", line))
        for sentence in split_sentences(line):
            cleaned = sentence.strip(" -*\N{BULLET}")
            if cleaned:
                found.append(cleaned[0].upper() + cleaned[1:])
    return found
