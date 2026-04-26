"""Persistence helpers for manually created user tickets."""

from __future__ import annotations

from datetime import datetime
from sqlite3 import Connection


def generate_user_ticket_folio(connection: Connection, document_date: str | None) -> str:
    effective_date = document_date or datetime.now().date().isoformat()
    row = connection.execute(
        """
        SELECT COUNT(*) AS total
        FROM user_tickets
        WHERE document_date = ?
        """,
        (effective_date,),
    ).fetchone()
    sequence = int(row["total"] or 0) + 1
    parsed = datetime.fromisoformat(effective_date)
    return f"TU-{parsed:%Y-%m-%d}-{sequence:04d}"


def create_user_ticket(
    connection: Connection,
    *,
    document_date: str,
    document_time: str | None,
    tower: str | None,
    equipment_code: str | None,
    equipment_text_original: str | None,
    description: str,
    ticket_state: str,
    observations: str | None,
    source_document_id: int | None,
    original_report_reference: str | None,
    original_finding_reference: str | None,
    original_estimate_reference: str | None,
    created_by_user_id: int | None,
) -> int:
    ticket_folio = generate_user_ticket_folio(connection, document_date)
    cursor = connection.execute(
        """
        INSERT INTO user_tickets (
            ticket_folio,
            document_date,
            document_time,
            tower,
            equipment_code,
            equipment_text_original,
            description,
            ticket_state,
            observations,
            source_document_id,
            original_report_reference,
            original_finding_reference,
            original_estimate_reference,
            created_by_user_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ticket_folio,
            document_date,
            document_time,
            tower,
            equipment_code,
            equipment_text_original,
            description,
            ticket_state,
            observations,
            source_document_id,
            original_report_reference,
            original_finding_reference,
            original_estimate_reference,
            created_by_user_id,
        ),
    )
    return int(cursor.lastrowid)


def get_user_ticket(connection: Connection, user_ticket_id: int) -> dict | None:
    row = connection.execute(
        """
        SELECT
            ut.*,
            d.file_name_original AS source_document_name,
            d.document_type AS source_document_type,
            d.document_date AS source_document_date
        FROM user_tickets ut
        LEFT JOIN documents d ON d.id = ut.source_document_id
        WHERE ut.id = ?
        """,
        (user_ticket_id,),
    ).fetchone()
    return dict(row) if row else None


def list_user_tickets(connection: Connection, filters: dict | None = None) -> list[dict]:
    active_filters = filters or {}
    clauses = ["1 = 1"]
    params: list[object] = []
    if active_filters.get("date_from"):
        clauses.append("ut.document_date >= ?")
        params.append(active_filters["date_from"])
    if active_filters.get("date_to"):
        clauses.append("ut.document_date <= ?")
        params.append(active_filters["date_to"])
    if active_filters.get("tower"):
        clauses.append("COALESCE(ut.tower, '') = ?")
        params.append(active_filters["tower"])
    if active_filters.get("equipment_code"):
        clauses.append("COALESCE(ut.equipment_code, '') = ?")
        params.append(active_filters["equipment_code"])
    if active_filters.get("ticket_state"):
        clauses.append("ut.ticket_state = ?")
        params.append(active_filters["ticket_state"])
    if active_filters.get("source_document_id"):
        clauses.append("ut.source_document_id = ?")
        params.append(active_filters["source_document_id"])
    if active_filters.get("free_text"):
        needle = f"%{active_filters['free_text']}%"
        clauses.append(
            """
            (
                COALESCE(ut.ticket_folio, '') LIKE ?
                OR COALESCE(ut.description, '') LIKE ?
                OR COALESCE(ut.observations, '') LIKE ?
                OR COALESCE(ut.original_report_reference, '') LIKE ?
                OR COALESCE(ut.original_finding_reference, '') LIKE ?
                OR COALESCE(ut.original_estimate_reference, '') LIKE ?
            )
            """
        )
        params.extend([needle] * 6)

    rows = connection.execute(
        f"""
        SELECT
            ut.*,
            d.file_name_original AS source_document_name,
            d.document_type AS source_document_type,
            d.document_date AS source_document_date,
            c.case_folio
        FROM user_tickets ut
        LEFT JOIN documents d ON d.id = ut.source_document_id
        LEFT JOIN case_user_tickets cut ON cut.user_ticket_id = ut.id
        LEFT JOIN cases c ON c.id = cut.case_id
        WHERE {" AND ".join(clauses)}
        ORDER BY ut.document_date DESC, ut.document_time DESC, ut.id DESC
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def update_user_ticket_fields(connection: Connection, user_ticket_id: int, payload: dict) -> None:
    assignments = ", ".join(f"{column} = ?" for column in payload)
    connection.execute(
        f"""
        UPDATE user_tickets
        SET {assignments},
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (*payload.values(), user_ticket_id),
    )


def link_user_ticket_to_case(
    connection: Connection,
    *,
    case_id: int,
    user_ticket_id: int,
    linked_by_user_id: int | None,
    notes: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO case_user_tickets (
            case_id,
            user_ticket_id,
            linked_by_user_id,
            notes
        )
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_ticket_id) DO UPDATE SET
            case_id = excluded.case_id,
            linked_by_user_id = excluded.linked_by_user_id,
            linked_at = CURRENT_TIMESTAMP,
            notes = excluded.notes
        """,
        (case_id, user_ticket_id, linked_by_user_id, notes),
    )


def list_case_user_tickets(connection: Connection, case_id: int) -> list[dict]:
    rows = connection.execute(
        """
        SELECT ut.*, d.file_name_original AS source_document_name
        FROM case_user_tickets cut
        JOIN user_tickets ut ON ut.id = cut.user_ticket_id
        LEFT JOIN documents d ON d.id = ut.source_document_id
        WHERE cut.case_id = ?
        ORDER BY ut.document_date, ut.document_time, ut.id
        """,
        (case_id,),
    ).fetchall()
    return [dict(row) for row in rows]
