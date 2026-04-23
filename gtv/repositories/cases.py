"""Case persistence and suggestion queries."""

from __future__ import annotations

from datetime import datetime
from sqlite3 import Connection


def _next_daily_sequence(connection: Connection, case_date: str) -> int:
    row = connection.execute(
        "SELECT last_value FROM case_daily_counters WHERE counter_date = ?",
        (case_date,),
    ).fetchone()
    next_value = 1 if not row else int(row["last_value"]) + 1
    connection.execute(
        """
        INSERT INTO case_daily_counters (counter_date, last_value)
        VALUES (?, ?)
        ON CONFLICT(counter_date) DO UPDATE SET last_value = excluded.last_value
        """,
        (case_date, next_value),
    )
    return next_value


def generate_case_folio(connection: Connection, case_date: str) -> str:
    sequence = _next_daily_sequence(connection, case_date)
    parsed = datetime.fromisoformat(case_date)
    return f"CASO-{parsed:%Y-%m-%d}-{sequence:04d}"


def create_case(
    connection: Connection,
    *,
    equipment_key: str,
    tower: str | None,
    position_id: int | None,
    equipment_text_original: str | None,
    origin_document_id: int | None,
    anchor_date: str | None,
    suggested_consolidated_status: str,
    manual_consolidated_status: str | None,
    created_by_user_id: int | None,
) -> int:
    case_date = anchor_date or datetime.now().date().isoformat()
    case_folio = generate_case_folio(connection, case_date)
    cursor = connection.execute(
        """
        INSERT INTO cases (
            case_folio,
            equipment_key,
            tower,
            position_id,
            equipment_text_original,
            origin_document_id,
            anchor_date,
            suggested_consolidated_status,
            manual_consolidated_status,
            created_by_user_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            case_folio,
            equipment_key,
            tower,
            position_id,
            equipment_text_original,
            origin_document_id,
            anchor_date,
            suggested_consolidated_status,
            manual_consolidated_status,
            created_by_user_id,
        ),
    )
    return int(cursor.lastrowid)


def get_case_by_id(connection: Connection, case_id: int) -> dict | None:
    row = connection.execute(
        """
        SELECT c.*, p.name AS position_name
        FROM cases c
        LEFT JOIN positions p ON p.id = c.position_id
        WHERE c.id = ?
        """,
        (case_id,),
    ).fetchone()
    return dict(row) if row else None


def list_cases(connection: Connection) -> list[dict]:
    rows = connection.execute(
        """
        SELECT
            c.*,
            p.name AS position_name,
            COUNT(DISTINCT cd.document_id) AS linked_documents,
            od.file_name_original AS source_file_name,
            od.document_type AS source_document_type,
            CASE
                WHEN od.document_type = 'reporte' THEN COALESCE(fr.ticket_number, od.primary_identifier, '')
                WHEN od.document_type = 'hallazgo' THEN COALESCE(fi.base_ticket_number, fi.finding_folio, od.primary_identifier, '')
                WHEN od.document_type = 'estimacion' THEN COALESCE(es.normalized_folio, es.original_folio, od.primary_identifier, '')
                ELSE COALESCE(od.primary_identifier, '')
            END AS source_reference
        FROM cases c
        LEFT JOIN positions p ON p.id = c.position_id
        LEFT JOIN case_documents cd ON cd.case_id = c.id
        LEFT JOIN documents od ON od.id = c.origin_document_id
        LEFT JOIN fault_reports fr ON fr.document_id = od.id
        LEFT JOIN findings fi ON fi.document_id = od.id
        LEFT JOIN estimates es ON es.document_id = od.id
        GROUP BY c.id
        ORDER BY c.created_at DESC, c.id DESC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def find_candidate_cases(
    connection: Connection,
    *,
    equipment_key: str,
    document_date: str,
    max_days: int = 15,
) -> list[dict]:
    rows = connection.execute(
        """
        SELECT
            c.*,
            ABS(CAST(julianday(c.anchor_date) - julianday(?) AS INTEGER)) AS days_difference,
            p.name AS position_name
        FROM cases c
        LEFT JOIN positions p ON p.id = c.position_id
        WHERE c.equipment_key = ?
          AND c.anchor_date IS NOT NULL
          AND ABS(CAST(julianday(c.anchor_date) - julianday(?) AS INTEGER)) <= ?
        ORDER BY days_difference ASC, c.id DESC
        """,
        (document_date, equipment_key, document_date, max_days),
    ).fetchall()
    return [dict(row) for row in rows]


def update_case_manual_status(connection: Connection, case_id: int, manual_status: str | None) -> None:
    connection.execute(
        """
        UPDATE cases
        SET manual_consolidated_status = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (manual_status, case_id),
    )
