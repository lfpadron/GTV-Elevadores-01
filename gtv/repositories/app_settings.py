"""Application settings persistence helpers."""

from __future__ import annotations

from sqlite3 import Connection


def get_setting(connection: Connection, setting_key: str) -> str | None:
    row = connection.execute(
        """
        SELECT setting_value
        FROM app_settings
        WHERE setting_key = ?
        """,
        (setting_key,),
    ).fetchone()
    return str(row["setting_value"]) if row else None


def get_setting_int(connection: Connection, setting_key: str, default: int) -> int:
    raw_value = get_setting(connection, setting_key)
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return default


def upsert_setting(connection: Connection, setting_key: str, setting_value: str) -> None:
    connection.execute(
        """
        INSERT INTO app_settings (setting_key, setting_value)
        VALUES (?, ?)
        ON CONFLICT(setting_key) DO UPDATE SET
            setting_value = excluded.setting_value,
            updated_at = CURRENT_TIMESTAMP
        """,
        (setting_key, setting_value),
    )
