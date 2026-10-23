"""Pulling values out of text: contact details, money, dates, ids, line items, names.

Every extractor is a pure function of the text, so the offline model stays deterministic.
Each one prefers explicit evidence (a "Total due:" line, a "From:" field) over guesses, and
returns None rather than inventing a value.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from datetime import date

from agentstudio.core.text import content_terms

CURRENCY_SYMBOLS = {
    "$": "USD",
    "\N{EURO SIGN}": "EUR",
    "\N{POUND SIGN}": "GBP",
    "\N{INDIAN RUPEE SIGN}": "INR",
    "\N{YEN SIGN}": "JPY",
}
CURRENCY_CODES = (
    "USD",
    "EUR",
    "GBP",
    "INR",
    "JPY",
    "AUD",
    "CAD",
    "CHF",
    "SGD",
    "AED",
    "SEK",
    "NZD",
)
_SYMBOLS = re.escape("".join(CURRENCY_SYMBOLS))

EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
URL = re.compile(r"\bhttps?://[^\s)>\]\"']+")
PHONE = re.compile(r"(?<![\w.])\+?\d[\d ().-]{7,}\d(?![\w.])")
NUMBER = re.compile(r"(?<![\w.])-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?![\w])")
QUANTITY = re.compile(
    r"\b(\d[\d,]*)\s+(seats|users|licen[cs]es|people|employees|agents|engineers|members|staff|"
    r"reps|developers|analysts|accounts|stores|locations)\b",
    re.I,
)
INVOICE_NUMBER = re.compile(
    r"\b(?:invoice|inv)\b\.?\s*(?:no\.?|number|num|#|id)?\s*[:#]?\s*([A-Z]{0,5}[-/]?\d[\w/-]{1,24})",
    re.I,
)
PAYMENT_TERMS = re.compile(
    r"\b(net\s?\d{1,3}|due on receipt|due upon receipt|payable within \d{1,3} days|"
    r"\d{1,3} days net)\b",
    re.I,
)
_COMPANY_SUFFIX = re.compile(
    r"\b(inc|inc\.|ltd|ltd\.|llc|llp|gmbh|corp|corporation|co\.|company|limited|plc|ag|sa|bv|pty)\b",
    re.I,
)

_MONTHS = {
    name: number
    for number, names in enumerate(
        (
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ),
        start=1,
    )
    for name in names
}
_MONTH = (
    r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
    r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
_DATE_PATTERNS = (
    re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"),
    re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+{_MONTH}\.?,?\s+(\d{{4}})\b", re.I),
    re.compile(rf"\b{_MONTH}\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.I),
    re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"),
)
_RELATIVE_DATE = re.compile(
    r"\b(today|tomorrow|tonight|next week|next month|end of (?:the )?(?:day|week|month|quarter)|"
    r"eod|eow|(?:this |next )?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))\b",
    re.I,
)


def emails(text: str) -> list[str]:
    return list(dict.fromkeys(EMAIL.findall(text)))


def urls(text: str) -> list[str]:
    return list(dict.fromkeys(URL.findall(text)))


def phones(text: str) -> list[str]:
    found = []
    for match in PHONE.findall(text):
        digits = re.sub(r"\D", "", match)
        if 8 <= len(digits) <= 15 and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", match.strip()):
            found.append(match.strip())
    return list(dict.fromkeys(found))


def domain_of(text: str) -> str | None:
    for address in emails(text):
        return address.split("@", 1)[1].lower()
    for url in urls(text):
        host = url.split("://", 1)[1].split("/", 1)[0]
        return host.lower().removeprefix("www.")
    return None


def parse_number(raw: str) -> float | int | None:
    cleaned = raw.replace(",", "").strip()
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return int(value) if value.is_integer() and "." not in cleaned else value


def numbers(text: str) -> list[float | int]:
    found = []
    for raw in NUMBER.findall(text):
        value = parse_number(raw)
        if value is not None:
            found.append(value)
    return found


def _keyword_pattern(keyword: str) -> re.Pattern[str]:
    return re.compile(
        r"(?<![a-z])" + re.escape(keyword.lower()).replace(r"\ ", r"[\s_-]*") + r"(?![a-z])"
    )


def amount_near(text: str, keywords: Iterable[str]) -> float | int | None:
    """The amount on the first line that names one of the keywords (the last number on it)."""
    lines = text.splitlines()
    for keyword in keywords:
        pattern = _keyword_pattern(keyword)
        for line in lines:
            lowered = line.lower()
            match = pattern.search(lowered)
            if not match:
                continue
            values = numbers(line[match.end() :])
            # "Tax (20%): 240.00": the rate is not the amount.
            values = [
                v for v in values if not re.search(rf"{re.escape(str(v))}\s*%", line)
            ] or values
            if values:
                return values[-1]
    return None


_SYNONYMS = (
    {"seat", "user", "license", "licence", "agent", "member", "rep", "developer", "analyst"},
    {"employee", "people", "staff", "headcount", "person"},
)


def quantity(text: str, nouns: Iterable[str] | None = None) -> int | None:
    wanted = {noun.lower().rstrip("s") for noun in nouns or ()}
    for group in _SYNONYMS:
        if wanted & group:
            wanted |= group
    for count, noun in QUANTITY.findall(text):
        if not wanted or noun.lower().rstrip("s") in wanted or noun.lower().rstrip("es") in wanted:
            value = parse_number(count)
            if value is not None:
                return int(value)
    return None


def currency(text: str) -> str | None:
    for code in re.findall(r"\b([A-Z]{3})\b", text):
        if code in CURRENCY_CODES:
            return str(code)
    for symbol, code in CURRENCY_SYMBOLS.items():
        if re.search(re.escape(symbol) + r"\s?\d", text):
            return code
    return None


def _month(name: str) -> int:
    key = name.lower().rstrip(".")
    return _MONTHS.get(key) or _MONTHS[key[:3]]


def _to_iso(match: re.Match[str], pattern_index: int) -> str | None:
    groups = match.groups()
    try:
        if pattern_index == 0:
            year, month, day = int(groups[0]), int(groups[1]), int(groups[2])
        elif pattern_index == 1:
            day, month, year = int(groups[0]), _month(groups[1]), int(groups[2])
        elif pattern_index == 2:
            month, day, year = _month(groups[0]), int(groups[1]), int(groups[2])
        else:
            first, second, year = int(groups[0]), int(groups[1]), int(groups[2])
            # Day first when it cannot be a month; otherwise month first (US style).
            day, month = (first, second) if first > 12 else (second, first)
        return date(year, month, day).isoformat()
    except (ValueError, KeyError):
        return None


def dates(text: str) -> list[tuple[int, str]]:
    """(position, ISO date) for every absolute date in the text, in order."""
    found: list[tuple[int, str]] = []
    taken: list[tuple[int, int]] = []
    for index, pattern in enumerate(_DATE_PATTERNS):
        for match in pattern.finditer(text):
            if any(start <= match.start() < end for start, end in taken):
                continue
            iso = _to_iso(match, index)
            if iso:
                found.append((match.start(), iso))
                taken.append((match.start(), match.end()))
    return sorted(found)


def date_near(text: str, keywords: Iterable[str]) -> str | None:
    for keyword in keywords:
        pattern = _keyword_pattern(keyword)
        for line in text.splitlines():
            match = pattern.search(line.lower())
            if match:
                on_line = dates(line[match.start() :])
                if on_line:
                    return on_line[0][1]
                relative = _RELATIVE_DATE.search(line[match.start() :])
                if relative:
                    return relative.group(1)
    return None


def first_date(text: str, *, avoid: Iterable[str] = ()) -> str | None:
    avoid_patterns = [_keyword_pattern(word) for word in avoid]
    for line in text.splitlines():
        if any(pattern.search(line.lower()) for pattern in avoid_patterns):
            continue
        found = dates(line)
        if found:
            return found[0][1]
    return None


def relative_date(text: str) -> str | None:
    match = _RELATIVE_DATE.search(text)
    return match.group(1) if match else None


def invoice_number(text: str, fields: Mapping[str, str]) -> str | None:
    value = lookup_field(fields, "invoice_number") or lookup_field(fields, "invoice_no")
    if value:
        return value.split()[0].strip(" #:")
    match = INVOICE_NUMBER.search(text)
    return match.group(1).strip(" #:.,") if match else None


def payment_terms(text: str) -> str | None:
    match = PAYMENT_TERMS.search(text)
    if not match:
        return None
    terms = match.group(1)
    return terms[0].upper() + terms[1:] if terms[0].isalpha() else terms


# --------------------------------------------------------------------------------------
# Names and organisations
# --------------------------------------------------------------------------------------

_SIGNOFF = re.compile(
    r"^(thanks|thank you|many thanks|regards|best|best regards|kind regards|cheers|"
    r"sincerely)\b[ ,!.]*$",
    re.I,
)
_INTRO = re.compile(r"\b(?:i'm|i am|my name is|this is)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)")
_NAME = re.compile(r"^[A-Z][a-z'-]+(?:\s+[A-Z][a-z'-]+){0,2}$")


def name_from_email(address: str) -> str:
    local = address.split("@", 1)[0]
    parts = [part for part in re.split(r"[._-]+", local) if part.isalpha()]
    return " ".join(part.capitalize() for part in parts) if parts else local


def company_from_domain(domain: str) -> str:
    label = domain.split(".")[0]
    return label.replace("-", " ").title()


def _strip_email(value: str) -> str:
    return EMAIL.sub("", value).replace("<", "").replace(">", "").strip(" ,()")


def person_name(text: str, fields: Mapping[str, str]) -> str | None:
    for key in (
        "name",
        "customer name",
        "contact name",
        "full name",
        "customer",
        "contact",
        "from",
        "lead",
    ):
        value = fields.get(key)
        if not value:
            continue
        stripped = _strip_email(value).split("(")[0].strip()
        if stripped and _NAME.match(stripped):
            return stripped
        found = emails(value)
        if found:
            return name_from_email(found[0])
    lines = [line.strip() for line in text.splitlines()]
    for index, line in enumerate(lines[:-1]):
        if _SIGNOFF.match(line):
            candidate = lines[index + 1].strip(" ,")
            if _NAME.match(candidate):
                return candidate
    intro = _INTRO.search(text)
    if intro:
        return intro.group(1)
    found = emails(text)
    return name_from_email(found[0]) if found else None


_COMPANY_FIELDS = ("company", "organization", "organisation", "account", "employer", "business")


def company_name(text: str, fields: Mapping[str, str]) -> str | None:
    for key in _COMPANY_FIELDS:
        value = fields.get(key)
        stripped = _strip_email(value) if value else ""
        if stripped:
            return stripped
    # "From:" may hold a person or a company; only a company suffix settles it.
    sender = _strip_email(fields.get("from", ""))
    if sender and _COMPANY_SUFFIX.search(sender):
        return sender
    for line in text.splitlines()[:12]:
        candidate = line.strip()
        if (
            candidate
            and _COMPANY_SUFFIX.search(candidate)
            and len(candidate) <= 80
            and "@" not in candidate
        ):
            return candidate.strip(" ,")
    lines = [line.strip() for line in text.splitlines()]
    for index, line in enumerate(lines[:-2]):
        if _SIGNOFF.match(line) and lines[index + 2].strip():
            candidate = lines[index + 2].strip(" ,")
            if 2 <= len(candidate) <= 60 and "@" not in candidate:
                return candidate
    domain = domain_of(text)
    return company_from_domain(domain) if domain else None


def vendor_name(text: str, fields: Mapping[str, str]) -> str | None:
    for key in ("vendor", "supplier", "from", "bill from", "seller", "issued by", "company"):
        value = fields.get(key)
        if value:
            return _tidy_name(_strip_email(value).split("\n")[0].strip())
    for line in text.splitlines()[:8]:
        candidate = line.strip()
        lowered = candidate.lower()
        if not candidate or "invoice" in lowered or ":" in candidate or "@" in candidate:
            continue
        if _COMPANY_SUFFIX.search(candidate) or (
            candidate.istitle() and len(candidate.split()) <= 5
        ):
            return _tidy_name(candidate.strip(" ,"))
    return None


_KEEP_UPPER = frozenset({"LLC", "LLP", "PLC", "AG", "SA", "BV", "UK", "US", "EU", "GMBH"})


def _tidy_name(name: str) -> str:
    """ACME OFFICE SUPPLIES LTD reads better as Acme Office Supplies Ltd."""
    if not (name.isupper() and len(name) > 4):
        return name
    return " ".join(
        word if word.strip(".,") in _KEEP_UPPER else word.capitalize() for word in name.split()
    )


# --------------------------------------------------------------------------------------
# Tables
# --------------------------------------------------------------------------------------

_NOT_AN_ITEM = re.compile(
    r"\b(sub-?total|total|tax|vat|gst|shipping|discount|balance|amount due|due|payment|"
    r"invoice|date|bill to|ship to|"
    r"terms|description|qty|quantity|unit price|iban|account|swift|po number|reference)\b",
    re.I,
)


_NUMERIC_TOKEN = re.compile(rf"^[{_SYMBOLS}]?-?[\d,]+(?:\.\d+)?[{_SYMBOLS}]?$")


def line_items(text: str) -> list[dict[str, float | int | str]]:
    """Rows that read "description ... quantity ... unit price ... amount".

    The numeric columns are the run of number tokens at the end of the row, so numbers
    inside a description ("Standing desk (1.6m)") stay part of it.
    """
    items: list[dict[str, float | int | str]] = []
    for line in text.splitlines():
        tokens = line.strip(" -*\t|").split()
        values: list[float | int] = []
        while tokens and _NUMERIC_TOKEN.match(tokens[-1]):
            value = parse_number(tokens.pop().strip("".join(CURRENCY_SYMBOLS)))
            if value is None:
                break
            values.insert(0, value)
        while tokens and tokens[-1].lower() in {"x", "@", "=", "|", "-"}:
            tokens.pop()
        description = " ".join(tokens).strip(" -:|")
        if not values or len(description) < 3 or not re.search(r"[A-Za-z]", description):
            continue
        if _NOT_AN_ITEM.search(description):
            continue
        amount = values[-1]
        qty: float | int = 1
        unit: float | int = amount
        if len(values) >= 3:
            qty, unit = values[0], values[-2]
        elif len(values) == 2 and isinstance(values[0], int) and 0 < values[0] < 1000:
            # Two numbers read as quantity and line amount.
            qty, unit = values[0], amount / values[0]
        elif len(values) == 2:
            unit = values[0]
        items.append(
            {
                "description": description,
                "quantity": qty,
                "unit_price": round(float(unit), 2),
                "amount": amount,
            }
        )
    return items


# --------------------------------------------------------------------------------------
# Fields by name
# --------------------------------------------------------------------------------------


def _words(name: str) -> set[str]:
    return set(content_terms(name.replace("_", " ")))


def lookup_field(fields: Mapping[str, str], name: str) -> str | None:
    """The value of the inline field whose label best matches a schema field name."""
    wanted = _words(name)
    if not wanted:
        return None
    best: tuple[float, str] | None = None
    for label, value in fields.items():
        have = _words(label)
        if not have:
            continue
        overlap = len(wanted & have)
        if not overlap:
            continue
        score = overlap / len(wanted | have)
        if best is None or score > best[0]:
            best = (score, value)
    return best[1] if best and best[0] >= 0.5 else None
