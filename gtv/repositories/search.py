"""Structured search and FTS helpers."""

from __future__ import annotations

from sqlite3 import Connection, OperationalError

from gtv.utils.equipment import EQUIPMENT_OTHER_FILTER_VALUE, catalog_equipment_codes, resolve_equipment_code_alias


def search_documents(connection: Connection, filters: dict) -> list[dict]:
    clauses = ["1 = 1"]
    params: list[object] = []

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
    if filters.get("state"):
        clauses.append(
            """
            (
                COALESCE(fr.report_state, fi.finding_state, es.estimate_state, '') = ?
            )
            """
        )
        params.append(filters["state"])
    if filters.get("inclusion_status"):
        clauses.append("COALESCE(d.inclusion_status, 'incluido') = ?")
        params.append(filters["inclusion_status"])

    where_clause = " AND ".join(clauses)
    rows = connection.execute(
        f"""
        SELECT
            d.id AS document_id,
            d.document_type,
            d.storage_path,
            CASE
                WHEN d.document_type = 'reporte' THEN COALESCE(fr.ticket_number, d.primary_identifier, '')
                WHEN d.document_type = 'hallazgo' THEN COALESCE(fi.base_ticket_number, fi.finding_folio, d.primary_identifier, '')
                WHEN d.document_type = 'estimacion' THEN COALESCE(es.normalized_folio, es.original_folio, d.primary_identifier, '')
                ELSE COALESCE(d.primary_identifier, '')
            END AS source_reference,
            d.primary_identifier,
            d.document_date,
            d.document_time,
            d.tower,
            p.name AS position_name,
            d.equipment_text_original,
            d.equipment_code,
            d.inclusion_status,
            COALESCE(fr.report_state, fi.finding_state, es.estimate_state, '') AS current_state,
            d.short_description,
            COALESCE(d.summary_user_edited, d.summary_ai_original, d.short_description, '') AS detail_summary,
            CASE
                WHEN d.document_type = 'reporte' THEN COALESCE(fr.description, d.short_description, '')
                WHEN d.document_type = 'hallazgo' THEN COALESCE(fi.description, d.short_description, '')
                WHEN d.document_type = 'estimacion' THEN COALESCE(es.original_folio, d.short_description, '')
                ELSE COALESCE(d.short_description, '')
            END AS concise_description,
            d.file_name_original
        FROM documents d
        LEFT JOIN positions p ON p.id = d.position_id
        LEFT JOIN fault_reports fr ON fr.document_id = d.id
        LEFT JOIN findings fi ON fi.document_id = d.id
        LEFT JOIN estimates es ON es.document_id = d.id
        WHERE {where_clause}
        ORDER BY d.document_date DESC, d.document_time DESC, d.id DESC
        LIMIT 300
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def search_document_pages(connection: Connection, filters: dict) -> tuple[list[dict], str | None]:
    clauses = ["document_pages_fts MATCH ?"]
    params: list[object] = [filters["free_text"]]

    if filters.get("date_from"):
        clauses.append("d.document_date >= ?")
        params.append(filters["date_from"])
    if filters.get("date_to"):
        clauses.append("d.document_date <= ?")
        params.append(filters["date_to"])
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
    if filters.get("inclusion_status"):
        clauses.append("COALESCE(d.inclusion_status, 'incluido') = ?")
        params.append(filters["inclusion_status"])

    where_clause = " AND ".join(clauses)
    try:
        rows = connection.execute(
            f"""
            SELECT
                d.id AS document_id,
                d.file_name_original,
                d.storage_path,
                dp.page_number,
                dp.page_text,
                d.document_type,
                d.document_date,
                d.inclusion_status,
                d.primary_identifier,
                CASE
                    WHEN d.document_type = 'reporte' THEN COALESCE(fr.ticket_number, d.primary_identifier, '')
                    WHEN d.document_type = 'hallazgo' THEN COALESCE(fi.base_ticket_number, fi.finding_folio, d.primary_identifier, '')
                    WHEN d.document_type = 'estimacion' THEN COALESCE(es.normalized_folio, es.original_folio, d.primary_identifier, '')
                    ELSE COALESCE(d.primary_identifier, '')
                END AS source_reference
            FROM document_pages_fts
            JOIN document_pages dp
              ON dp.document_id = document_pages_fts.document_id
             AND dp.page_number = document_pages_fts.page_number
            JOIN documents d ON d.id = dp.document_id
            LEFT JOIN positions p ON p.id = d.position_id
            LEFT JOIN fault_reports fr ON fr.document_id = d.id
            LEFT JOIN findings fi ON fi.document_id = d.id
            LEFT JOIN estimates es ON es.document_id = d.id
            WHERE {where_clause}
            ORDER BY d.document_date DESC, dp.page_number ASC
            LIMIT 100
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows], None
    except OperationalError as exc:
        return [], str(exc)
