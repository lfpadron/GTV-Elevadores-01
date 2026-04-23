"""SQLite connection factory."""

from __future__ import annotations

import sqlite3

from gtv.config import Settings, get_settings


def get_connection(settings: Settings | None = None) -> sqlite3.Connection:
    active_settings = settings or get_settings(validate_secrets=False)
    connection = sqlite3.connect(active_settings.db_path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection
