"""Structured search and FTS helpers."""

from __future__ import annotations

from sqlite3 import Connection, OperationalError

from gtv.utils.equipment import EQUIPMENT_OTHER_FILTER_VALUE, catalog_equipment_codes, resolve_equipment_code_alias


ESTIMATE_CONCEPT_SUMMARY_SQL = """
COALESCE(
    (
        SELECT group_concat(concept_text, ' | ')
        FROM (
            SELECT ei2.concept_text AS concept_text
            FROM estimate_items ei2
            WHERE ei2.estimate_document_id = d.id
              AND COALESCE(ei2.concept_text, '') <> ''
            ORDER BY ei2.line_number ASC
            LIMIT 3
        ) concept_rows
    ),
    ''
)
"""

SOURCE_REFERENCE_SQL = """
CASE
    WHEN d.document_type = 'reporte' THEN COALESCE(fr.ticket_number, d.primary_identifier, '')
    WHEN d.document_type = 'hallazgo' THEN COALESCE(fi.base_ticket_number, fi.finding_folio, d.primary_identifier, '')
    WHEN d.document_type = 'estimacion' THEN COALESCE(es.normalized_folio, es.original_folio, d.primary_identifier, '')
    ELSE COALESCE(d.primary_identifier, '')
END
"""

CAUSE_TEXT_SQL = """
CASE
    WHEN d.document_type = 'reporte' THEN COALESCE(fr.cause_text, fr.description, d.short_description, '')
    WHEN d.document_type = 'hallazgo' THEN COALESCE(fi.description, fi.affected_part_text, d.short_description, '')
    WHEN d.document_type = 'estimacion' THEN COALESCE(d.summary_user_edited, d.summary_ai_original, d.short_description, '')
    ELSE COALESCE(d.short_description, '')
END
"""

RECOMMENDATION_TEXT_SQL = f"""
CASE
    WHEN d.document_type = 'reporte' THEN COALESCE(fr.solution_text, '')
    WHEN d.document_type = 'hallazgo' THEN COALESCE(fi.recommendation_text, '')
    WHEN d.document_type = 'estimacion' THEN {ESTIMATE_CONCEPT_SUMMARY_SQL}
    ELSE ''
END
"""


def search_documents(connection: Connection, filters: dict) -> list[dict]:
    include_documents = filters.get("document_type") in (None, "", "reporte", "hallazgo", "estimacion")
    include_user_tickets = filters.get("document_type") in (None, "", "ticket_usuario")

    rows: list[dict] = []
    if include_documents:
        rows.extend(_search_document_rows(connection, filters))
    if include_user_tickets and filters.get("inclusion_status") != "ignorado":
        rows.extend(_search_user_ticket_rows(connection, filters))

    rows.sort(
        key=lambda row: (
            row.get("document_date") or "",
            row.get("document_time") or "",
            row.get("record_key") or "",
        ),
        reverse=True,
    )
    return rows


def search_document_pages(connection: Connection, filters: dict) -> tuple[list[dict], str | None]:
    include_documents = filters.get("document_type") in (None, "", "reporte", "hallazgo", "estimacion")
    include_user_tickets = filters.get("document_type") in (None, "", "ticket_usuario")

    rows: list[dict] = []
    error: str | None = None
    if include_documents:
        try:
            rows.extend(_search_document_page_rows(connection, filters))
        except OperationalError as exc:
            error = str(exc)
    if include_user_tickets and filters.get("inclusion_status") != "ignorado":
        rows.extend(_search_user_ticket_page_rows(connection, filters))

    rows.sort(
        key=lambda row: (
            row.get("document_date") or "",
            row.get("page_number") or 0,
            row.get("record_key") or "",
        ),
        reverse=True,
    )
    return rows, error


def _search_document_rows(connection: Connection, filters: dict) -> list[dict]:
    clauses = ["1 = 1"]
    params: list[object] = []
    _apply_document_common_filters(clauses, params, filters)

    rows = connection.execute(
        f"""
        SELECT
            'document:' || d.id AS record_key,
            d.id AS document_id,
            NULL AS user_ticket_id,
            d.document_type,
            d.storage_path,
            {SOURCE_REFERENCE_SQL} AS source_reference,
            d.primary_identifier,
            d.document_date,
            d.document_time,
            d.tower,
            p.name AS position_name,
            d.equipment_text_original,
            d.equipment_code,
            d.inclusion_status,
            COALESCE(fr.report_state, fi.finding_state, es.estimate_state, '') AS current_state,
            {CAUSE_TEXT_SQL} AS cause_text,
            {RECOMMENDATION_TEXT_SQL} AS recommendation_text,
            d.short_description,
            COALESCE(d.summary_user_edited, d.summary_ai_original, d.short_description, '') AS detail_summary,
            CASE
                WHEN d.document_type = 'reporte' THEN COALESCE(fr.description, d.short_description, '')
                WHEN d.document_type = 'hallazgo' THEN COALESCE(fi.description, d.short_description, '')
                WHEN d.document_type = 'estimacion' THEN COALESCE(d.summary_user_edited, d.summary_ai_original, d.short_description, es.original_folio, '')
                ELSE COALESCE(d.short_description, '')
            END AS concise_description,
            d.file_name_original,
            d.file_name_original AS preview_file_name
        FROM documents d
        LEFT JOIN positions p ON p.id = d.position_id
        LEFT JOIN fault_reports fr ON fr.document_id = d.id
        LEFT JOIN findings fi ON fi.document_id = d.id
        LEFT JOIN estimates es ON es.document_id = d.id
        WHERE {" AND ".join(clauses)}
        ORDER BY d.document_date DESC, d.document_time DESC, d.id DESC
        LIMIT 300
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def _search_user_ticket_rows(connection: Connection, filters: dict) -> list[dict]:
    clauses = ["1 = 1"]
    params: list[object] = []
    _apply_user_ticket_common_filters(clauses, params, filters, text_key="ticket_or_identifier")

    rows = connection.execute(
        f"""
        SELECT
            'user_ticket:' || ut.id AS record_key,
            ut.source_document_id AS document_id,
            ut.id AS user_ticket_id,
            'ticket_usuario' AS document_type,
            sd.storage_path,
            ut.ticket_folio AS source_reference,
            ut.ticket_folio AS primary_identifier,
            ut.document_date,
            ut.document_time,
            ut.tower,
            NULL AS position_name,
            ut.equipment_text_original,
            ut.equipment_code,
            'incluido' AS inclusion_status,
            ut.ticket_state AS current_state,
            ut.description AS cause_text,
            COALESCE(ut.observations, '') AS recommendation_text,
            ut.description AS short_description,
            COALESCE(ut.observations, ut.description, '') AS detail_summary,
            ut.description AS concise_description,
            COALESCE(sd.file_name_original, ut.ticket_folio) AS file_name_original,
            COALESCE(sd.file_name_original, ut.ticket_folio) AS preview_file_name
        FROM user_tickets ut
        LEFT JOIN documents sd ON sd.id = ut.source_document_id
        WHERE {" AND ".join(clauses)}
        ORDER BY ut.document_date DESC, ut.document_time DESC, ut.id DESC
        LIMIT 300
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def _search_document_page_rows(connection: Connection, filters: dict) -> list[dict]:
    clauses = ["document_pages_fts MATCH ?"]
    params: list[object] = [filters["free_text"]]
    _apply_document_common_filters(clauses, params, filters)

    rows = connection.execute(
        f"""
        SELECT
            'document:' || d.id || ':' || dp.page_number AS record_key,
            d.id AS document_id,
            NULL AS user_ticket_id,
            d.file_name_original,
            d.storage_path,
            dp.page_number,
            dp.page_text,
            d.document_type,
            d.document_date,
            d.document_time,
            d.inclusion_status,
            d.primary_identifier,
            {SOURCE_REFERENCE_SQL} AS source_reference,
            {CAUSE_TEXT_SQL} AS cause_text,
            {RECOMMENDATION_TEXT_SQL} AS recommendation_text
        FROM document_pages_fts
        JOIN document_pages dp
          ON dp.document_id = document_pages_fts.document_id
         AND dp.page_number = document_pages_fts.page_number
        JOIN documents d ON d.id = dp.document_id
        LEFT JOIN positions p ON p.id = d.position_id
        LEFT JOIN fault_reports fr ON fr.document_id = d.id
        LEFT JOIN findings fi ON fi.document_id = d.id
        LEFT JOIN estimates es ON es.document_id = d.id
        WHERE {" AND ".join(clauses)}
        ORDER BY d.document_date DESC, dp.page_number ASC
        LIMIT 100
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def _search_user_ticket_page_rows(connection: Connection, filters: dict) -> list[dict]:
    clauses = ["1 = 1"]
    params: list[object] = []
    _apply_user_ticket_common_filters(clauses, params, filters, text_key="free_text")

    rows = connection.execute(
        f"""
        SELECT
            'user_ticket:' || ut.id || ':0' AS record_key,
            ut.source_document_id AS document_id,
            ut.id AS user_ticket_id,
            COALESCE(sd.file_name_original, ut.ticket_folio) AS file_name_original,
            sd.storage_path,
            0 AS page_number,
            trim(
                COALESCE(ut.description, '') || ' ' ||
                COALESCE(ut.observations, '') || ' ' ||
                COALESCE(ut.original_report_reference, '') || ' ' ||
                COALESCE(ut.original_finding_reference, '') || ' ' ||
                COALESCE(ut.original_estimate_reference, '')
            ) AS page_text,
            'ticket_usuario' AS document_type,
            ut.document_date,
            ut.document_time,
            'incluido' AS inclusion_status,
            ut.ticket_folio AS primary_identifier,
            ut.ticket_folio AS source_reference,
            ut.description AS cause_text,
            COALESCE(ut.observations, '') AS recommendation_text
        FROM user_tickets ut
        LEFT JOIN documents sd ON sd.id = ut.source_document_id
        WHERE {" AND ".join(clauses)}
        ORDER BY ut.document_date DESC, ut.document_time DESC, ut.id DESC
        LIMIT 100
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def _apply_document_common_filters(clauses: list[str], params: list[object], filters: dict) -> None:
    if filters.get("date_from"):
        clauses.append("d.document_date >= ?")
        params.append(filters["date_from"])
    if filters.get("date_to"):
        clauses.append("d.document_date <= ?")
        params.append(filters["date_to"])
    if filters.get("ticket_or_identifier"):
        clauses.append(
            """
            (
                COALESCE(fr.ticket_number, '') LIKE ?
                OR COALESCE(fi.base_ticket_number, '') LIKE ?
                OR COALESCE(fi.finding_folio, '') LIKE ?
                OR COALESCE(es.original_folio, '') LIKE ?
                OR COALESCE(es.normalized_folio, '') LIKE ?
                OR COALESCE(d.primary_identifier, '') LIKE ?
            )
            """
        )
        needle = f"%{filters['ticket_or_identifier']}%"
        params.extend([needle] * 6)
    if filters.get("tower"):
        clauses.append("COALESCE(d.tower, '') = ?")
        params.append(filters["tower"])
    if filters.get("equipment"):
        if filters["equipment"] == EQUIPMENT_OTHER_FILTER_VALUE:
            known_codes = [code.upper() for code in catalog_equipment_codes()]
            placeholders = ", ".join("?" for _ in known_codes)
            clauses.append(
                f"""
                (
                    NULLIF(COALESCE(d.equipment_code, ''), '') IS NULL
                    OR UPPER(COALESCE(d.equipment_code, '')) NOT IN ({placeholders})
                )
                """
            )
            params.extend(known_codes)
        else:
            resolved_code = resolve_equipment_code_alias(filters["equipment"])
            if resolved_code:
                clauses.append("COALESCE(d.equipment_code, d.equipment_key, '') = ?")
                params.append(resolved_code)
            else:
                clauses.append(
                    """
                    (
                        COALESCE(d.equipment_text_original, '') LIKE ?
                        OR COALESCE(d.equipment_key, '') LIKE ?
                        OR COALESCE(d.equipment_code, '') LIKE ?
                    )
                    """
                )
                params.extend([f"%{filters['equipment']}%"] * 3)
    if filters.get("document_type"):
        clauses.append("d.document_type = ?")
        params.append(filters["document_type"])
    if filters.get("inclusion_status"):
        clauses.append("COALESCE(d.inclusion_status, 'incluido') = ?")
        params.append(filters["inclusion_status"])


def _apply_user_ticket_common_filters(
    clauses: list[str],
    params: list[object],
    filters: dict,
    *,
    text_key: str,
) -> None:
    if filters.get("date_from"):
        clauses.append("ut.document_date >= ?")
        params.append(filters["date_from"])
    if filters.get("date_to"):
        clauses.append("ut.document_date <= ?")
        params.append(filters["date_to"])
    if filters.get("tower"):
        clauses.append("COALESCE(ut.tower, '') = ?")
        params.append(filters["tower"])
    if filters.get("equipment"):
        if filters["equipment"] == EQUIPMENT_OTHER_FILTER_VALUE:
            known_codes = [code.upper() for code in catalog_equipment_codes()]
            placeholders = ", ".join("?" for _ in known_codes)
            clauses.append(
                f"""
                (
                    NULLIF(COALESCE(ut.equipment_code, ''), '') IS NULL
                    OR UPPER(COALESCE(ut.equipment_code, '')) NOT IN ({placeholders})
                )
                """
            )
            params.extend(known_codes)
        else:
            resolved_code = resolve_equipment_code_alias(filters["equipment"])
            if resolved_code:
                clauses.append("COALESCE(ut.equipment_code, '') = ?")
                params.append(resolved_code)
            else:
                clauses.append(
                    """
                    (
                        COALESCE(ut.equipment_text_original, '') LIKE ?
                        OR COALESCE(ut.equipment_code, '') LIKE ?
                    )
                    """
                )
                params.extend([f"%{filters['equipment']}%"] * 2)
    if filters.get(text_key):
        needle = f"%{filters[text_key]}%"
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
