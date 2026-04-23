"""Document, incident, linking and estimate persistence."""

from __future__ import annotations

from sqlite3 import Connection


def list_positions(connection: Connection) -> list[dict]:
    rows = connection.execute(
        "SELECT * FROM positions WHERE is_active = 1 ORDER BY name"
    ).fetchall()
    return [dict(row) for row in rows]


def get_position_id(connection: Connection, name: str | None) -> int | None:
    if not name:
        return None
    row = connection.execute(
        "SELECT id FROM positions WHERE lower(name) = lower(?)",
        (name,),
    ).fetchone()
    return int(row["id"]) if row else None


def create_document(connection: Connection, payload: dict) -> int:
    columns = ", ".join(payload.keys())
    placeholders = ", ".join("?" for _ in payload)
    cursor = connection.execute(
        f"INSERT INTO documents ({columns}) VALUES ({placeholders})",
        tuple(payload.values()),
    )
    return int(cursor.lastrowid)


def update_document_fields(connection: Connection, document_id: int, payload: dict) -> None:
    assignments = ", ".join(f"{column} = ?" for column in payload)
    connection.execute(
        f"UPDATE documents SET {assignments} WHERE id = ?",
        (*payload.values(), document_id),
    )


def get_document(connection: Connection, document_id: int) -> dict | None:
    row = connection.execute(
        """
        SELECT d.*, p.name AS position_name
        FROM documents d
        LEFT JOIN positions p ON p.id = d.position_id
        WHERE d.id = ?
        """,
        (document_id,),
    ).fetchone()
    return dict(row) if row else None


def get_document_with_details(connection: Connection, document_id: int) -> dict | None:
    document = get_document(connection, document_id)
    if not document:
        return None
    if document["document_type"] == "reporte":
        row = connection.execute(
            "SELECT * FROM fault_reports WHERE document_id = ?",
            (document_id,),
        ).fetchone()
    elif document["document_type"] == "hallazgo":
        row = connection.execute(
            "SELECT * FROM findings WHERE document_id = ?",
            (document_id,),
        ).fetchone()
    elif document["document_type"] == "estimacion":
        row = connection.execute(
            "SELECT * FROM estimates WHERE document_id = ?",
            (document_id,),
        ).fetchone()
    else:
        row = None
    document["details"] = dict(row) if row else {}
    return document


def find_existing_named_documents(
    connection: Connection,
    *,
    file_name_original: str,
    target_folder_fragment: str,
) -> list[dict]:
    rows = connection.execute(
        """
        SELECT *
        FROM documents
        WHERE file_name_original = ?
          AND storage_path LIKE ?
          AND document_status = 'activo'
        ORDER BY uploaded_at DESC
        """,
        (file_name_original, f"%{target_folder_fragment}%"),
    ).fetchall()
    return [dict(row) for row in rows]


def insert_document_pages(
    connection: Connection,
    *,
    document_id: int,
    file_name: str,
    document_type: str,
    pages: list[str],
) -> None:
    for index, page_text in enumerate(pages, start=1):
        connection.execute(
            """
            INSERT INTO document_pages (document_id, page_number, page_text)
            VALUES (?, ?, ?)
            """,
            (document_id, index, page_text),
        )
        connection.execute(
            """
            INSERT INTO document_pages_fts (
                document_id,
                page_number,
                file_name,
                document_type,
                page_text
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (document_id, index, file_name, document_type, page_text),
        )


def upsert_fault_report(connection: Connection, document_id: int, payload: dict) -> None:
    connection.execute(
        """
        INSERT INTO fault_reports (
            document_id,
            ticket_number,
            report_state,
            description,
            cause_text,
            solution_text,
            source_pages
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(document_id) DO UPDATE SET
            ticket_number = excluded.ticket_number,
            report_state = excluded.report_state,
            description = excluded.description,
            cause_text = excluded.cause_text,
            solution_text = excluded.solution_text,
            source_pages = excluded.source_pages
        """,
        (
            document_id,
            payload.get("ticket_number"),
            payload.get("report_state", "reportado"),
            payload.get("description"),
            payload.get("cause_text"),
            payload.get("solution_text"),
            payload.get("source_pages"),
        ),
    )


def upsert_finding(connection: Connection, document_id: int, payload: dict) -> None:
    connection.execute(
        """
        INSERT INTO findings (
            document_id,
            base_ticket_number,
            finding_folio,
            finding_state,
            description,
            affected_part_text,
            recommendation_text,
            source_pages
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(document_id) DO UPDATE SET
            base_ticket_number = excluded.base_ticket_number,
            finding_folio = excluded.finding_folio,
            finding_state = excluded.finding_state,
            description = excluded.description,
            affected_part_text = excluded.affected_part_text,
            recommendation_text = excluded.recommendation_text,
            source_pages = excluded.source_pages
        """,
        (
            document_id,
            payload.get("base_ticket_number"),
            payload.get("finding_folio"),
            payload.get("finding_state", "detectado"),
            payload.get("description"),
            payload.get("affected_part_text"),
            payload.get("recommendation_text"),
            payload.get("source_pages"),
        ),
    )


def upsert_estimate(connection: Connection, document_id: int, payload: dict) -> None:
    connection.execute(
        """
        INSERT INTO estimates (
            document_id,
            original_folio,
            normalized_folio,
            estimate_state,
            delivery_days,
            estimated_delivery_date,
            subtotal_amount,
            tax_amount,
            total_amount,
            source_pages
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(document_id) DO UPDATE SET
            original_folio = excluded.original_folio,
            normalized_folio = excluded.normalized_folio,
            estimate_state = excluded.estimate_state,
            delivery_days = excluded.delivery_days,
            estimated_delivery_date = excluded.estimated_delivery_date,
            subtotal_amount = excluded.subtotal_amount,
            tax_amount = excluded.tax_amount,
            total_amount = excluded.total_amount,
            source_pages = excluded.source_pages
        """,
        (
            document_id,
            payload.get("original_folio"),
            payload.get("normalized_folio"),
            payload.get("estimate_state", "abierta"),
            payload.get("delivery_days"),
            payload.get("estimated_delivery_date"),
            payload.get("subtotal_amount"),
            payload.get("tax_amount"),
            payload.get("total_amount"),
            payload.get("source_pages"),
        ),
    )


def replace_estimate_items(connection: Connection, estimate_document_id: int, items: list[dict]) -> list[int]:
    connection.execute("DELETE FROM estimate_items WHERE estimate_document_id = ?", (estimate_document_id,))
    item_ids: list[int] = []
    for item in items:
        cursor = connection.execute(
            """
            INSERT INTO estimate_items (
                estimate_document_id,
                line_number,
                concept_text,
                quantity,
                unit_price,
                subtotal
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                estimate_document_id,
                item.get("line_number"),
                item.get("concept_text"),
                item.get("quantity", 0),
                item.get("unit_price", 0),
                item.get("subtotal", 0),
            ),
        )
        item_id = int(cursor.lastrowid)
        item_ids.append(item_id)
        quantity = int(item.get("quantity") or 0)
        for unit_index in range(1, max(quantity, 0) + 1):
            connection.execute(
                """
                INSERT INTO estimate_item_units (estimate_item_id, unit_index)
                VALUES (?, ?)
                """,
                (item_id, unit_index),
            )
    return item_ids


def list_estimate_items(connection: Connection, estimate_document_id: int) -> list[dict]:
    rows = connection.execute(
        """
        SELECT *
        FROM estimate_items
        WHERE estimate_document_id = ?
        ORDER BY line_number, id
        """,
        (estimate_document_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def list_estimate_item_units(connection: Connection, estimate_item_id: int) -> list[dict]:
    rows = connection.execute(
        """
        SELECT *
        FROM estimate_item_units
        WHERE estimate_item_id = ?
        ORDER BY unit_index
        """,
        (estimate_item_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def update_estimate_item_fields(connection: Connection, item_id: int, payload: dict) -> None:
    assignments = ", ".join(f"{column} = ?" for column in payload)
    connection.execute(
        f"UPDATE estimate_items SET {assignments} WHERE id = ?",
        (*payload.values(), item_id),
    )


def update_estimate_unit_fields(connection: Connection, unit_id: int, payload: dict) -> None:
    assignments = ", ".join(f"{column} = ?" for column in payload)
    connection.execute(
        f"UPDATE estimate_item_units SET {assignments} WHERE id = ?",
        (*payload.values(), unit_id),
    )


def create_incident(
    connection: Connection,
    *,
    document_id: int | None,
    incident_type: str,
    title: str,
    details: str,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO incidents (document_id, incident_type, title, details)
        VALUES (?, ?, ?, ?)
        """,
        (document_id, incident_type, title, details),
    )
    return int(cursor.lastrowid)


def list_incidents(connection: Connection, status: str = "pendiente") -> list[dict]:
    rows = connection.execute(
        """
        SELECT i.*, d.file_name_original, d.document_type, d.primary_identifier
        FROM incidents i
        LEFT JOIN documents d ON d.id = i.document_id
        WHERE i.status = ?
        ORDER BY i.created_at ASC, i.id ASC
        """,
        (status,),
    ).fetchall()
    return [dict(row) for row in rows]


def resolve_incident(
    connection: Connection,
    *,
    incident_id: int,
    user_id: int,
    resolution_notes: str,
    discarded: bool = False,
) -> None:
    final_status = "descartada" if discarded else "resuelta"
    connection.execute(
        """
        UPDATE incidents
        SET status = ?,
            resolved_at = CURRENT_TIMESTAMP,
            resolved_by_user_id = ?,
            resolution_notes = ?
        WHERE id = ?
        """,
        (final_status, user_id, resolution_notes, incident_id),
    )


def get_incident(connection: Connection, incident_id: int) -> dict | None:
    row = connection.execute(
        """
        SELECT i.*, d.file_name_original, d.storage_path, d.document_type, d.duplicate_of_document_id
        FROM incidents i
        LEFT JOIN documents d ON d.id = i.document_id
        WHERE i.id = ?
        """,
        (incident_id,),
    ).fetchone()
    return dict(row) if row else None


def create_case_document_link(
    connection: Connection,
    *,
    case_id: int,
    document_id: int,
    link_status: str,
    linked_by_user_id: int | None,
    origin: str,
    notes: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO case_documents (
            case_id,
            document_id,
            link_status,
            linked_by_user_id,
            origin,
            notes
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(document_id) DO UPDATE SET
            case_id = excluded.case_id,
            link_status = excluded.link_status,
            linked_by_user_id = excluded.linked_by_user_id,
            linked_at = CURRENT_TIMESTAMP,
            origin = excluded.origin,
            notes = excluded.notes
        """,
        (case_id, document_id, link_status, linked_by_user_id, origin, notes),
    )


def list_case_document_links(connection: Connection, case_id: int) -> list[dict]:
    rows = connection.execute(
        """
        SELECT
            cd.*,
            d.document_type,
            d.file_name_original,
            d.document_date,
            d.document_time,
            d.primary_identifier,
            d.short_description
        FROM case_documents cd
        JOIN documents d ON d.id = cd.document_id
        WHERE cd.case_id = ?
        ORDER BY d.document_date, d.document_time, d.id
        """,
        (case_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def create_case_suggestion(
    connection: Connection,
    *,
    document_id: int,
    case_id: int,
    days_difference: int,
    proximity_label: str,
) -> None:
    connection.execute(
        """
        INSERT INTO case_link_suggestions (
            document_id,
            case_id,
            days_difference,
            proximity_label
        )
        VALUES (?, ?, ?, ?)
        ON CONFLICT(document_id, case_id) DO UPDATE SET
            days_difference = excluded.days_difference,
            proximity_label = excluded.proximity_label,
            link_status = 'sugerida',
            created_at = CURRENT_TIMESTAMP,
            decided_at = NULL,
            decided_by_user_id = NULL
        """,
        (document_id, case_id, days_difference, proximity_label),
    )


def list_pending_case_suggestions(connection: Connection) -> list[dict]:
    rows = connection.execute(
        """
        SELECT
            s.*,
            d.file_name_original,
            d.document_type,
            d.primary_identifier,
            d.document_date,
            d.equipment_text_original,
            c.case_folio,
            c.suggested_consolidated_status
        FROM case_link_suggestions s
        JOIN documents d ON d.id = s.document_id
        JOIN cases c ON c.id = s.case_id
        WHERE s.link_status = 'sugerida'
        ORDER BY s.created_at ASC, s.id ASC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def list_case_suggestions_for_document(connection: Connection, document_id: int) -> list[dict]:
    rows = connection.execute(
        """
        SELECT
            s.*,
            c.case_folio,
            c.suggested_consolidated_status,
            c.manual_consolidated_status
        FROM case_link_suggestions s
        JOIN cases c ON c.id = s.case_id
        WHERE s.document_id = ?
        ORDER BY s.days_difference ASC, s.id ASC
        """,
        (document_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def update_case_suggestion_status(
    connection: Connection,
    *,
    suggestion_id: int,
    status: str,
    user_id: int,
) -> None:
    connection.execute(
        """
        UPDATE case_link_suggestions
        SET link_status = ?,
            decided_at = CURRENT_TIMESTAMP,
            decided_by_user_id = ?
        WHERE id = ?
        """,
        (status, user_id, suggestion_id),
    )


def discard_other_case_suggestions(connection: Connection, *, document_id: int, keep_case_id: int, user_id: int) -> None:
    connection.execute(
        """
        UPDATE case_link_suggestions
        SET link_status = 'descartada',
            decided_at = CURRENT_TIMESTAMP,
            decided_by_user_id = ?
        WHERE document_id = ?
          AND case_id <> ?
          AND link_status = 'sugerida'
        """,
        (user_id, document_id, keep_case_id),
    )


def list_documents_without_case(connection: Connection) -> list[dict]:
    rows = connection.execute(
        """
        SELECT d.*, p.name AS position_name
        FROM documents d
        LEFT JOIN positions p ON p.id = d.position_id
        LEFT JOIN case_documents cd ON cd.document_id = d.id
        WHERE d.document_type <> 'no_reconocido'
          AND d.document_status = 'activo'
          AND d.duplicate_status NOT IN ('pending_review', 'discarded')
          AND cd.document_id IS NULL
        ORDER BY d.uploaded_at DESC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def list_documents_by_case_and_type(connection: Connection, case_id: int, document_type: str) -> list[dict]:
    rows = connection.execute(
        """
        SELECT d.*, p.name AS position_name
        FROM case_documents cd
        JOIN documents d ON d.id = cd.document_id
        LEFT JOIN positions p ON p.id = d.position_id
        WHERE cd.case_id = ?
          AND d.document_type = ?
        ORDER BY d.document_date, d.document_time, d.id
        """,
        (case_id, document_type),
    ).fetchall()
    return [dict(row) for row in rows]


def list_findings_for_case(connection: Connection, case_id: int) -> list[dict]:
    rows = connection.execute(
        """
        SELECT
            d.id AS document_id,
            d.document_date,
            d.document_time,
            d.file_name_original,
            f.*
        FROM case_documents cd
        JOIN documents d ON d.id = cd.document_id
        JOIN findings f ON f.document_id = d.id
        WHERE cd.case_id = ?
        ORDER BY d.document_date, d.document_time, d.id
        """,
        (case_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def list_estimates_for_case(connection: Connection, case_id: int) -> list[dict]:
    rows = connection.execute(
        """
        SELECT
            d.id AS document_id,
            d.document_date,
            d.document_time,
            d.file_name_original,
            e.*
        FROM case_documents cd
        JOIN documents d ON d.id = cd.document_id
        JOIN estimates e ON e.document_id = d.id
        WHERE cd.case_id = ?
        ORDER BY d.document_date, d.document_time, d.id
        """,
        (case_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def list_estimate_items_for_case(connection: Connection, case_id: int) -> list[dict]:
    rows = connection.execute(
        """
        SELECT
            ei.*,
            e.original_folio,
            e.normalized_folio,
            e.estimated_delivery_date,
            d.document_date AS estimate_date
        FROM case_documents cd
        JOIN estimates e ON e.document_id = cd.document_id
        JOIN documents d ON d.id = e.document_id
        JOIN estimate_items ei ON ei.estimate_document_id = e.document_id
        WHERE cd.case_id = ?
        ORDER BY e.document_id, ei.line_number, ei.id
        """,
        (case_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def list_units_for_case(connection: Connection, case_id: int) -> list[dict]:
    rows = connection.execute(
        """
        SELECT
            u.*,
            ei.concept_text,
            ei.id AS estimate_item_id,
            e.normalized_folio,
            e.original_folio
        FROM case_documents cd
        JOIN estimates e ON e.document_id = cd.document_id
        JOIN estimate_items ei ON ei.estimate_document_id = e.document_id
        JOIN estimate_item_units u ON u.estimate_item_id = ei.id
        WHERE cd.case_id = ?
        ORDER BY ei.id, u.unit_index
        """,
        (case_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def list_pages_for_document(connection: Connection, document_id: int) -> list[dict]:
    rows = connection.execute(
        """
        SELECT *
        FROM document_pages
        WHERE document_id = ?
        ORDER BY page_number
        """,
        (document_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def delete_system_matches(connection: Connection, case_id: int) -> None:
    connection.execute(
        """
        DELETE FROM finding_estimate_matches
        WHERE case_id = ?
          AND (
                match_state IN ('sugerida', 'cotizada_sin_hallazgo')
                OR (match_state = 'sin_match' AND confirmed_by_user_id IS NULL)
          )
        """,
        (case_id,),
    )


def create_match(connection: Connection, payload: dict) -> int:
    columns = ", ".join(payload.keys())
    placeholders = ", ".join("?" for _ in payload)
    cursor = connection.execute(
        f"INSERT INTO finding_estimate_matches ({columns}) VALUES ({placeholders})",
        tuple(payload.values()),
    )
    return int(cursor.lastrowid)


def list_matches_for_case(connection: Connection, case_id: int) -> list[dict]:
    rows = connection.execute(
        """
        SELECT
            m.*,
            f.finding_folio,
            f.affected_part_text,
            f.recommendation_text,
            ei.concept_text,
            ei.quantity,
            d.document_date AS finding_date
        FROM finding_estimate_matches m
        LEFT JOIN findings f ON f.document_id = m.finding_document_id
        LEFT JOIN estimate_items ei ON ei.id = m.estimate_item_id
        LEFT JOIN documents d ON d.id = f.document_id
        WHERE m.case_id = ?
        ORDER BY
            CASE m.match_state
                WHEN 'confirmada' THEN 0
                WHEN 'sugerida' THEN 1
                WHEN 'sin_match' THEN 2
                ELSE 3
            END,
            m.score DESC,
            m.id ASC
        """,
        (case_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def delete_match(connection: Connection, match_id: int) -> None:
    connection.execute("DELETE FROM finding_estimate_matches WHERE id = ?", (match_id,))
