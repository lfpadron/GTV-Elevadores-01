"""Search orchestration services."""

from __future__ import annotations

from sqlite3 import Connection

from gtv.repositories import search as search_repo
from gtv.utils.text import excerpt_around_term


def run_structured_search(connection: Connection, filters: dict) -> list[dict]:
    return search_repo.search_documents(connection, filters)


def run_full_text_search(connection: Connection, filters: dict) -> tuple[list[dict], str | None]:
    rows, error = search_repo.search_document_pages(connection, filters)
    if error:
        return [], error
    term = filters.get("free_text", "")
    results: list[dict] = []
    for row in rows:
        row["snippet"] = excerpt_around_term(row.get("page_text", ""), term)
        results.append(row)
    return results, None
