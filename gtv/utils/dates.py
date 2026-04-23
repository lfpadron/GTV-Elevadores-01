"""Date and time normalization helpers."""

from __future__ import annotations

from datetime import datetime
import re

DATE_PATTERNS = [
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%Y-%m-%d",
    "%d.%m.%Y",
    "%d/%m/%y",
    "%d-%m-%y",
]

SPANISH_MONTHS = {
    "ene": 1,
    "feb": 2,
    "mar": 3,
    "abr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "ago": 8,
    "sep": 9,
    "set": 9,
    "oct": 10,
    "nov": 11,
    "dic": 12,
}


def parse_date(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip()
    spanish_date = parse_spanish_date(cleaned)
    if spanish_date:
        return spanish_date
    for pattern in DATE_PATTERNS:
        try:
            parsed = datetime.strptime(cleaned, pattern)
            return parsed.date().isoformat()
        except ValueError:
            continue
    return None


def parse_spanish_date(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(
        r"\b(\d{1,2})\s+([A-Za-záéíóúü]+)\s+(\d{2,4})\b",
        value.strip(),
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    day = int(match.group(1))
    month_label = match.group(2).strip().lower()[:3]
    month = SPANISH_MONTHS.get(month_label)
    if not month:
        return None
    year = int(match.group(3))
    if year < 100:
        year += 2000
    try:
        return datetime(year, month, day).date().isoformat()
    except ValueError:
        return None


def normalize_time(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"\s+", " ", value.strip())
    for pattern in ("%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M:%S %p"):
        try:
            parsed = datetime.strptime(cleaned.upper(), pattern)
            return parsed.strftime("%H:%M:%S")
        except ValueError:
            continue
    if re.fullmatch(r"\d{1,2}:\d{2}", cleaned):
        return f"{cleaned}:00"
    return None


def today_iso() -> str:
    return datetime.now().date().isoformat()


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def days_between(date_a: str | None, date_b: str | None) -> int | None:
    if not date_a or not date_b:
        return None
    try:
        first = datetime.fromisoformat(date_a).date()
        second = datetime.fromisoformat(date_b).date()
    except ValueError:
        return None
    return abs((second - first).days)
