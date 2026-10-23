"""Filling a JSON schema from a prompt: one rule per kind of field.

The field's name, type, options and description decide how it is filled: options are
classified, money and dates are extracted near their keywords, lists such as action items
or questions are generated, and unknown fields are looked up as "Label: value" lines. A field
with no evidence is null, never invented.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from agentstudio.core.text import content_terms
from agentstudio.providers.offline import extract
from agentstudio.providers.offline.classify import (
    classify,
    confidence,
    label_scores,
    sentiment_score,
)
from agentstudio.providers.offline.draft import research_questions
from agentstudio.providers.offline.lexicon import LEXICON
from agentstudio.providers.offline.prompt import Prompt, sentences
from agentstudio.providers.offline.summarize import (
    action_items,
    decisions,
    key_sentences,
    keywords,
    one_sentence,
    speakers,
)

_MONEY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "subtotal": ("subtotal", "sub-total", "net amount", "net total"),
    "tax": ("tax", "vat", "gst", "sales tax"),
    "shipping": ("shipping", "delivery", "freight"),
    "discount": ("discount",),
    "total": ("total due", "amount due", "balance due", "grand total", "total amount", "total"),
    "balance": ("balance due", "balance", "amount due"),
    "budget": ("budget",),
    "revenue": ("revenue", "arr", "annual revenue"),
}
_MONEY_WORDS = (
    "total",
    "subtotal",
    "tax",
    "vat",
    "amount",
    "price",
    "cost",
    "balance",
    "fee",
    "revenue",
    "budget",
    "discount",
    "shipping",
    "spend",
)
_COUNT_WORDS = (
    "seats",
    "users",
    "licenses",
    "licences",
    "quantity",
    "employees",
    "headcount",
    "count",
    "people",
    "agents",
)


def schema_of(response_format: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not response_format:
        return None
    if response_format.get("type") == "json_schema":
        schema = (response_format.get("json_schema") or {}).get("schema")
        return dict(schema) if isinstance(schema, dict) else {"type": "object", "properties": {}}
    if response_format.get("type") == "json_object":
        return {"type": "object", "properties": {}}
    return None


def _types(spec: Mapping[str, Any]) -> list[str]:
    kind = spec.get("type", "string")
    return [kind] if isinstance(kind, str) else [k for k in kind if k != "null"]


def _words(name: str) -> list[str]:
    return [word for word in re.split(r"[_\s-]+", name.lower()) if word]


def fill(schema: Mapping[str, Any], prompt: Prompt) -> dict[str, Any]:
    properties = schema.get("properties") or {}
    if not properties:
        return _free_form(prompt)
    text = _material(prompt)
    return {name: _value(name, spec, prompt, text) for name, spec in properties.items()}


def _material(prompt: Prompt) -> str:
    parts = [f"{label}: {value}" for label, value in prompt.fields.items()]
    parts.append(prompt.content)
    return "\n".join(part for part in parts if part)


def _free_form(prompt: Prompt) -> dict[str, Any]:
    """JSON mode without a schema: the inline fields found, plus a summary."""
    data: dict[str, Any] = {re.sub(r"\W+", "_", k).strip("_"): v for k, v in prompt.fields.items()}
    data["summary"] = one_sentence(prompt.content)
    return data


def _value(name: str, spec: Mapping[str, Any], prompt: Prompt, text: str) -> Any:
    kinds = _types(spec)
    words = _words(name)
    enum = [option for option in spec.get("enum") or [] if option is not None]
    if enum:
        return classify(
            prompt.content + "\n" + "\n".join(prompt.fields.values()), [str(o) for o in enum]
        )
    if "object" in kinds and spec.get("properties"):
        return {key: _value(key, sub, prompt, text) for key, sub in spec["properties"].items()}
    if "array" in kinds:
        return _array(words, spec, prompt, text)
    if "boolean" in kinds:
        return _boolean(words, text)
    if "number" in kinds or "integer" in kinds:
        value = _number(words, prompt, text)
        if value is not None and "integer" in kinds and "number" not in kinds:
            return round(value)
        return value
    return _string(words, spec, prompt, text)


# --------------------------------------------------------------------------------------
# Kinds of fields
# --------------------------------------------------------------------------------------


def _array(words: list[str], spec: Mapping[str, Any], prompt: Prompt, text: str) -> list[Any]:
    items = spec.get("items") or {}
    item_props = items.get("properties") or {}
    joined = " ".join(words)
    if item_props:
        names = set(item_props)
        if names & {"owner", "assignee", "task", "action", "due", "deadline"}:
            return [_map_item(item, item_props) for item in action_items(prompt.content)]
        if (
            "line" in words
            or "items" in words
            or names & {"quantity", "qty", "unit_price", "amount"}
        ):
            return [_map_item(row, item_props) for row in extract.line_items(prompt.content)]
        return []
    if "question" in joined:
        topic = prompt.field("topic", "subject") or prompt.content or prompt.instruction
        return research_questions(topic, prompt.field("audience"), _count_requested(prompt) or 3)
    if "decision" in joined:
        return decisions(prompt.content)
    if "action" in joined or "todo" in joined or "next_step" in "_".join(words):
        return [
            f"{i['owner']}: {i['task']}" + (f" (due {i['due']})" if i["due"] else "")
            for i in action_items(prompt.content)
        ]
    if any(word in words for word in ("attendees", "participants", "people", "speakers")):
        return speakers(prompt.content)
    if "email" in joined:
        return extract.emails(text)
    if any(word in words for word in ("tags", "keywords", "topics", "themes")):
        return keywords(prompt.content, 5)
    if any(word in words for word in ("risks", "issues", "concerns", "blockers")):
        risky = [
            s
            for s in sentences(prompt.content)
            if re.search(
                r"\b(risk|concern|issue|blocker|delay|problem|might|could fail)\b", s, re.I
            )
        ]
        return risky[:4]
    return key_sentences(prompt.content, 3)


def _map_item(item: Mapping[str, Any], props: Mapping[str, Any]) -> dict[str, Any]:
    aliases = {
        "owner": ("owner", "assignee", "person", "who"),
        "task": ("task", "action", "item", "title", "description", "what"),
        "due": ("due", "deadline", "due_date", "when", "by"),
        "description": ("description", "item", "name", "product", "service", "title"),
        "quantity": ("quantity", "qty", "units", "count"),
        "unit_price": ("unit_price", "price", "rate", "unit_cost"),
        "amount": ("amount", "total", "line_total", "subtotal", "cost"),
    }
    mapped: dict[str, Any] = {}
    for prop, spec in props.items():
        value = None
        for source, names in aliases.items():
            if prop.lower() in names and source in item:
                value = item[source]
                break
        if value is not None and ("number" in _types(spec) or "integer" in _types(spec)):
            value = value if isinstance(value, int | float) else extract.parse_number(str(value))
        mapped[prop] = value
    return mapped


def _count_requested(prompt: Prompt) -> int | None:
    match = re.search(
        r"\b(two|three|four|five|2|3|4|5)\s+(?:research\s+|sub-?)?questions\b", prompt.request
    )
    if not match:
        return None
    return {"two": 2, "three": 3, "four": 4, "five": 5}.get(match.group(1)) or int(match.group(1))


def _boolean(words: list[str], text: str) -> bool:
    meaningful = [
        w
        for w in words
        if w
        not in {
            "is",
            "has",
            "have",
            "requires",
            "required",
            "needs",
            "mentioned",
            "requested",
            "provided",
            "present",
            "included",
            "any",
        }
    ]
    lowered = text.lower()
    if "budget" in meaningful:
        return bool(
            re.search(
                r"\b(budget|budgeted|spend|price range|\$\s?\d|\d+\s?k\b|per (seat|user))", lowered
            )
        )
    if "urgent" in meaningful or "urgency" in meaningful:
        return any(word in lowered for word in LEXICON["urgent"])
    if "refund" in meaningful:
        return "refund" in lowered
    if "human" in meaningful or "escalat" in "".join(meaningful):
        return sentiment_score(text) <= -2
    stems = set(content_terms(" ".join(meaningful)))
    return bool(stems) and stems <= set(content_terms(text))


def _number(words: list[str], prompt: Prompt, text: str) -> float | int | None:
    joined = "_".join(words)
    for key, phrases in _MONEY_KEYWORDS.items():
        if key in words or joined == key:
            return extract.amount_near(text, phrases)
    if any(word in words for word in _MONEY_WORDS):
        return extract.amount_near(
            text, [" ".join(w for w in words if w not in {"amount", "usd"}) or "amount"]
        )
    if any(word in words for word in _COUNT_WORDS):
        nouns = [w for w in words if w in _COUNT_WORDS and w not in {"quantity", "count"}]
        found = extract.quantity(text, nouns or None)
        if found is not None:
            return found
        return extract.amount_near(text, [" ".join(words)])
    if "confidence" in words or "probability" in words:
        return confidence(prompt.content, list(LEXICON)) if prompt.content else 0.5
    if "score" in words or "rating" in words:
        return _signal_score(words, prompt.content)
    return extract.amount_near(text, [" ".join(words)])


def _signal_score(words: list[str], text: str) -> int:
    """A 0 to 50 score from buying signals, for lead scoring fields."""
    scores = label_scores(text, ["purchase", "evaluation"])
    score = 10 + 8 * scores["purchase"] + 4 * scores["evaluation"]
    if extract.quantity(text) is not None:
        score += 6
    if re.search(
        r"\b(this quarter|this month|next month|asap|immediately|this week|q[1-4])\b", text, re.I
    ):
        score += 6
    if re.search(r"\b(budget|approved|signed|procurement)\b", text, re.I):
        score += 5
    return int(max(0, min(50, round(score))))


def _string(words: list[str], spec: Mapping[str, Any], prompt: Prompt, text: str) -> str | None:
    joined = "_".join(words)
    looked_up = extract.lookup_field(prompt.fields, joined)
    if "email" in words:
        found = extract.emails(text)
        return found[0] if found else None
    if "phone" in words:
        found = extract.phones(text)
        return found[0] if found else None
    if any(w in words for w in ("url", "website", "link")):
        found = extract.urls(text)
        return found[0] if found else None
    if "domain" in words:
        return extract.domain_of(text)
    if "currency" in words:
        return extract.currency(text)
    if "terms" in words:
        return extract.payment_terms(text) or looked_up
    if "invoice" in words and any(w in words for w in ("number", "no", "id", "ref")):
        return extract.invoice_number(text, prompt.fields)
    if any(w in words for w in ("date", "due", "deadline", "issued")):
        if "due" in words or "deadline" in words:
            return extract.date_near(text, ("due date", "payment due", "due", "deadline"))
        if looked_up and extract.dates(looked_up):
            return extract.dates(looked_up)[0][1]
        return extract.date_near(
            text, (" ".join(words), "invoice date", "date of issue", "issued")
        ) or extract.first_date(text, avoid=("due",))
    if any(w in words for w in ("vendor", "supplier", "seller", "merchant")):
        return extract.vendor_name(prompt.content, prompt.fields) or looked_up
    if any(w in words for w in ("company", "organization", "organisation", "employer")):
        return extract.company_name(text, prompt.fields) or looked_up
    if looked_up:
        return looked_up
    if any(
        w in words for w in ("name", "customer", "contact", "person", "owner", "assignee", "author")
    ):
        return extract.person_name(prompt.content, prompt.fields)
    if any(
        w in words
        for w in ("summary", "description", "overview", "synopsis", "gist", "problem", "issue")
    ):
        return one_sentence(prompt.content)
    if any(w in words for w in ("title", "subject", "headline")):
        return prompt.field("subject", "title") or one_sentence(
            prompt.content, max_words=10
        ).rstrip(".")
    if any(w in words for w in ("use", "case", "need", "goal", "request", "intent", "purpose")):
        return one_sentence(prompt.content, max_words=18)
    if "language" in words:
        return "en"
    if any(w in words for w in ("reason", "rationale", "explanation", "justification")):
        return _reason(prompt)
    if any(w in words for w in ("category", "type", "topic", "theme")):
        found = keywords(prompt.content, 1)
        return found[0] if found else None
    if "sentiment" in words:
        return classify(prompt.content, ["negative", "neutral", "positive"])
    if "priority" in words:
        return classify(prompt.content, ["low", "normal", "high", "urgent"])
    description = str(spec.get("description") or "")
    if description:
        found = key_sentences(prompt.content, 1, focus=content_terms(description))
        return found[0] if found else None
    return None


def _reason(prompt: Prompt) -> str:
    signals = [
        s
        for s in sentences(prompt.content)
        if re.search(r"\b(because|since|due to|so that|as)\b", s, re.I)
    ]
    if signals:
        return signals[0]
    return one_sentence(prompt.content, max_words=20)
