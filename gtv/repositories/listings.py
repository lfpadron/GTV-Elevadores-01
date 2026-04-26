"""Operational listing queries for reports, estimates and item tracking."""

from __future__ import annotations

from datetime import date
from sqlite3 import Connection

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


def list_report_ticket_rows(connection: Connection, filters: dict) -> list[dict]:
    clauses = [
        "d.document_status = 'activo'",
        "d.document_type IN ('reporte', 'hallazgo', 'estimacion')",
    ]
    params: list[object] = []

    if filters.get("date_from"):
        clauses.append("d.document_date >= ?")
        params.append(filters["date_from"])
    if filters.get("date_to"):
        clauses.append("d.document_date <= ?")
        params.append(filters["date_to"])
    if filters.get("ticket"):
        needle = f"%{filters['ticket']}%"
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
        params.extend([needle, needle, needle, needle, needle, needle])
    if filters.get("state"):
        clauses.append("COALESCE(fr.report_state, fi.finding_state, es.estimate_state, '') = ?")
        params.append(filters["state"])
    if filters.get("tower"):
        clauses.append("COALESCE(d.tower, '') = ?")
        params.append(filters["tower"])
    if filters.get("document_type"):
        clauses.append("d.document_type = ?")
        params.append(filters["document_type"])
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

    rows = connection.execute(
        f"""
        SELECT
            d.id AS document_id,
            d.document_type,
            d.file_name_original,
            d.storage_path,
            d.document_date,
            d.document_time,
            trim(COALESCE(d.document_date, '') || ' ' || COALESCE(d.document_time, '')) AS opened_at,
            CASE
                WHEN d.document_type = 'estimacion' THEN ''
                ELSE COALESCE(
                    (
                        SELECT MIN(a.event_at)
                        FROM audit_logs a
                        WHERE a.entity_type = CASE
                                WHEN d.document_type = 'reporte' THEN 'reporte'
                                ELSE 'hallazgo'
                            END
                          AND a.entity_id = CAST(d.id AS TEXT)
                          AND a.field_name = CASE
                                WHEN d.document_type = 'reporte' THEN 'report_state'
                                ELSE 'finding_state'
                            END
                          AND a.new_value IN ('en_atencion', 'atendido', 'cerrado')
                    ),
                    CASE
                        WHEN COALESCE(fr.report_state, fi.finding_state, '') IN ('en_atencion', 'atendido', 'cerrado')
                        THEN trim(COALESCE(d.document_date, '') || ' ' || COALESCE(d.document_time, ''))
                        ELSE ''
                    END
                )
            END AS attended_at,
            CASE
                WHEN d.document_type = 'estimacion' THEN ''
                ELSE COALESCE(
                    (
                        SELECT MIN(a.event_at)
                        FROM audit_logs a
                        WHERE a.entity_type = CASE
                                WHEN d.document_type = 'reporte' THEN 'reporte'
                                ELSE 'hallazgo'
                            END
                          AND a.entity_id = CAST(d.id AS TEXT)
                          AND a.field_name = CASE
                                WHEN d.document_type = 'reporte' THEN 'report_state'
                                ELSE 'finding_state'
                            END
                          AND a.new_value = 'cerrado'
                    ),
                    CASE
                        WHEN COALESCE(fr.report_state, fi.finding_state, '') = 'cerrado'
                        THEN trim(COALESCE(d.document_date, '') || ' ' || COALESCE(d.document_time, ''))
                        ELSE ''
                    END
                )
            END AS closed_at,
            d.tower,
            p.name AS position_name,
            d.equipment_text_original,
            d.equipment_code,
            d.equipment_key,
            cd.case_id,
            c.case_folio,
            COALESCE(fr.report_state, fi.finding_state, es.estimate_state, '') AS current_status,
            CASE
                WHEN d.document_type = 'reporte' THEN COALESCE(fr.ticket_number, d.primary_identifier, '')
                WHEN d.document_type = 'hallazgo' THEN COALESCE(fi.base_ticket_number, fi.finding_folio, d.primary_identifier, '')
                WHEN d.document_type = 'estimacion' THEN COALESCE(es.normalized_folio, es.original_folio, d.primary_identifier, '')
                ELSE COALESCE(d.primary_identifier, '')
            END AS source_reference,
            COALESCE(
                d.summary_user_edited,
                d.summary_ai_original,
                d.short_description,
                fr.description,
                fi.description,
                {ESTIMATE_CONCEPT_SUMMARY_SQL},
                ''
            ) AS summary_text,
            CASE
                WHEN d.document_type = 'estimacion' THEN COALESCE(es.total_amount, 0)
                ELSE COALESCE(
                    (
                        SELECT SUM(estimate_total)
                        FROM (
                            SELECT DISTINCT
                                e2.document_id,
                                COALESCE(e2.total_amount, 0) AS estimate_total
                            FROM case_documents cd2
                            JOIN estimates e2 ON e2.document_id = cd2.document_id
                            WHERE cd2.case_id = cd.case_id
                        )
                    ),
                    0
                )
            END AS quoted_amount
        FROM documents d
        LEFT JOIN positions p ON p.id = d.position_id
        LEFT JOIN fault_reports fr ON fr.document_id = d.id
        LEFT JOIN findings fi ON fi.document_id = d.id
        LEFT JOIN estimates es ON es.document_id = d.id
        LEFT JOIN case_documents cd ON cd.document_id = d.id
        LEFT JOIN cases c ON c.id = cd.case_id
        WHERE {" AND ".join(clauses)}
        ORDER BY d.document_date DESC, d.document_time DESC, d.id DESC
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def list_estimate_item_rows(connection: Connection, filters: dict) -> list[dict]:
    clauses = [
        "d.document_status = 'activo'",
        "d.document_type = 'estimacion'",
    ]
    params: list[object] = []

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
                    NULLIF(COALESCE(ei.equipment_code, d.equipment_code, ''), '') IS NULL
                    OR UPPER(COALESCE(ei.equipment_code, d.equipment_code, '')) NOT IN ({placeholders})
                )
                """
            )
            params.extend(known_codes)
        else:
            resolved_code = resolve_equipment_code_alias(filters["equipment"])
            if resolved_code:
                clauses.append("COALESCE(ei.equipment_code, d.equipment_code, d.equipment_key, '') = ?")
                params.append(resolved_code)
            else:
                clauses.append(
                    """
                    (
                        COALESCE(ei.equipment_text_original, d.equipment_text_original, '') LIKE ?
                        OR COALESCE(d.equipment_key, '') LIKE ?
                        OR COALESCE(ei.equipment_code, d.equipment_code, '') LIKE ?
                    )
                    """
                )
                params.extend([f"%{filters['equipment']}%"] * 3)
    if filters.get("piece_text"):
        clauses.append("COALESCE(ei.concept_text, '') LIKE ?")
        params.append(f"%{filters['piece_text']}%")
    if filters.get("case_search"):
        clauses.append("COALESCE(c.case_folio, '') LIKE ?")
        params.append(f"%{filters['case_search']}%")
    if filters.get("ticket"):
        needle = f"%{filters['ticket']}%"
        clauses.append(
            """
            EXISTS (
                SELECT 1
                FROM case_documents cd2
                JOIN documents d2 ON d2.id = cd2.document_id
                LEFT JOIN fault_reports fr2 ON fr2.document_id = d2.id
                LEFT JOIN findings fi2 ON fi2.document_id = d2.id
                WHERE cd2.case_id = cd.case_id
                  AND d2.document_type IN ('reporte', 'hallazgo')
                  AND (
                        COALESCE(fr2.ticket_number, '') LIKE ?
                        OR COALESCE(fi2.base_ticket_number, '') LIKE ?
                        OR COALESCE(fi2.finding_folio, '') LIKE ?
                        OR COALESCE(d2.primary_identifier, '') LIKE ?
                  )
            )
            """
        )
        params.extend([needle, needle, needle, needle])
    if filters.get("link_status") == "vinculado":
        clauses.append("cd.case_id IS NOT NULL")
    elif filters.get("link_status") == "por_vincular":
        clauses.append("cd.case_id IS NULL")
    if filters.get("support_status") == "sin_soporte":
        clauses.append("COALESCE(ei.missing_supporting_reference, es.missing_supporting_reference, 0) = 1")
    elif filters.get("support_status") == "con_soporte":
        clauses.append("COALESCE(ei.missing_supporting_reference, es.missing_supporting_reference, 0) = 0")
    if filters.get("catalog_status") == "sin_catalogo":
        clauses.append("COALESCE(ei.missing_catalog_equipment, 0) = 1")
    elif filters.get("catalog_status") == "en_catalogo":
        clauses.append("COALESCE(ei.missing_catalog_equipment, 0) = 0")

    state_filter = filters.get("item_state")
    if state_filter:
        if state_filter == "pendiente":
            clauses.append(
                """
                COALESCE(ei.invoice_number, '') = ''
                AND COALESCE(ei.invoice_date, '') = ''
                AND ei.payment_status = 'no_pagada'
                AND ei.receipt_status = 'no_recibida'
                """
            )
        elif state_filter == "recibida":
            clauses.append("ei.receipt_status IN ('parcialmente_recibida', 'recibida_total')")
        elif state_filter == "pagada":
            clauses.append("ei.payment_status IN ('pagada_parcial', 'pagada_total')")
        elif state_filter == "facturada":
            clauses.append(
                """
                (
                    COALESCE(ei.invoice_number, '') <> ''
                    OR COALESCE(ei.invoice_date, '') <> ''
                    OR EXISTS (
                        SELECT 1
                        FROM estimate_item_units u
                        WHERE u.estimate_item_id = ei.id
                          AND (
                              COALESCE(u.invoice_number, '') <> ''
                              OR COALESCE(u.invoice_date, '') <> ''
                          )
                    )
                )
                """
            )
        elif state_filter == "sin_factura":
            clauses.append(
                """
                COALESCE(ei.invoice_number, '') = ''
                AND COALESCE(ei.invoice_date, '') = ''
                AND NOT EXISTS (
                    SELECT 1
                    FROM estimate_item_units u
                    WHERE u.estimate_item_id = ei.id
                      AND (
                          COALESCE(u.invoice_number, '') <> ''
                          OR COALESCE(u.invoice_date, '') <> ''
                      )
                )
                """
            )
        elif state_filter in {"no_recibida", "parcialmente_recibida", "recibida_total"}:
            clauses.append("ei.receipt_status = ?")
            params.append(state_filter)
        elif state_filter in {"no_pagada", "pagada_parcial", "pagada_total"}:
            clauses.append("ei.payment_status = ?")
            params.append(state_filter)

    rows = connection.execute(
        f"""
        SELECT
            d.id AS document_id,
            d.file_name_original,
            d.storage_path,
            d.document_date,
            d.document_time,
            d.tower,
            p.name AS position_name,
            d.equipment_text_original,
            d.equipment_code,
            d.equipment_key,
            cd.case_id,
            c.case_folio,
            es.estimate_state,
            COALESCE(es.normalized_folio, es.original_folio, d.primary_identifier, '') AS estimate_reference,
            es.report_reference_text AS estimate_report_reference_text,
            es.finding_reference_text AS estimate_finding_reference_text,
            es.missing_supporting_reference AS estimate_missing_supporting_reference,
            ei.id AS estimate_item_id,
            ei.line_number,
            ei.concept_text,
            ei.equipment_text_original AS item_equipment_text_original,
            ei.equipment_code AS item_equipment_code,
            ei.report_reference_text,
            ei.finding_reference_text,
            ei.report_document_id,
            ei.finding_document_id,
            ei.user_ticket_id,
            ei.delivery_days,
            ei.estimated_delivery_date,
            ei.missing_catalog_equipment,
            ei.missing_supporting_reference,
            ei.quantity,
            ei.unit_price,
            ei.subtotal,
            ei.receipt_status,
            ei.payment_status,
            ei.reception_date,
            ei.payment_date,
            ei.payment_method,
            ei.invoice_date,
            ei.invoice_number,
            rd.file_name_original AS report_document_name,
            fd.file_name_original AS finding_document_name,
            COALESCE(fr_map.ticket_number, rd.primary_identifier, '') AS mapped_report_reference,
            COALESCE(fi_map.base_ticket_number, fi_map.finding_folio, fd.primary_identifier, '') AS mapped_finding_reference,
            ut.ticket_folio AS mapped_user_ticket_folio,
            COALESCE(
                (
                    SELECT COUNT(*)
                    FROM estimate_item_units u
                    WHERE u.estimate_item_id = ei.id
                      AND u.receipt_status = 'recibida_total'
                ),
                0
            ) AS received_units,
            COALESCE(
                (
                    SELECT COUNT(*)
                    FROM estimate_item_units u
                    WHERE u.estimate_item_id = ei.id
                      AND u.payment_status = 'pagada_total'
                ),
                0
            ) AS paid_units,
            COALESCE(
                (
                    SELECT group_concat(DISTINCT d2.document_type)
                    FROM case_documents cd2
                    JOIN documents d2 ON d2.id = cd2.document_id
                    WHERE cd2.case_id = cd.case_id
                      AND d2.document_type IN ('reporte', 'hallazgo')
                ),
                ''
            ) AS related_origin_types,
            COALESCE(
                (
                    SELECT group_concat(related_reference, ' | ')
                    FROM (
                        SELECT DISTINCT
                            CASE
                                WHEN d2.document_type = 'reporte' THEN 'REPORTE ' || COALESCE(fr2.ticket_number, d2.primary_identifier, 'sin referencia')
                                WHEN d2.document_type = 'hallazgo' THEN 'HALLAZGO ' || COALESCE(fi2.base_ticket_number, fi2.finding_folio, d2.primary_identifier, 'sin referencia')
                                ELSE NULL
                            END AS related_reference
                        FROM case_documents cd2
                        JOIN documents d2 ON d2.id = cd2.document_id
                        LEFT JOIN fault_reports fr2 ON fr2.document_id = d2.id
                        LEFT JOIN findings fi2 ON fi2.document_id = d2.id
                        WHERE cd2.case_id = cd.case_id
                          AND d2.document_type IN ('reporte', 'hallazgo')
                    )
                ),
                ''
            ) AS linked_references,
            COALESCE(
                (
                    SELECT group_concat(DISTINCT NULLIF(u.invoice_number, ''))
                    FROM estimate_item_units u
                    WHERE u.estimate_item_id = ei.id
                      AND NULLIF(u.invoice_number, '') IS NOT NULL
                ),
                ''
            ) AS unit_invoice_numbers,
            COALESCE(
                (
                    SELECT group_concat(related_summary, ' | ')
                    FROM (
                        SELECT DISTINCT
                            COALESCE(d2.summary_user_edited, d2.summary_ai_original, d2.short_description, '') AS related_summary
                        FROM case_documents cd2
                        JOIN documents d2 ON d2.id = cd2.document_id
                        WHERE cd2.case_id = cd.case_id
                          AND d2.id <> d.id
                          AND COALESCE(d2.summary_user_edited, d2.summary_ai_original, d2.short_description, '') <> ''
                    )
                ),
                COALESCE(d.summary_user_edited, d.summary_ai_original, d.short_description, '')
            ) AS summary_text,
            CASE
                WHEN cd.case_id IS NULL THEN 'por_vincular'
                ELSE 'vinculado'
            END AS link_status
        FROM documents d
        JOIN estimates es ON es.document_id = d.id
        JOIN estimate_items ei ON ei.estimate_document_id = d.id
        LEFT JOIN positions p ON p.id = d.position_id
        LEFT JOIN case_documents cd ON cd.document_id = d.id
        LEFT JOIN cases c ON c.id = cd.case_id
        LEFT JOIN documents rd ON rd.id = ei.report_document_id
        LEFT JOIN fault_reports fr_map ON fr_map.document_id = rd.id
        LEFT JOIN documents fd ON fd.id = ei.finding_document_id
        LEFT JOIN findings fi_map ON fi_map.document_id = fd.id
        LEFT JOIN user_tickets ut ON ut.id = ei.user_ticket_id
        WHERE {" AND ".join(clauses)}
        ORDER BY d.document_date DESC, d.id DESC, ei.line_number ASC, ei.id ASC
        """,
        params,
    ).fetchall()

    enriched_rows: list[dict] = []
    today_date = date.today()
    today = today_date.isoformat()
    for row in rows:
        item = dict(row)
        quantity = float(item.get("quantity") or 0)
        paid_units = int(item.get("paid_units") or 0)
        received_units = int(item.get("received_units") or 0)

        if received_units == 0 and item.get("receipt_status") == "recibida_total":
            received_units = int(quantity)
        if paid_units == 0 and item.get("payment_status") == "pagada_total":
            paid_units = int(quantity)

        if quantity > 0 and paid_units > 0:
            paid_amount = float(item.get("subtotal") or 0) * min(paid_units, quantity) / quantity
        elif item.get("payment_status") == "pagada_total":
            paid_amount = float(item.get("subtotal") or 0)
        else:
            paid_amount = 0.0

        invoice_tokens = [
            token
            for token in [
                item.get("invoice_number") or "",
                item.get("unit_invoice_numbers") or "",
            ]
            if token
        ]
        invoice_display = " | ".join(invoice_tokens)
        invoice_flag = bool(invoice_display or item.get("invoice_date"))

        if invoice_flag:
            operational_bucket = "facturada"
        elif item.get("payment_status") in {"pagada_parcial", "pagada_total"} or paid_units > 0:
            operational_bucket = "pagada"
        elif item.get("receipt_status") in {"parcialmente_recibida", "recibida_total"} or received_units > 0:
            operational_bucket = "recibida"
        else:
            operational_bucket = "pendiente"

        support_labels = []
        if item.get("mapped_report_reference"):
            support_labels.append(f"REPORTE {item['mapped_report_reference']}")
        elif item.get("report_reference_text"):
            support_labels.append(f"REPORTE {item['report_reference_text']}")
        if item.get("mapped_finding_reference"):
            support_labels.append(f"HALLAZGO {item['mapped_finding_reference']}")
        elif item.get("finding_reference_text"):
            support_labels.append(f"HALLAZGO {item['finding_reference_text']}")
        if item.get("mapped_user_ticket_folio"):
            support_labels.append(f"TICKET USUARIO {item['mapped_user_ticket_folio']}")

        estimated_delivery_date = item.get("estimated_delivery_date") or ""
        delivery_bucket = ""
        if estimated_delivery_date:
            if item.get("receipt_status") == "recibida_total" or received_units >= int(item.get("quantity") or 0):
                delivery_bucket = "entregado"
            elif estimated_delivery_date < today:
                delivery_bucket = "atrasado"
            else:
                delivery_bucket = "pendiente_entrega"

        item["received_units"] = received_units
        item["paid_units"] = paid_units
        item["paid_amount"] = round(paid_amount, 2)
        item["invoice_display"] = invoice_display
        item["invoice_flag"] = "SI" if invoice_flag else "NO"
        item["operational_bucket"] = operational_bucket
        item["requested_date"] = item.get("document_date")
        item["support_reference_display"] = " | ".join(support_labels) if support_labels else "No vinculado"
        item["effective_equipment_code"] = item.get("item_equipment_code") or item.get("equipment_code")
        item["effective_equipment_text"] = item.get("item_equipment_text_original") or item.get("equipment_text_original")
        item["delivery_bucket"] = delivery_bucket
        item["delivery_delay_flag"] = "SI" if delivery_bucket == "atrasado" else "NO"
        enriched_rows.append(item)

    delivery_filter = filters.get("delivery_filter")
    if delivery_filter:
        enriched_rows = _apply_delivery_filters(enriched_rows, delivery_filter)

    return enriched_rows


def list_estimate_rows(connection: Connection, filters: dict) -> list[dict]:
    base_rows = list_estimate_item_rows(connection, filters)
    grouped: dict[int, dict] = {}
    for row in base_rows:
        document_id = row["document_id"]
        if document_id not in grouped:
            grouped[document_id] = {
                "document_id": document_id,
                "document_type": "estimacion",
                "file_name_original": row.get("file_name_original"),
                "storage_path": row.get("storage_path"),
                "document_date": row.get("document_date"),
                "document_time": row.get("document_time"),
                "tower": row.get("tower"),
                "position_name": row.get("position_name"),
                "equipment_text_original": row.get("equipment_text_original"),
                "equipment_code": row.get("effective_equipment_code") or row.get("equipment_code"),
                "equipment_key": row.get("equipment_key"),
                "case_id": row.get("case_id"),
                "case_folio": row.get("case_folio"),
                "estimate_state": row.get("estimate_state"),
                "estimate_reference": row.get("estimate_reference"),
                "linked_references": row.get("support_reference_display") or row.get("linked_references"),
                "summary_text": row.get("summary_text"),
                "missing_link_indicator": "SI" if row.get("link_status") == "por_vincular" else "NO",
            }
        grouped[document_id]["summary_text"] = grouped[document_id]["summary_text"] or row.get("summary_text")
    return list(grouped.values())


def list_hallazgo_report_rows(connection: Connection, filters: dict) -> list[dict]:
    clauses = [
        "1 = 1",
        "d.document_type IN ('reporte', 'hallazgo', 'estimacion')",
    ]
    params: list[object] = []

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
    if filters.get("document_type"):
        clauses.append("d.document_type = ?")
        params.append(filters["document_type"])
    if filters.get("inclusion_status"):
        clauses.append("COALESCE(d.inclusion_status, 'incluido') = ?")
        params.append(filters["inclusion_status"])

    rows = connection.execute(
        f"""
        SELECT
            d.id AS document_id,
            d.document_type,
            d.file_name_original,
            d.storage_path,
            d.document_date,
            d.document_time,
            d.tower,
            p.name AS position_name,
            d.equipment_text_original,
            d.equipment_code,
            d.equipment_key,
            d.inclusion_status,
            CASE
                WHEN d.document_type = 'reporte' THEN COALESCE(fr.cause_text, fr.description, d.short_description, '')
                WHEN d.document_type = 'hallazgo' THEN COALESCE(fi.description, fi.affected_part_text, d.short_description, '')
                WHEN d.document_type = 'estimacion' THEN COALESCE(d.summary_user_edited, d.summary_ai_original, d.short_description, '')
                ELSE COALESCE(d.short_description, '')
            END AS cause_text,
            CASE
                WHEN d.document_type = 'reporte' THEN COALESCE(fr.solution_text, '')
                WHEN d.document_type = 'hallazgo' THEN COALESCE(fi.recommendation_text, '')
                WHEN d.document_type = 'estimacion' THEN COALESCE(
                    (
                        SELECT group_concat(concept_text, ' | ')
                        FROM (
                            SELECT DISTINCT ei.concept_text
                            FROM estimate_items ei
                            WHERE ei.estimate_document_id = d.id
                              AND COALESCE(ei.concept_text, '') <> ''
                            ORDER BY ei.line_number ASC
                            LIMIT 3
                        )
                    ),
                    ''
                )
                ELSE ''
            END AS solution_text,
            CASE
                WHEN d.document_type = 'reporte' THEN COALESCE(fr.ticket_number, '')
                WHEN d.document_type = 'hallazgo' THEN COALESCE(fi.base_ticket_number, '')
                WHEN d.document_type = 'estimacion' THEN COALESCE(
                    (
                        SELECT fr2.ticket_number
                        FROM case_documents cd_self
                        JOIN case_documents cd2 ON cd2.case_id = cd_self.case_id
                        JOIN documents d2 ON d2.id = cd2.document_id
                        LEFT JOIN fault_reports fr2 ON fr2.document_id = d2.id
                        WHERE cd_self.document_id = d.id
                          AND d2.document_type = 'reporte'
                          AND COALESCE(fr2.ticket_number, '') <> ''
                        ORDER BY d2.document_date DESC, d2.id DESC
                        LIMIT 1
                    ),
                    (
                        SELECT fi2.base_ticket_number
                        FROM case_documents cd_self
                        JOIN case_documents cd2 ON cd2.case_id = cd_self.case_id
                        JOIN documents d2 ON d2.id = cd2.document_id
                        LEFT JOIN findings fi2 ON fi2.document_id = d2.id
                        WHERE cd_self.document_id = d.id
                          AND d2.document_type = 'hallazgo'
                          AND COALESCE(fi2.base_ticket_number, '') <> ''
                        ORDER BY d2.document_date DESC, d2.id DESC
                        LIMIT 1
                    ),
                    ''
                )
                ELSE ''
            END AS ticket_number
        FROM documents d
        LEFT JOIN positions p ON p.id = d.position_id
        LEFT JOIN fault_reports fr ON fr.document_id = d.id
        LEFT JOIN findings fi ON fi.document_id = d.id
        WHERE {" AND ".join(clauses)}
        ORDER BY d.document_date DESC, d.document_time DESC, d.id DESC
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def _apply_delivery_filters(rows: list[dict], delivery_filter: str) -> list[dict]:
    today = date.today()
    filtered: list[dict] = []
    for row in rows:
        estimated_delivery = row.get("estimated_delivery_date")
        estimated_date = None
        if estimated_delivery:
            try:
                estimated_date = date.fromisoformat(str(estimated_delivery))
            except ValueError:
                estimated_date = None

        if delivery_filter == "proximos_3_dias":
            if estimated_date and today <= estimated_date <= date.fromordinal(today.toordinal() + 3):
                filtered.append(row)
            continue
        if delivery_filter == "proximos_5_dias":
            if estimated_date and today <= estimated_date <= date.fromordinal(today.toordinal() + 5):
                filtered.append(row)
            continue
        if delivery_filter == "atrasados":
            if row.get("delivery_bucket") == "atrasado":
                filtered.append(row)
            continue
        if delivery_filter == "entregados":
            if row.get("delivery_bucket") == "entregado":
                filtered.append(row)
            continue
        if delivery_filter == "con_falta_pago":
            if row.get("payment_status") != "pagada_total":
                filtered.append(row)
            continue
        if delivery_filter == "ya_pagados":
            if row.get("payment_status") == "pagada_total":
                filtered.append(row)
            continue
        if delivery_filter == "con_falta_factura":
            if row.get("invoice_flag") != "SI":
                filtered.append(row)
            continue
        if delivery_filter == "ya_facturados":
            if row.get("invoice_flag") == "SI":
                filtered.append(row)
            continue
        filtered.append(row)
    return filtered
