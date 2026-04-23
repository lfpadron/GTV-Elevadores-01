"""Typed dataclasses used across the application."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class AuthenticatedUser:
    id: int
    email: str
    full_name: str
    preferred_name: str
    role: str
    status: str
    is_seed: bool


@dataclass(slots=True)
class SearchFilters:
    date_from: str | None = None
    date_to: str | None = None
    ticket_or_identifier: str | None = None
    tower: str | None = None
    position: str | None = None
    state: str | None = None
    free_text: str | None = None


@dataclass(slots=True)
class ExtractedDocument:
    document_type: str
    extraction_status: str
    document_date: str | None
    document_time: str | None
    tower: str | None
    position: str | None
    equipment_text: str | None
    equipment_code: str | None
    equipment_key: str | None
    primary_identifier: str | None
    summary_ai_original: str
    short_description: str
    raw_text: str
    total_pages: int
    detail_payload: dict[str, Any]
