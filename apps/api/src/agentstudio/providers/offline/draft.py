"""Templated writing: support replies, emails, answers with citations, research briefs.

The offline model writes from templates filled with what it can find in the prompt: the
recipient's name, the topic, the sentences from the supplied sources that best match the
request, and computed values. The wording is fixed per situation, so the same prompt always
produces the same text.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from agentstudio.core.text import content_terms, truncate
from agentstudio.providers.offline import extract
from agentstudio.providers.offline.classify import classify, sentiment_score, urgency_score
from agentstudio.providers.offline.prompt import Prompt, sentences
from agentstudio.providers.offline.summarize import action_items, bullets, key_sentences

_SOURCE_HEADER = re.compile(r"^\[(\d+)\]\s*(.*)$")
_SIGN_AS = re.compile(r"\bsign(?:\s+off)?\s+as\s+[\"']?([^\"'.\n]{2,60})", re.I)

NEXT_STEPS = {
    "billing": (
        "I've asked our billing team to review your account, and we'll confirm the outcome by "
        "email as soon as it's done."
    ),
    "technical": (
        "Our engineering team is looking into this now, and I'll update you as soon as we know "
        "more."
    ),
    "account": (
        "I've checked your account settings on our side; if anything still blocks you, reply to "
        "this email and I'll fix it right away."
    ),
    "feature_request": (
        "I've shared your suggestion with our product team, who review every request when they "
        "plan the roadmap."
    ),
    "other": "Let me know if there is anything else I can help with.",
}


@dataclass(frozen=True, slots=True)
class Source:
    number: int
    title: str
    text: str


def parse_sources(context: str) -> list[Source]:
    """Numbered sources ("[1] Title" then text), or the whole context as one source."""
    found: list[Source] = []
    current: tuple[int, str] | None = None
    buffer: list[str] = []
    for line in context.splitlines():
        header = _SOURCE_HEADER.match(line.strip())
        if header:
            if current:
                found.append(Source(current[0], current[1], "\n".join(buffer).strip()))
            current = (int(header.group(1)), header.group(2).strip())
            buffer = []
        else:
            buffer.append(line)
    if current:
        found.append(Source(current[0], current[1], "\n".join(buffer).strip()))
    if not found and context.strip():
        found.append(Source(1, "", context.strip()))
    return found


def relevant(
    query: str, context: str, count: int, *, min_overlap: int = 1
) -> list[tuple[Source, str]]:
    """The context sentences that best match the query, in the order they appear.

    Words the query repeats weigh more (a ticket that says "charge" three times is about
    charges), and words that are rare in the context weigh more than common ones.
    """
    wanted = Counter(content_terms(query))
    sources = parse_sources(context)
    candidates: list[tuple[Source, str, set[str]]] = []
    for source in sources:
        for sentence in sentences(source.text):
            if sentence.startswith("#") or len(sentence.split()) < 4:
                continue
            candidates.append((source, sentence, set(content_terms(sentence))))
    document_frequency = Counter(term for _, _, terms in candidates for term in terms)
    total = max(1, len(candidates))
    scored: list[tuple[float, int]] = []
    for index, (_, sentence, terms) in enumerate(candidates):
        overlap = terms & set(wanted)
        if len(overlap) < min_overlap:
            continue
        score = sum(
            (1.0 + math.log(wanted[term])) * (1.0 + (total / document_frequency[term]) ** 0.5)
            for term in overlap
        )
        if re.search(r"\d", sentence) and re.search(
            r"\b(how (?:many|much|long|soon)|when|price|cost|refund)", query, re.I
        ):
            score += 1.5
        scored.append((score, index))
    scored.sort(key=lambda item: (-item[0], item[1]))
    best = scored[0][0] if scored else 0.0
    # Only sentences nearly as relevant as the best one: no padding with weak matches.
    chosen = sorted(index for score, index in scored[:count] if score >= 0.6 * best)
    picked: list[tuple[Source, str]] = []
    for index in chosen:
        source, sentence, _ = candidates[index]
        if sentence not in {s for _, s in picked}:
            picked.append((source, sentence))
    return picked


def sign_off(prompt: Prompt, default: str) -> str:
    match = _SIGN_AS.search(prompt.system) or _SIGN_AS.search(prompt.instruction)
    return match.group(1).strip() if match else default


def first_name(name: str | None) -> str | None:
    if not name:
        return None
    return name.split()[0].strip(",")


def second_person(sentence: str) -> str:
    replacements = (
        (r"\bI am\b", "you are"),
        (r"\bI'm\b", "you're"),
        (r"\bWe are\b", "you are"),
        (r"\bwe are\b", "you are"),
        (r"\bWe're\b", "you're"),
        (r"\bwe're\b", "you're"),
        (r"\bI\b", "you"),
        (r"\b[Ww]e\b", "you"),
        (r"\b[Oo]ur\b", "your"),
        (r"\b[Mm]y\b", "your"),
        (r"\bus\b", "you"),
    )
    result = sentence
    for pattern, replacement in replacements:
        result = re.sub(pattern, replacement, result)
    return result


def _name_from_fields(prompt: Prompt) -> str | None:
    for key in ("customer", "name", "contact", "lead", "recipient", "to"):
        value = prompt.fields.get(key)
        if value:
            candidate = (
                extract.EMAIL.sub("", value)
                .split("(")[0]
                .replace("<", "")
                .replace(">", "")
                .strip(" ,")
            )
            if candidate and candidate[0].isupper():
                return candidate
            found = extract.emails(value)
            if found:
                return extract.name_from_email(found[0])
    match = re.search(r"\bto ([A-Z][a-z]+(?: [A-Z][a-z]+)?)\b", prompt.instruction)
    if match:
        return match.group(1)
    return extract.person_name(prompt.content, prompt.fields)


# --------------------------------------------------------------------------------------
# Support replies
# --------------------------------------------------------------------------------------


def support_reply(prompt: Prompt) -> str:
    content = prompt.content
    name = first_name(_name_from_fields(prompt))
    subject = prompt.field("subject", "title")
    category = (prompt.field("category") or classify(content, list(NEXT_STEPS))).lower()
    priority = (prompt.field("priority") or "").lower()

    paragraphs = [f"Hi {name}," if name else "Hi there,"]
    opening = (
        f'Thanks for getting in touch about "{subject}".'
        if subject
        else "Thanks for getting in touch."
    )
    mood = sentiment_score(content)
    if re.search(r"\b(again|second time|still|keeps happening)\b", content, re.I):
        opening += " I'm sorry this has happened again, and I understand how frustrating that is."
    elif mood <= -1:
        opening += " I'm sorry for the trouble this has caused."
    paragraphs.append(opening)

    policy = relevant(content + " " + (subject or ""), prompt.context, 2, min_overlap=2)
    if policy:
        paragraphs.append(" ".join(sentence for _, sentence in policy))
    next_step = NEXT_STEPS.get(category.replace(" ", "_"), NEXT_STEPS["other"])
    if priority in {"urgent", "critical"} or (not priority and urgency_score(content) >= 5):
        next_step += " Because this is urgent, I've also escalated it to our on-call team."
    paragraphs.append(next_step)
    paragraphs.append("Best regards,\n" + sign_off(prompt, "The Support Team"))
    return "\n\n".join(paragraphs)


# --------------------------------------------------------------------------------------
# Emails
# --------------------------------------------------------------------------------------

_QUOTED = re.compile(r"(?:wrote|said|asked|message)[^\"\n]{0,20}:?\s*\"([^\"]{8,1200})\"", re.I)


def quoted_message(prompt: Prompt) -> str | None:
    match = _QUOTED.search(prompt.user)
    if match:
        return match.group(1).strip()
    return prompt.field("message", "they wrote", "note")


def email(prompt: Prompt, facts: list[str], *, price_line: str | None = None) -> str:
    name = first_name(_name_from_fields(prompt))
    message = quoted_message(prompt) or prompt.content
    company = prompt.field("company") or _company_in_instruction(prompt)
    paragraphs = [f"Hi {name}," if name else "Hello,"]
    lead_in = "Thanks for reaching out"
    if company:
        lead_in += f", and for telling us what the team at {company} is working on"
    paragraphs.append(lead_in + ".")
    if message and message != prompt.user:
        gist = key_sentences(message, 1)
        if gist:
            paragraphs[-1] += (
                " You mentioned that " + _lower_first(second_person(gist[0]).rstrip(".")) + "."
            )
    if facts:
        paragraphs.append(" ".join(facts))
    if price_line:
        paragraphs.append(price_line)
    nurture = bool(
        re.search(r"\b(nurture|not ready|later|no rush|keep in touch)\b", prompt.request)
    )
    if nurture:
        paragraphs.append(
            "There's no rush on our side. I'll send over a short guide on how similar teams get "
            "started, and I'm happy to answer questions whenever the timing is right."
        )
    else:
        paragraphs.append(
            "Would you be open to a 30-minute call this week to walk through it together?"
        )
    paragraphs.append("Best regards,\n" + sign_off(prompt, "The Sales Team"))
    return "\n\n".join(paragraphs)


def _company_in_instruction(prompt: Prompt) -> str | None:
    match = re.search(r"\bat ([A-Z][A-Za-z0-9&'-]*(?: [A-Z][A-Za-z0-9&'-]*){0,3})", prompt.user)
    return match.group(1).rstrip(".,") if match else None


def _lower_first(text: str) -> str:
    if len(text) > 1 and text[0].isupper() and not text[1].isupper():
        return text[0].lower() + text[1:]
    return text


# --------------------------------------------------------------------------------------
# Answers and briefs
# --------------------------------------------------------------------------------------


def answer(question: str, context: str, *, count: int = 2) -> str:
    found = relevant(question, context, count)
    if not found:
        return "I could not find an answer to that in the sources provided."
    parts = []
    for source, sentence in found:
        text = sentence.rstrip()
        if source.title:
            stop = text[-1] if text[-1] in ".!?" else "."
            text = text.rstrip(".!?") + f" [{source.number}]{stop}"
        parts.append(text)
    return " ".join(parts)


def question_of(prompt: Prompt) -> str:
    explicit = prompt.field("question", "query", "q")
    if explicit:
        return explicit
    for section in ("question", "query"):
        if section in prompt.sections:
            return prompt.sections[section]
    asked = [s for s in sentences(prompt.user) if s.rstrip().endswith("?")]
    if asked:
        return asked[0]
    return prompt.instruction or prompt.user


def research_questions(topic: str, audience: str | None, count: int = 3) -> list[str]:
    subject = _lower_first(topic.strip().rstrip("?.!")) or "this topic"
    who = audience.strip() if audience else "the team"
    questions = [
        f"What do our documents say about {subject}?",
        f"What risks or open issues affect {subject}?",
        f"What should {who} do next about {subject}?",
        f"How is {subject} measured or tracked?",
        f"Who owns {subject} and who needs to be involved?",
    ]
    return questions[: max(1, min(count, len(questions)))]


_RECOMMEND = re.compile(
    r"\b(should|must|recommend|recommended|need to|needs to|plan to|next step|we will|required)\b",
    re.I,
)


def brief(prompt: Prompt) -> str:
    topic = prompt.field("topic", "subject", "title") or truncate(prompt.instruction, 80)
    audience = prompt.field("audience", "for", "reader", "readers")
    findings = prompt.context or prompt.content
    blocks = _finding_blocks(findings)
    lines = [f"# {topic[0].upper() + topic[1:] if topic else 'Research brief'}"]
    if audience:
        lines.append(f"Prepared for {audience}.")
    lines += ["", "## Summary"]
    bodies = "\n".join(body for _, body in blocks) if blocks else findings
    summary_sentences = key_sentences(bodies, 2)
    lines.append(
        " ".join(summary_sentences) if summary_sentences else "No findings were available."
    )
    lines += ["", "## Key findings"]
    for heading, body in blocks or [("", findings)]:
        first = key_sentences(body, 1)
        if not first:
            continue
        lines.append(f"- **{heading}** {first[0]}" if heading else f"- {first[0]}")
    lines += ["", "## Recommendations"]
    recommendations = [
        s for s in sentences(findings) if _RECOMMEND.search(s) and not s.startswith("#")
    ]
    if recommendations:
        lines += [f"- {s}" for s in list(dict.fromkeys(recommendations))[:3]]
    else:
        lines.append(
            f"- Review these findings with {audience or 'the team'} and agree on an owner for "
            "each open item."
        )
    return "\n".join(lines)


def _finding_blocks(text: str) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    current: str | None = None
    buffer: list[str] = []
    for line in text.splitlines():
        if line.startswith("### "):
            if current is not None:
                blocks.append((current, "\n".join(buffer).strip()))
            current, buffer = line[4:].strip(), []
        else:
            buffer.append(line)
    if current is not None:
        blocks.append((current, "\n".join(buffer).strip()))
    return blocks


def action_item_lines(text: str) -> str:
    items = action_items(text)
    if not items:
        return "No action items were found."
    lines = []
    for item in items:
        due = f" (due {item['due']})" if item.get("due") else ""
        lines.append(f"- {item['owner']}: {item['task']}{due}")
    return "\n".join(lines)


def bullet_summary(text: str, count: int) -> str:
    return "\n".join(f"- {line}" for line in bullets(text, count)) or "- Nothing to summarise."
