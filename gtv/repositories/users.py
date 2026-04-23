"""User, access-request, OTP and session persistence."""

from __future__ import annotations

from sqlite3 import Connection


def get_user_by_email(connection: Connection, email: str) -> dict | None:
    row = connection.execute(
        "SELECT * FROM users WHERE email = ?",
        (email.lower(),),
    ).fetchone()
    return dict(row) if row else None


def get_user_by_id(connection: Connection, user_id: int) -> dict | None:
    row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def list_users(connection: Connection) -> list[dict]:
    rows = connection.execute(
        """
        SELECT *
        FROM users
        ORDER BY
            CASE role WHEN 'semilla_admin' THEN 0 ELSE 1 END,
            full_name,
            email
        """
    ).fetchall()
    return [dict(row) for row in rows]


def create_pending_user(connection: Connection, *, email: str, full_name: str) -> int:
    cursor = connection.execute(
        """
        INSERT INTO users (email, full_name, preferred_name, role, status, is_seed)
        VALUES (?, ?, ?, 'usuario', 'pendiente_aprobacion', 0)
        """,
        (email.lower(), full_name.strip(), _default_preferred_name(full_name, email)),
    )
    return int(cursor.lastrowid)


def create_access_request(
    connection: Connection,
    *,
    user_id: int,
    email: str,
    requested_name: str,
    requested_preferred_name: str | None = None,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO access_requests (user_id, email, requested_name, requested_preferred_name)
        VALUES (?, ?, ?, ?)
        """,
        (
            user_id,
            email.lower(),
            requested_name.strip(),
            (requested_preferred_name or _default_preferred_name(requested_name, email)).strip(),
        ),
    )
    return int(cursor.lastrowid)


def get_pending_access_request_for_user(connection: Connection, user_id: int) -> dict | None:
    row = connection.execute(
        """
        SELECT *
        FROM access_requests
        WHERE user_id = ?
          AND status = 'pendiente'
        ORDER BY requested_at DESC
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()
    return dict(row) if row else None


def list_pending_access_requests(connection: Connection) -> list[dict]:
    rows = connection.execute(
        """
        SELECT ar.*, u.full_name, u.status AS user_status
        FROM access_requests ar
        JOIN users u ON u.id = ar.user_id
        WHERE ar.status = 'pendiente'
        ORDER BY ar.requested_at ASC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def resolve_access_request(
    connection: Connection,
    *,
    request_id: int,
    resolver_user_id: int,
    approved: bool,
    notes: str | None = None,
) -> dict | None:
    request_row = connection.execute(
        "SELECT * FROM access_requests WHERE id = ?",
        (request_id,),
    ).fetchone()
    if not request_row:
        return None
    request = dict(request_row)
    if request["status"] != "pendiente":
        return request

    request_status = "aprobada" if approved else "rechazada"
    user_status = "activo" if approved else "rechazado"

    connection.execute(
        """
        UPDATE access_requests
        SET status = ?,
            resolved_at = CURRENT_TIMESTAMP,
            resolved_by_user_id = ?,
            resolution_notes = ?
        WHERE id = ?
        """,
        (request_status, resolver_user_id, notes, request_id),
    )

    if approved:
        connection.execute(
            """
            UPDATE users
            SET status = 'activo',
                preferred_name = COALESCE(NULLIF(?, ''), preferred_name),
                approved_at = CURRENT_TIMESTAMP,
                approved_by_user_id = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (request.get("requested_preferred_name"), resolver_user_id, request["user_id"]),
        )
    else:
        connection.execute(
            """
            UPDATE users
            SET status = 'rechazado',
                rejected_at = CURRENT_TIMESTAMP,
                rejected_by_user_id = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (resolver_user_id, request["user_id"]),
        )

    request["status"] = request_status
    request["resolved_by_user_id"] = resolver_user_id
    request["resolved_user_status"] = user_status
    return request


def update_user_status(connection: Connection, user_id: int, status: str) -> None:
    connection.execute(
        """
        UPDATE users
        SET status = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (status, user_id),
    )


def invalidate_active_otps(connection: Connection, user_id: int) -> None:
    connection.execute(
        """
        UPDATE otp_codes
        SET is_active = 0,
            invalidated_at = CURRENT_TIMESTAMP
        WHERE user_id = ?
          AND is_active = 1
          AND consumed_at IS NULL
        """,
        (user_id,),
    )


def create_otp(
    connection: Connection,
    *,
    user_id: int,
    code_hash: str,
    expires_at: str,
    resend_available_at: str,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO otp_codes (
            user_id,
            code_hash,
            expires_at,
            resend_available_at
        )
        VALUES (?, ?, ?, ?)
        """,
        (user_id, code_hash, expires_at, resend_available_at),
    )
    return int(cursor.lastrowid)


def get_active_otp(connection: Connection, user_id: int) -> dict | None:
    row = connection.execute(
        """
        SELECT *
        FROM otp_codes
        WHERE user_id = ?
          AND is_active = 1
          AND consumed_at IS NULL
          AND invalidated_at IS NULL
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()
    return dict(row) if row else None


def increment_otp_attempts(connection: Connection, otp_id: int) -> None:
    connection.execute(
        """
        UPDATE otp_codes
        SET attempts_count = attempts_count + 1,
            is_active = CASE
                WHEN attempts_count + 1 >= max_attempts THEN 0
                ELSE is_active
            END
        WHERE id = ?
        """,
        (otp_id,),
    )


def consume_otp(connection: Connection, otp_id: int) -> None:
    connection.execute(
        """
        UPDATE otp_codes
        SET consumed_at = CURRENT_TIMESTAMP,
            is_active = 0
        WHERE id = ?
        """,
        (otp_id,),
    )


def create_session(connection: Connection, *, user_id: int, session_key: str, login_at: str) -> None:
    connection.execute(
        """
        INSERT INTO user_sessions (user_id, session_key, login_at, last_activity_at)
        VALUES (?, ?, ?, ?)
        """,
        (user_id, session_key, login_at, login_at),
    )
    connection.execute(
        """
        UPDATE users
        SET last_login_at = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (login_at, user_id),
    )


def touch_session(connection: Connection, session_key: str, activity_at: str) -> None:
    connection.execute(
        """
        UPDATE user_sessions
        SET last_activity_at = ?
        WHERE session_key = ?
          AND logout_at IS NULL
        """,
        (activity_at, session_key),
    )


def get_session(connection: Connection, session_key: str) -> dict | None:
    row = connection.execute(
        """
        SELECT *
        FROM user_sessions
        WHERE session_key = ?
        """,
        (session_key,),
    ).fetchone()
    return dict(row) if row else None


def close_session(connection: Connection, session_key: str, logout_at: str, reason: str) -> None:
    session_row = connection.execute(
        "SELECT * FROM user_sessions WHERE session_key = ?",
        (session_key,),
    ).fetchone()
    if not session_row:
        return
    session = dict(session_row)
    connection.execute(
        """
        UPDATE user_sessions
        SET logout_at = ?, logout_reason = ?
        WHERE session_key = ?
        """,
        (logout_at, reason, session_key),
    )
    connection.execute(
        """
        UPDATE users
        SET last_logout_at = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (logout_at, session["user_id"]),
    )


def _default_preferred_name(full_name: str, email: str) -> str:
    cleaned_name = full_name.strip()
    if cleaned_name:
        return cleaned_name.split()[0]
    return email.split("@", 1)[0]
