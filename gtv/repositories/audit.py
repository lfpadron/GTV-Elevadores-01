"""Audit trail persistence helpers."""

from __future__ import annotations

from sqlite3 import Connection


def log_change(
    connection: Connection,
    *,
    user_email: str,
    entity_type: str,
    entity_id: str,
    field_name: str,
    old_value: str | None,
    new_value: str | None,
    context: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO audit_logs (
            user_email,
            entity_type,
            entity_id,
            field_name,
            old_value,
            new_value,
            context
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (user_email, entity_type, entity_id, field_name, old_value, new_value, context),
    )


def list_audit_logs(connection: Connection, limit: int = 200) -> list[dict]:
    rows = connection.execute(
        """
        SELECT *
        FROM audit_logs
        ORDER BY event_at DESC, id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]
