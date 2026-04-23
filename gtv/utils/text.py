"""Text normalization, summaries and snippets."""

from __future__ import annotations

import re
import unicodedata


def normalize_pdf_text(text: str) -> str:
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", text)
    normalized = normalized.replace("\u00a0", " ")
    return normalized


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", normalize_pdf_text(text)).strip()


def normalize_for_match(text: str | None) -> str:
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    lowered = without_marks.lower()
    lowered = re.sub(r"[^a-z0-9 ]+", " ", lowered)
    return normalize_whitespace(lowered)


def first_non_empty(*values: str | None) -> str | None:
    for value in values:
        if value and value.strip():
            return value.strip()
    return None


def summarize_text(text: str, limit: int = 160) -> tuple[str, str]:
    cleaned = normalize_whitespace(text)
    if not cleaned:
        return "", ""
    sentence = re.split(r"(?<=[.!?])\s+", cleaned)[0]
    summary = sentence[:500].strip()
    short = cleaned[:limit].strip()
    return short, summary


def excerpt_around_term(text: str, term: str, before: int = 30, after: int = 30) -> str:
    normalized_text = text or ""
    if not normalized_text:
        return ""
    match = re.search(re.escape(term), normalized_text, flags=re.IGNORECASE)
    if not match:
        return normalized_text[: before + after + 10]
    start = max(0, match.start() - before)
    end = min(len(normalized_text), match.end() + after)

    while start > 0 and normalized_text[start] not in {" ", "\n"}:
        start -= 1
    while end < len(normalized_text) and normalized_text[end - 1] not in {" ", "\n"}:
        end += 1
        if end >= len(normalized_text):
            end = len(normalized_text)
            break

    return normalize_whitespace(normalized_text[start:end])
