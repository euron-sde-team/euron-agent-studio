"""Rule-based tool use: which tools to call, with what arguments, and the answer after.

Each round, every offered tool is considered once. A tool is called when its required
arguments can be filled from the conversation (a domain from an email address, an arithmetic
expression, a search query) and it has not been called with the same arguments before. A
calculator that needs numbers from another tool's result waits for the next round: that is
how a two-step "look up the price, then compute the total" plan emerges. When no tool is
left to call, the model answers using every result it has.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from agentstudio.core.text import content_terms, truncate
from agentstudio.providers.base import ToolCall
from agentstudio.providers.offline import extract
from agentstudio.providers.offline.draft import answer, email, question_of, relevant
from agentstudio.providers.offline.prompt import Prompt, ToolResult

_EXPRESSION = re.compile(r"(?<![\w.])(\(?\s*-?\d[\d.]*(?:\s*[-+*/x%]\s*\(?\s*-?\d[\d.]*\s*\)?)+)")
_PRICE = re.compile(
    r"(?:(?P<sym>[$\N{EURO SIGN}\N{POUND SIGN}])\s?(?P<amount>\d[\d,]*(?:\.\d+)?)"
    r"|(?P<amount2>\d[\d,]*(?:\.\d+)?)\s?(?P<code>USD|EUR|GBP))"
    r"\s*(?:per|/|a)\s*(?P<unit>seat|user|licen[cs]e|agent|member)"
    r"(?:\s*(?:per|/|a)\s*(?P<period>month|mo|year|yr|annum))?",
    re.I,
)
_RANGE = re.compile(r"\b(\d[\d,]*)\s*(?:to|-)\s*(\d[\d,]*)\s+(?:seats|users)\b", re.I)
_ABOVE = re.compile(
    r"\b(?:more than|over|above|from)\s+(\d[\d,]*)\s+(?:seats|users)\b"
    r"|\b(\d[\d,]*)\+\s*(?:seats|users)\b",
    re.I,
)
_UP_TO = re.compile(r"\b(?:up to|fewer than|under)\s+(\d[\d,]*)\s+(?:seats|users)\b", re.I)
_SEARCH_OBJECT = re.compile(
    r"\b(?:search|look up|lookup|find|check)\b(?:\s+(?:the|our))?(?:\s+[\w-]+){0,3}?"
    r"\s+(?:for|about|on)\s+([^.\n;]{3,120})",
    re.I,
)
_WANTS_EMAIL = re.compile(
    r"\b(email|e-mail|outreach|message to|reply|respond|write to|draft)\b", re.I
)
_WANTS_MATH = re.compile(
    r"\b(calculate|compute|total|price|pricing|cost|quote|how much|annual|per year|yearly|sum)\b",
    re.I,
)
_ANNUAL = re.compile(r"\b(annual|annually|per year|yearly|a year|12 months)\b", re.I)


def _kind(function: Mapping[str, Any]) -> str:
    properties = (function.get("parameters") or {}).get("properties") or {}
    names = {name.lower() for name in properties}
    if "expression" in names:
        return "calculator"
    if names & {"query", "question", "q", "search", "keywords"}:
        return "search"
    if "data" in names and len(names) == 1:
        return "transform"
    return "lookup"


def _task_text(prompt: Prompt) -> str:
    return f"{prompt.user}\n{prompt.system}"


_NEXT_CLAUSE = re.compile(
    r"\s+(?:and|then)\s+(?=(?:calculate|compute|then|write|draft|use|send|summari[sz]e|estimate|"
    r"answer|reply|include|quote)\b)",
    re.I,
)


def _search_query(prompt: Prompt) -> str:
    match = _SEARCH_OBJECT.search(prompt.user)
    if match:
        return _NEXT_CLAUSE.split(match.group(1))[0].strip(" ,")
    question = question_of(prompt)
    return truncate(question.strip(), 200)


def _seats(prompt: Prompt) -> int | None:
    # Seats, users or licences: a company's headcount is not what gets priced.
    return extract.quantity(prompt.user, ["seats"])


def _unit_price(
    results: list[ToolResult], seats: int | None, task: str
) -> tuple[float, str | None, str] | None:
    """The per-seat price in the tool results that fits the requested seat count.

    Returns the amount, its billing period, and the sentence it came from.
    """
    candidates: list[tuple[int, int, float, str | None, str]] = []
    order = 0
    for result in results:
        text = _result_text(result.content)
        for line in re.split(r"(?<=[.!?])\s+|\n", text):
            for match in _PRICE.finditer(line):
                raw = match.group("amount") or match.group("amount2") or ""
                amount = extract.parse_number(raw)
                if amount is None:
                    continue
                fit = _fits(line, seats)
                overlap = len(set(content_terms(line)) & set(content_terms(task)))
                order -= 1
                candidates.append(
                    (fit * 100 + overlap, order, float(amount), match.group("period"), line.strip())
                )
    if not candidates:
        return None
    _, _, amount, period, sentence = max(candidates, key=lambda item: (item[0], item[1]))
    return amount, period, sentence


def _fits(line: str, seats: int | None) -> int:
    if seats is None:
        return 0
    for low, high in _RANGE.findall(line):
        if int(low.replace(",", "")) <= seats <= int(high.replace(",", "")):
            return 2
    for groups in _ABOVE.findall(line):
        bound = next((g for g in groups if g), "")
        if bound and seats > int(bound.replace(",", "")):
            return 2
    for bound in _UP_TO.findall(line):
        if seats <= int(bound.replace(",", "")):
            return 1
    return 0


def _expression(prompt: Prompt) -> str | None:
    task = prompt.user
    explicit = _EXPRESSION.search(task)
    if explicit and re.search(r"[-+*/x%]", explicit.group(1)):
        return explicit.group(1).replace("x", "*").strip()
    if not _WANTS_MATH.search(task):
        return None
    seats = _seats(prompt)
    price = _unit_price(prompt.tool_results, seats, task)
    if seats is None or price is None:
        return None
    amount, period, _ = price
    months = 12 if _ANNUAL.search(task) and (period or "month").lower().startswith("mo") else 1
    expression = f"{seats} * {amount:g}"
    return f"{expression} * {months}" if months != 1 else expression


def _lookup_args(
    properties: Mapping[str, Any], required: list[str], prompt: Prompt
) -> dict[str, Any] | None:
    task = _task_text(prompt)
    args: dict[str, Any] = {}
    for name in properties:
        lowered = name.lower()
        value: Any = None
        if "domain" in lowered:
            value = extract.domain_of(task)
        elif "email" in lowered:
            found = extract.emails(task)
            value = found[0] if found else None
        elif lowered in {"company", "company_name", "organization", "account"}:
            value = extract.company_name(task, prompt.fields)
        elif lowered in {"name", "person", "contact"}:
            value = extract.person_name(task, prompt.fields)
        elif "invoice" in lowered:
            value = extract.invoice_number(task, prompt.fields)
        elif lowered.endswith("id") or lowered in {"number", "reference"}:
            match = re.search(r"\b([A-Z]{2,5}-\d{2,})\b", task)
            value = match.group(1) if match else None
        elif lowered in {"city", "location", "region", "country"}:
            value = extract.lookup_field(prompt.fields, lowered)
        else:
            value = extract.lookup_field(prompt.fields, lowered)
        if value is not None:
            args[name] = value
    if any(name not in args for name in required):
        return None
    return args


def plan(prompt: Prompt, tools: list[dict[str, Any]]) -> list[ToolCall]:
    """The tool calls to make this round (empty when it is time to answer)."""
    done = set(prompt.calls_made)
    called_names = {result.name for result in prompt.tool_results}
    calls: list[ToolCall] = []
    for tool in tools:
        function = tool.get("function") or {}
        name = str(function.get("name", ""))
        parameters = function.get("parameters") or {}
        properties = parameters.get("properties") or {}
        required = list(parameters.get("required") or [])
        kind = _kind(function)
        args: dict[str, Any] | None
        if kind == "calculator":
            expression = _expression(prompt)
            args = {"expression": expression} if expression else None
        elif kind == "search":
            if name in called_names:
                continue
            key = next(
                k
                for k in properties
                if k.lower() in {"query", "question", "q", "search", "keywords"}
            )
            args = {key: _search_query(prompt)}
        elif kind == "lookup":
            if name in called_names:
                continue
            args = _lookup_args(properties, required, prompt)
        else:
            args = None
        if args is None:
            continue
        signature = (name, json.dumps(args, sort_keys=True))
        if signature in done:
            continue
        calls.append(
            ToolCall(
                id=f"call_{len(prompt.calls_made) + len(calls) + 1}",
                name=name,
                arguments=json.dumps(args),
            )
        )
    return calls[:4]


# --------------------------------------------------------------------------------------
# The answer after tools
# --------------------------------------------------------------------------------------


def _result_text(content: Any) -> str:
    if isinstance(content, dict):
        if isinstance(content.get("context"), str):
            return str(content["context"])
        if "json" in content:
            return json.dumps(content["json"], ensure_ascii=False)
        return json.dumps(content, ensure_ascii=False)
    return str(content)


def _lookup_facts(content: Any) -> list[str]:
    data = content.get("json") if isinstance(content, dict) and "json" in content else content
    if not isinstance(data, dict):
        return []
    facts = []
    for key, value in data.items():
        if (
            isinstance(value, str | int | float)
            and not isinstance(value, bool)
            and len(str(value)) <= 80
        ):
            facts.append(f"{key.replace('_', ' ')}: {value}")
    return facts[:6]


def _facts_for_email(prompt: Prompt, knowledge: str, seats: int | None) -> list[str]:
    """The source sentences behind the offer: the priced plan and what it includes."""
    if not knowledge:
        return []
    priced = _unit_price(prompt.tool_results, seats, prompt.user)
    if priced is not None and _WANTS_MATH.search(prompt.user):
        sentence = priced[2]
        following = _sentence_after(knowledge, sentence)
        return [sentence, following] if following else [sentence]
    return [s for _, s in relevant(_search_query(prompt), knowledge, 2)]


def _sentence_after(text: str, sentence: str) -> str | None:
    parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n", text) if part.strip()]
    for index, part in enumerate(parts[:-1]):
        following = parts[index + 1]
        if part == sentence and not following.startswith("["):
            return following
    return None


def _money(amount: float, symbol: str = "$") -> str:
    return f"{symbol}{amount:,.0f}" if float(amount).is_integer() else f"{symbol}{amount:,.2f}"


def final_answer(prompt: Prompt) -> str:
    knowledge = "\n\n".join(
        result.content["context"]
        for result in prompt.tool_results
        if isinstance(result.content, dict) and isinstance(result.content.get("context"), str)
    )
    totals = [
        result.content["result"]
        for result in prompt.tool_results
        if isinstance(result.content, dict)
        and isinstance(result.content.get("result"), int | float)
    ]
    errors = [
        f"I could not use {result.name}: {result.content['error']}"
        for result in prompt.tool_results
        if isinstance(result.content, dict) and result.content.get("error")
    ]
    if _WANTS_EMAIL.search(prompt.instruction or prompt.user):
        seats = _seats(prompt)
        facts = _facts_for_email(prompt, knowledge, seats)
        price_line = None
        if totals and seats:
            period = "per year" if _ANNUAL.search(prompt.user) else "per month"
            price_line = f"For {seats} seats, that comes to {_money(totals[-1])} {period}."
        elif totals:
            price_line = f"The estimate comes to {_money(totals[-1])}."
        return email(prompt, facts, price_line=price_line)
    parts: list[str] = []
    if knowledge:
        parts.append(answer(question_of(prompt), knowledge))
    if totals:
        parts.append(f"The calculation comes to {totals[-1]:,}.")
    for result in prompt.tool_results:
        if (
            isinstance(result.content, dict)
            and "json" in result.content
            and not result.content.get("error")
        ):
            facts = _lookup_facts(result.content)
            if facts:
                parts.append(f"From {result.name.replace('_', ' ')}: " + "; ".join(facts) + ".")
    parts.extend(errors)
    if not parts:
        return "I did not find anything that answers this."
    return "\n\n".join(parts)
