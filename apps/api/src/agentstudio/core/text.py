"""Text utilities shared by the knowledge chunker and the offline model provider."""

from __future__ import annotations

import re
import unicodedata

_SPACES = re.compile(r"[ \t\u00a0\u2000-\u200b\u202f\u205f\u3000]+")
_MANY_BLANK_LINES = re.compile(r"\n{3,}")
# A sentence ends at . ! or ? (optionally followed by closing quotes or brackets), then
# whitespace, then something that can start a sentence.
_BOUNDARY = re.compile(r"[.!?][\"'\u201d\u2019)\]]*\s+(?=[\"'\u201c\u2018(\[]?[A-Z0-9\u2022])")
_ABBREVIATIONS = frozenset(
    """e.g i.e etc vs mr mrs ms dr prof inc ltd co corp no fig approx dept est jan feb mar apr
    jun jul aug sep sept oct nov dec st mt u.s u.k a.m p.m""".split()
)
_WORD = re.compile(r"[a-z0-9]+(?:['.][a-z0-9]+)*")
STOPWORDS = frozenset(
    """a about above after again against all am an and any are as at be because been before
    being below between both but by can could did do does doing down during each few for
    from further had has have having he her here hers herself him himself his how i if in
    into is it its itself just me more most my myself no nor not now of off on once only or
    other our ours ourselves out over own same she should so some such than that the their
    theirs them themselves then there these they this those through to too under until up
    very was we were what when where which while who whom why will with would you your yours
    yourself yourselves tell show give list please much many does know need want get got use
    like make say think see look find take come go must may might shall can could would
    will""".split()
)


def normalize(text: str) -> str:
    """NFC, unified newlines, single spaces, at most one blank line between paragraphs."""
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u00ad", "")  # soft hyphens from PDF line breaking
    lines = [_SPACES.sub(" ", line).strip() for line in text.split("\n")]
    return _MANY_BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()


def sentence_spans(text: str) -> list[tuple[int, int]]:
    """Character spans of the sentences in `text`, abbreviation and decimal aware."""
    spans: list[tuple[int, int]] = []
    start = 0
    for match in _BOUNDARY.finditer(text):
        end = match.start() + 1
        before = text[start:end].rstrip(".!?\"')]\u201d\u2019").split()
        last_word = before[-1].lower().rstrip(".") if before else ""
        if last_word in _ABBREVIATIONS or (len(last_word) == 1 and last_word.isalpha()):
            continue
        sentence_end = match.end() - len(match.group()) + len(match.group().rstrip())
        spans.append((start, sentence_end))
        start = match.end()
    if start < len(text) and text[start:].strip():
        spans.append((start, len(text.rstrip())))
    return [(s, e) for s, e in spans if text[s:e].strip()]


def split_sentences(text: str) -> list[str]:
    return [text[s:e].strip() for s, e in sentence_spans(text)]


def _stem(word: str) -> str:
    """A light, consistent stemmer: hire, hires, hired and hiring all become "hir".

    Deliberately small (no dependency) and applied identically to questions and passages,
    which is all the extractive scorer needs. Tokens with digits are left alone.
    """
    if len(word) <= 3 or not word.isalpha():
        return word
    for suffix, replacement in (("ies", "y"), ("ing", ""), ("ed", ""), ("es", ""), ("s", "")):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            word = word[: -len(suffix)] + replacement
            break
    if len(word) > 4 and word[-1] == word[-2] and word[-1] not in "lsz":
        word = word[:-1]
    if len(word) > 3 and word.endswith("e"):
        word = word[:-1]
    return word


def content_terms(text: str) -> list[str]:
    """Lowercased, stemmed words without stopwords, in order (duplicates kept)."""
    return [_stem(w) for w in _WORD.findall(text.lower()) if w not in STOPWORDS and len(w) > 1]


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(" ,.;:") + "..."
