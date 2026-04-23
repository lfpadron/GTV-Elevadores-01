"""Notification history queries."""

from __future__ import annotations

from sqlite3 import Connection


def create_notification(
    connection: Connection,
    *,
    notification_type: str,
    recipient_email: str,
    recipient_user_id: int | None,
    subject: str,
    body_preview: str,
    related_entity_type: str | None = None,
    related_entity_id: int | None = None,
    status: str = "enviada",
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO notifications (
            notification_type,
            recipient_email,
            recipient_user_id,
            related_entity_type,
            related_entity_id,
            subject,
            body_preview,
            status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            notification_type,
            recipient_email,
            recipient_user_id,
            related_entity_type,
            related_entity_id,
            subject,
            body_preview,
            status,
        ),
    )
    return int(cursor.lastrowid)


def mark_notification_read(connection: Connection, notification_id: int) -> None:
    connection.execute(
        """
        UPDATE notifications
        SET status = CASE WHEN status = 'enviada' THEN 'leida' ELSE status END,
            read_at = COALESCE(read_at, CURRENT_TIMESTAMP)
        WHERE id = ?
        """,
        (notification_id,),
    )


def mark_notification_resolved(connection: Connection, notification_id: int) -> None:
    connection.execute(
        """
        UPDATE notifications
        SET status = 'resuelta',
            resolved_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (notification_id,),
    )


def list_notifications_for_user(connection: Connection, email: str, limit: int = 100) -> list[dict]:
    rows = connection.execute(
        """
        SELECT *
        FROM notifications
        WHERE recipient_email = ?
        ORDER BY
            CASE WHEN status IN ('enviada', 'leida') THEN 0 ELSE 1 END,
            sent_at DESC
        LIMIT ?
        """,
        (email.lower(), limit),
    ).fetchall()
    return [dict(row) for row in rows]


def list_admin_request_notifications(connection: Connection, admin_email: str) -> list[dict]:
    rows = connection.execute(
        """
        SELECT n.*, ar.status AS request_status
        FROM notifications n
        LEFT JOIN access_requests ar
            ON n.related_entity_type = 'access_request'
           AND n.related_entity_id = ar.id
        WHERE n.recipient_email = ?
          AND n.notification_type = 'access_request_pending'
          AND COALESCE(ar.status, 'pendiente') = 'pendiente'
        ORDER BY n.sent_at DESC
        """,
        (admin_email.lower(),),
    ).fetchall()
    return [dict(row) for row in rows]
