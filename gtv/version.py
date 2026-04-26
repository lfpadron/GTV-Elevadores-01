"""Application version metadata shown in the UI."""

from __future__ import annotations

APP_VERSION_PUBLISHED_AT = "2026-04-26 16:22"


def version_display_text() -> str:
    return f"Fecha de versión: {APP_VERSION_PUBLISHED_AT}"
