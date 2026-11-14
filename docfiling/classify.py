"""Classification: document type, expiry date, property, company, counterparty.

Everything here is driven by the rules and matching dictionaries passed in (loaded
from the database by params.py) and returns plain values, so it can be tested
without a database.
"""

import re
from datetime import date
from typing import NamedTuple, Optional

UNCLASSIFIED = "Unclassified"

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

NUMERIC_DATE = r"\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}"
WORDED_DATE = (
    r"\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?[A-Za-z]{3,9}\.?,?\s+\d{4}"
)
DATE_RE = re.compile(f"({NUMERIC_DATE}|{WORDED_DATE})", re.IGNORECASE)


class Classification(NamedTuple):
    document_type: str
    score: float
    runner_up_score: float


class Analysis(NamedTuple):
    document_type: str
    score: float
    expiry_date: Optional[date]
    document_date: Optional[date]
    property_id: Optional[int]
    property_name: Optional[str]
    company_code: Optional[str]
    counterparty: Optional[str]


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------
def parse_date(raw: str) -> Optional[date]:
    """Parse a UK day-first date string. Returns None if it is not a real date."""
    raw = raw.strip().rstrip(",.")
    numeric = re.fullmatch(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})", raw)
    try:
        if numeric:
            day, month, year = (int(g) for g in numeric.groups())
            if year < 100:
                year += 2000
            return date(year, month, day)
        worded = re.fullmatch(
            r"(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?([A-Za-z]{3,9})\.?,?\s+(\d{4})",
            raw,
            re.IGNORECASE,
        )
        if worded:
            day, name, year = worded.groups()
            month = MONTHS.get(name[:3].lower())
            if month:
                return date(int(year), month, int(day))
    except ValueError:
        return None
    return None


def _dates_in(text: str):
    found = []
    for match in DATE_RE.finditer(text):
        parsed = parse_date(match.group(1))
        if parsed and 1990 <= parsed.year <= 2100:
            found.append(parsed)
    return found


def find_expiry(text: str, rules: dict) -> Optional[date]:
    lowered = text.lower()
    for entry in rules["expiry_keywords"]:
        position = lowered.find(entry["phrase"])
        if position < 0:
            continue
        window = text[position + len(entry["phrase"]): position + len(entry["phrase"]) + 90]
        dates = _dates_in(window)
        if dates:
            return dates[-1] if entry["pick"] == "last" else dates[0]
    return None


def find_document_date(text: str, rules: dict) -> Optional[date]:
    lowered = text.lower()
    for phrase in rules["issue_keywords"]:
        position = lowered.find(phrase)
        if position < 0:
            continue
        dates = _dates_in(text[position + len(phrase): position + len(phrase) + 60])
        if dates:
            return dates[0]
    return None


# ---------------------------------------------------------------------------
# Type scoring
# ---------------------------------------------------------------------------
def classify_type(text: str, rules: dict, min_score: float, min_margin: float) -> Classification:
    lowered = text.lower()

    scores = {}
    for type_name, phrases in rules["types"].items():
        scores[type_name] = sum(w for phrase, w in phrases.items() if phrase in lowered)

    if not scores:
        return Classification(UNCLASSIFIED, 0, 0)
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_name, best = ranked[0]
    runner_up = ranked[1][1] if len(ranked) > 1 else 0

    if best < min_score or (best - runner_up) < min_margin:
        return Classification(UNCLASSIFIED, best, runner_up)
    return Classification(best_name, best, runner_up)


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------
def match_property(text: str, matching: dict):
    lowered = text.lower()
    best = None
    for prop in matching["properties"]:
        hits = sum(1 for kw in prop["keywords"] if kw.lower() in lowered)
        if hits and (best is None or hits > best[0]):
            best = (hits, prop)
    if best:
        return best[1]["id"], best[1]["name"]
    return None, None


def match_company(text: str, matching: dict) -> Optional[str]:
    lowered = text.lower()
    for code, names in matching["companies"].items():
        if any(name.lower() in lowered for name in names):
            return code
    return None


def match_counterparty(text: str, matching: dict) -> Optional[str]:
    lowered = text.lower()
    for name in matching["counterparties"]:
        if name.lower() in lowered:
            return name
    return None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def analyse(text: str, filename: str, rules: dict, matching: dict,
            min_score: float, min_margin: float) -> Analysis:
    searchable = f"{filename}\n{text}"
    result = classify_type(searchable, rules, min_score, min_margin)
    property_id, property_name = match_property(text, matching)

    return Analysis(
        document_type=result.document_type,
        score=result.score,
        expiry_date=find_expiry(text, rules),
        document_date=find_document_date(text, rules),
        property_id=property_id,
        property_name=property_name,
        company_code=match_company(text, matching),
        counterparty=match_counterparty(text, matching),
    )
