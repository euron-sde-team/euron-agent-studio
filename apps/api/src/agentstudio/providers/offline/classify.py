"""Choosing a label: categories, priorities, sentiment, intent, anything with options.

Scores come from the label's lexicon (`lexicon.py`) and from the label's own words appearing
in the text. Priorities and sentiment are read along a scale instead of by raw counts, and
when the text gives no signal the classifier answers with the neutral option ("other",
"normal", "neutral", ...) rather than guessing.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence

from agentstudio.core.text import content_terms
from agentstudio.providers.offline.lexicon import DEFAULT_LABELS, LEXICON

_STRONG_URGENCY = frozenset(
    {
        "urgent",
        "emergency",
        "outage",
        "down",
        "production",
        "critical",
        "sev1",
        "p1",
        "blocked",
        "all users",
    }
)
_PRIORITY_NAMES = {
    "low": 0,
    "minor": 0,
    "normal": 1,
    "medium": 1,
    "moderate": 1,
    "standard": 1,
    "high": 2,
    "major": 2,
    "important": 2,
    "urgent": 3,
    "critical": 3,
    "highest": 3,
    "p1": 3,
}
_SENTIMENT_NAMES = {"negative": -1, "neutral": 0, "mixed": 0, "positive": 1}


def normalise_label(label: str) -> str:
    return re.sub(r"[\s-]+", "_", label.strip().lower())


def _phrase_count(text: str, terms: Counter[str], phrase: str) -> int:
    if " " in phrase or "-" in phrase or not phrase.isalpha():
        return len(re.findall(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])", text))
    stems = content_terms(phrase)
    return terms[stems[0]] if stems else 0


def signal(text: str, phrases: Sequence[str], *, cap: int = 3) -> float:
    lowered = text.lower()
    terms = Counter(content_terms(text))
    return float(sum(min(cap, _phrase_count(lowered, terms, phrase)) for phrase in phrases))


def _without_signoff(text: str) -> str:
    # "Thanks," at the end of a message is politeness, not sentiment.
    return re.sub(r"(?im)^(thanks|thank you|many thanks|cheers)[ ,!.]*$", "", text)


def urgency_score(text: str) -> float:
    lowered = text.lower()
    terms = Counter(content_terms(text))
    score = 0.0
    for phrase in LEXICON["urgent"]:
        hits = min(2, _phrase_count(lowered, terms, phrase))
        score += hits * (2.0 if phrase in _STRONG_URGENCY else 1.0)
    score += signal(text, LEXICON["high"], cap=2)
    score += 0.5 * signal(_without_signoff(text), LEXICON["negative"], cap=2)
    score -= 1.5 * signal(text, LEXICON["low"], cap=2)
    score += 0.5 * min(3, text.count("!"))
    return score


def _priority(text: str, labels: Sequence[str]) -> str | None:
    levels = {
        label: _PRIORITY_NAMES[normalise_label(label)]
        for label in labels
        if normalise_label(label) in _PRIORITY_NAMES
    }
    if len(levels) < 2:
        return None
    score = urgency_score(text)
    wanted = 3 if score >= 6 else 2 if score >= 2.5 else 0 if score <= -1 else 1
    # The closest available level, preferring the lower one on a tie.
    return min(levels, key=lambda label: (abs(levels[label] - wanted), levels[label]))


def sentiment_score(text: str) -> float:
    cleaned = _without_signoff(text)
    return signal(cleaned, LEXICON["positive"], cap=2) - signal(cleaned, LEXICON["negative"], cap=2)


def _sentiment(text: str, labels: Sequence[str]) -> str | None:
    levels = {
        label: _SENTIMENT_NAMES[normalise_label(label)]
        for label in labels
        if normalise_label(label) in _SENTIMENT_NAMES
    }
    if len(levels) < 2:
        return None
    score = sentiment_score(text)
    wanted = -1 if score <= -1 else 1 if score >= 1 else 0
    return min(levels, key=lambda label: (abs(levels[label] - wanted), -levels[label]))


def label_scores(text: str, labels: Sequence[str]) -> dict[str, float]:
    lowered = text.lower()
    terms = Counter(content_terms(text))
    scores: dict[str, float] = {}
    for label in labels:
        key = normalise_label(label)
        score = 0.0
        counted: set[str] = set()
        for phrase in LEXICON.get(key, ()):
            # "evaluate" and "evaluating" share a stem; count the evidence once.
            stem = (
                phrase if " " in phrase or not phrase.isalpha() else "".join(content_terms(phrase))
            )
            if stem in counted:
                continue
            counted.add(stem)
            score += min(3, _phrase_count(lowered, terms, phrase))
        for word in content_terms(key.replace("_", " ")):
            score += 2 * min(3, terms[word])
        scores[label] = score
    return scores


def classify(text: str, labels: Sequence[str]) -> str:
    """The best label for the text among `labels` (always one of them)."""
    options = [label for label in labels if label]
    if not options:
        return ""
    for scaled in (_priority(text, options), _sentiment(text, options)):
        if scaled is not None:
            return scaled
    scores = label_scores(text, options)
    best = max(options, key=lambda label: (scores[label], -options.index(label)))
    if scores[best] > 0:
        return best
    for default in DEFAULT_LABELS:
        for label in options:
            if normalise_label(label) == default:
                return label
    return options[-1] if len(options) > 2 else options[0]


def confidence(text: str, labels: Sequence[str]) -> float:
    """How clearly the winning label beats the runner-up, from 0.5 to 0.98."""
    scores = sorted(label_scores(text, labels).values(), reverse=True)
    if not scores or scores[0] <= 0:
        return 0.5
    runner_up = scores[1] if len(scores) > 1 else 0.0
    margin = (scores[0] - runner_up) / (scores[0] + 1)
    return round(min(0.98, 0.6 + 0.4 * margin), 2)


_CANDIDATES = re.compile(
    r"(?:one of|categories|labels|options|choose from|classes)\s*[:(]?\s*([a-z0-9_ ,/|-]{3,200})",
    re.I,
)


def candidate_labels(request: str) -> list[str]:
    """Labels offered in free text: "one of: billing, technical, account"."""
    match = _CANDIDATES.search(request)
    if not match:
        return []
    raw = re.split(r"[,/|]|\bor\b", match.group(1).split(".")[0].split("\n")[0])
    labels = [item.strip() for item in raw if item.strip() and len(item.strip()) <= 40]
    # A real list of options has at least two of them ("no options here" is not one).
    return labels if len(labels) >= 2 else []
