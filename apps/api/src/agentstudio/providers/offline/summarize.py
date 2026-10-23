"""Summaries, key points, action items and decisions, by extraction.

Sentences are ranked by how many of the text's frequent content words they carry (the
classic frequency method), with a small bonus for coming early, then returned in their
original order so a summary still reads naturally.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable

from agentstudio.core.text import content_terms, truncate
from agentstudio.providers.offline.prompt import sentences

_PRONOUNS = (
    (r"\bI was\b", "The customer was"),
    (r"\bI am\b", "The customer is"),
    (r"\bI'm\b", "The customer is"),
    (r"\bI have\b", "The customer has"),
    (r"\bI've\b", "The customer has"),
    (r"\bI can't\b", "The customer cannot"),
    (r"\bI cannot\b", "The customer cannot"),
    (r"\bI need\b", "The customer needs"),
    (r"\bI want\b", "The customer wants"),
    (r"\bI would\b", "The customer would"),
    (r"\bI'd\b", "The customer would"),
    (r"\bI\b", "the customer"),
    (r"\bWe are\b", "They are"),
    (r"\bwe are\b", "they are"),
    (r"\bWe're\b", "They're"),
    (r"\bwe're\b", "they're"),
    (r"\bWe\b", "They"),
    (r"\bwe\b", "they"),
    (r"\bour\b", "their"),
    (r"\bOur\b", "Their"),
    (r"\bmy\b", "their"),
    (r"\bMy\b", "Their"),
    (r"\bus\b", "them"),
)


def third_person(sentence: str) -> str:
    result = sentence
    for pattern, replacement in _PRONOUNS:
        result = re.sub(pattern, replacement, result)
    return result[0].upper() + result[1:] if result else result


def rank(found: list[str], *, focus: Iterable[str] = ()) -> list[tuple[float, int]]:
    """(score, index) for every sentence, best first."""
    focus_terms = set(focus)
    frequencies = Counter(term for sentence in found for term in set(content_terms(sentence)))
    ranked: list[tuple[float, int]] = []
    for index, sentence in enumerate(found):
        terms = set(content_terms(sentence))
        if not terms:
            continue
        score = sum(frequencies[term] for term in terms) / (len(terms) + 4) ** 0.5
        score += 2.0 * len(terms & focus_terms)
        if index == 0:
            score *= 1.25
        if len(sentence.split()) < 5:
            score *= 0.5
        if sentence.rstrip().endswith("?"):
            score *= 0.6
        # Decisions, figures and dates carry a summary; personal to-dos and pleasantries do not.
        if re.search(
            r"\d|\b(decided|agreed|approved|launch|blocker|risk|goal|on track)\b", sentence, re.I
        ):
            score *= 1.3
        if re.match(r"(?i)(let me|i'll|i will|thanks|thank you|ok|okay)\b", sentence):
            score *= 0.6
        ranked.append((score, index))
    ranked.sort(key=lambda pair: (-pair[0], pair[1]))
    return ranked


def key_sentences(text: str, count: int, *, focus: Iterable[str] = ()) -> list[str]:
    found = list(dict.fromkeys(sentences(text)))
    chosen = sorted(index for _, index in rank(found, focus=focus)[:count])
    return [found[index] for index in chosen]


def summary(text: str, *, count: int = 2) -> str:
    return " ".join(key_sentences(text, count))


def one_sentence(text: str, *, max_words: int = 32) -> str:
    """A one-line summary: the most representative sentence, in the third person."""
    found = sentences(text)
    if not found:
        return ""
    ranked = rank(found)
    best = found[ranked[0][1]] if ranked else found[0]
    best = third_person(best.strip())
    words = best.split()
    if len(words) > max_words:
        best = " ".join(words[:max_words]).rstrip(",;:") + "..."
    return best if best.endswith((".", "!", "?", "...")) else best + "."


def bullets(text: str, count: int = 3) -> list[str]:
    return [truncate(sentence, 240) for sentence in key_sentences(text, count)]


# --------------------------------------------------------------------------------------
# Meetings
# --------------------------------------------------------------------------------------

_SPEAKER = re.compile(
    r"^\s*(?:\[[^\]]*\]\s*)?([A-Z][a-zA-Z.'-]+(?: [A-Z][a-zA-Z.'-]+)?)\s*:\s*(.+)$"
)
_OWNER_FIRST = re.compile(
    r"^(?:action(?: item)?:\s*)?@?([A-Z][a-z]+)(?:,)?\s+"
    r"(?:will|to|can|is going to|needs to|should)\s+(.+)$"
)
_SELF = re.compile(
    r"^(?:ok(?:ay)?,?\s+|sure,?\s+|yes,?\s+)?"
    r"(?:i'll|i will|i can|i'm going to|i am going to|let me|i'll go ahead and)\s+(.+)$",
    re.I,
)
_TEAM = re.compile(r"^(?:we'll|we will|we need to|we should|we're going to)\s+(.+)$", re.I)
_ACTION = re.compile(r"^(?:action(?: item)?|todo|to-do|next step)s?\s*:\s*(.+)$", re.I)
_DUE = re.compile(
    r"\s*\b(?:by|before|until|due|no later than|on)\s+"
    r"((?:end of (?:the )?(?:day|week|month|quarter))|eod|eow|"
    r"(?:next |this )?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|tomorrow|today|"
    r"next week|next month|"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.? \d{1,2}(?:st|nd|rd|th)?|"
    r"\d{4}-\d{2}-\d{2}|the \d{1,2}(?:st|nd|rd|th))\b",
    re.I,
)
_DECISION = re.compile(
    r"\b(decided|agreed|agree to|decision|we will go with|we're going with|approved|"
    r"signed off|settled on|"
    r"go with)\b",
    re.I,
)
_NOT_A_NAME = frozenset(
    {"We", "It", "This", "That", "They", "There", "Everyone", "Someone", "Nobody", "Okay", "So"}
)


def _clean_task(task: str) -> tuple[str, str | None]:
    due = None
    match = _DUE.search(task)
    if match:
        due = match.group(1)
        task = (task[: match.start()] + task[match.end() :]).strip()
    task = re.sub(r"\s+", " ", task).strip(" ,.;:-")
    task = re.sub(r"^(?:go ahead and|also|then|just)\s+", "", task, flags=re.I)
    if due:
        due = due[0].upper() + due[1:] if not due[0].isdigit() else due
    return (task[0].upper() + task[1:] if task else task), due


def action_items(text: str) -> list[dict[str, str | None]]:
    """Commitments made in notes or a transcript: owner, task and due date."""
    items: list[dict[str, str | None]] = []
    seen: set[str] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip(" -*\t\N{BULLET}")
        if not line:
            continue
        speaker = None
        speaking = _SPEAKER.match(line)
        if speaking and speaking.group(1) not in _NOT_A_NAME:
            speaker, line = speaking.group(1), speaking.group(2)
        for sentence in re.split(r"(?<=[.!?])\s+", line):
            sentence = sentence.strip()
            if (
                not sentence
                or sentence.endswith("?")
                or re.search(r"\b(won't|will not|can't|cannot)\b", sentence, re.I)
            ):
                continue
            owner: str | None = None
            task: str | None = None
            action = _ACTION.match(sentence)
            if action:
                sentence = action.group(1)
            named = _OWNER_FIRST.match(sentence)
            own = _SELF.match(sentence)
            team = _TEAM.match(sentence)
            if named and named.group(1) not in _NOT_A_NAME:
                owner, task = named.group(1), named.group(2)
            elif own:
                owner, task = speaker, own.group(1)
            elif team:
                owner, task = speaker or "Team", team.group(1)
            elif action:
                owner, task = speaker, sentence
            if not task:
                continue
            cleaned, due = _clean_task(task)
            key = cleaned.lower()
            if len(cleaned.split()) < 2 or key in seen:
                continue
            seen.add(key)
            items.append({"owner": owner or "Unassigned", "task": cleaned, "due": due})
    return items


def decisions(text: str) -> list[str]:
    found: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip(" -*\t\N{BULLET}")
        speaking = _SPEAKER.match(line)
        if speaking:
            line = speaking.group(2)
        for sentence in re.split(r"(?<=[.!?])\s+", line):
            if (
                _DECISION.search(sentence)
                and not sentence.strip().endswith("?")
                and len(sentence.split()) >= 4
            ):
                cleaned = sentence.strip()
                if cleaned and cleaned not in found:
                    found.append(cleaned[0].upper() + cleaned[1:])
    return found


def speakers(text: str) -> list[str]:
    found: list[str] = []
    for line in text.splitlines():
        match = _SPEAKER.match(line.strip())
        if match and match.group(1) not in _NOT_A_NAME and match.group(1) not in found:
            found.append(match.group(1))
    return found


def keywords(text: str, count: int = 5) -> list[str]:
    counts = Counter(
        word for word in re.findall(r"[a-z][a-z-]{3,}", text.lower()) if word not in _STOP
    )
    return [word for word, _ in counts.most_common(count)]


_STOP = frozenset(
    """this that with from have will your their there about would could should which when what
    where while been were they them then than into also just only more most some such very
    team hello thanks thank regards please""".split()
)
