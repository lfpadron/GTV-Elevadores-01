"""Editable equipment catalog and alias persistence helpers."""

from __future__ import annotations

from sqlite3 import Connection

from gtv.utils.equipment import equipment_display_name, normalize_alias_text


def list_equipment_catalog(connection: Connection, *, tower: str | None = None, include_inactive: bool = False) -> list[dict]:
    clauses = ["1 = 1"]
    params: list[object] = []
    if tower:
        clauses.append("tower = ?")
        params.append(tower.upper())
    if not include_inactive:
        clauses.append("is_active = 1")
    rows = connection.execute(
        f"""
        SELECT *
        FROM equipment_catalog
        WHERE {" AND ".join(clauses)}
        ORDER BY tower, display_name
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def get_equipment_catalog_entry(connection: Connection, equipment_code: str) -> dict | None:
    row = connection.execute(
        "SELECT * FROM equipment_catalog WHERE equipment_code = ?",
        (equipment_code.upper(),),
    ).fetchone()
    return dict(row) if row else None


def upsert_equipment_catalog_entry(
    connection: Connection,
    *,
    equipment_code: str,
    tower: str,
    position_name: str | None,
    display_name: str,
    is_active: bool = True,
) -> None:
    connection.execute(
        """
        INSERT INTO equipment_catalog (
            equipment_code,
            tower,
            position_name,
            display_name,
            is_active
        )
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(equipment_code) DO UPDATE SET
            tower = excluded.tower,
            position_name = excluded.position_name,
            display_name = excluded.display_name,
            is_active = excluded.is_active,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            equipment_code.upper(),
            tower.upper(),
            position_name.lower() if position_name else None,
            display_name,
            1 if is_active else 0,
        ),
    )


def list_equipment_aliases(connection: Connection, equipment_code: str | None = None) -> list[dict]:
    clauses = ["1 = 1"]
    params: list[object] = []
    if equipment_code:
        clauses.append("equipment_code = ?")
        params.append(equipment_code.upper())
    rows = connection.execute(
        f"""
        SELECT *
        FROM equipment_aliases
        WHERE {" AND ".join(clauses)}
        ORDER BY equipment_code, alias_text
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def upsert_equipment_alias(connection: Connection, *, alias_text: str, equipment_code: str, source: str = "manual") -> None:
    normalized_alias = normalize_alias_text(alias_text)
    connection.execute(
        """
        INSERT INTO equipment_aliases (
            alias_text,
            normalized_alias,
            equipment_code,
            source
        )
        VALUES (?, ?, ?, ?)
        ON CONFLICT(normalized_alias) DO UPDATE SET
            alias_text = excluded.alias_text,
            equipment_code = excluded.equipment_code,
            source = excluded.source,
            updated_at = CURRENT_TIMESTAMP
        """,
        (alias_text.strip(), normalized_alias, equipment_code.upper(), source),
    )


def list_uncataloged_equipment_usage(connection: Connection) -> list[dict]:
    rows = connection.execute(
        """
        SELECT
            'documento' AS entity_type,
            d.id AS entity_id,
            d.id AS source_document_id,
            d.document_type,
            d.file_name_original AS source_name,
            d.storage_path,
            d.document_date,
            d.document_time,
            d.tower,
            d.equipment_text_original AS alias_text,
            d.equipment_code,
            CASE
                WHEN d.document_type = 'reporte' THEN COALESCE(fr.ticket_number, d.primary_identifier, '')
                WHEN d.document_type = 'hallazgo' THEN COALESCE(fi.base_ticket_number, fi.finding_folio, d.primary_identifier, '')
                WHEN d.document_type = 'estimacion' THEN COALESCE(es.normalized_folio, es.original_folio, d.primary_identifier, '')
                ELSE COALESCE(d.primary_identifier, '')
            END AS source_reference
        FROM documents d
        LEFT JOIN fault_reports fr ON fr.document_id = d.id
        LEFT JOIN findings fi ON fi.document_id = d.id
        LEFT JOIN estimates es ON es.document_id = d.id
        LEFT JOIN equipment_catalog ec ON ec.equipment_code = d.equipment_code AND ec.is_active = 1
        WHERE COALESCE(d.equipment_text_original, '') <> ''
          AND (COALESCE(d.equipment_code, '') = '' OR ec.equipment_code IS NULL)

        UNION ALL

        SELECT
            'partida_estimacion' AS entity_type,
            ei.id AS entity_id,
            d.id AS source_document_id,
            'estimacion' AS document_type,
            d.file_name_original AS source_name,
            d.storage_path,
            d.document_date,
            d.document_time,
            d.tower,
            ei.equipment_text_original AS alias_text,
            ei.equipment_code,
            COALESCE(es.normalized_folio, es.original_folio, d.primary_identifier, '') AS source_reference
        FROM estimate_items ei
        JOIN estimates es ON es.document_id = ei.estimate_document_id
        JOIN documents d ON d.id = es.document_id
        LEFT JOIN equipment_catalog ec ON ec.equipment_code = ei.equipment_code AND ec.is_active = 1
        WHERE COALESCE(ei.equipment_text_original, '') <> ''
          AND (COALESCE(ei.equipment_code, '') = '' OR ec.equipment_code IS NULL OR COALESCE(ei.missing_catalog_equipment, 0) = 1)

        ORDER BY document_date DESC, document_time DESC, source_name
        """
    ).fetchall()
    return [dict(row) for row in rows]


def apply_equipment_mapping_to_document(
    connection: Connection,
    *,
    document_id: int,
    equipment_code: str,
    display_name: str | None = None,
) -> None:
    label = display_name or equipment_display_name(equipment_code) or ""
    row = get_equipment_catalog_entry(connection, equipment_code)
    connection.execute(
        """
        UPDATE documents
        SET equipment_code = ?,
            equipment_key = ?,
            tower = COALESCE(?, tower),
            equipment_text_original = CASE
                WHEN COALESCE(equipment_text_original, '') = '' THEN ?
                ELSE equipment_text_original
            END
        WHERE id = ?
        """,
        (
            equipment_code.upper(),
            equipment_code.upper(),
            row.get("tower") if row else None,
            label or None,
            document_id,
        ),
    )


def apply_equipment_mapping_to_estimate_item(
    connection: Connection,
    *,
    item_id: int,
    equipment_code: str,
    display_name: str | None = None,
) -> None:
    label = display_name or equipment_display_name(equipment_code) or ""
    row = get_equipment_catalog_entry(connection, equipment_code)
    connection.execute(
        """
        UPDATE estimate_items
        SET equipment_code = ?,
            equipment_text_original = CASE
                WHEN COALESCE(equipment_text_original, '') = '' THEN ?
                ELSE equipment_text_original
            END,
            missing_catalog_equipment = 0
        WHERE id = ?
        """,
        (
            equipment_code.upper(),
            label or None,
            item_id,
        ),
    )
    if row:
        connection.execute(
            """
            UPDATE documents
            SET tower = COALESCE(?, tower)
            WHERE id = (
                SELECT estimate_document_id
                FROM estimate_items
                WHERE id = ?
            )
            """,
            (row.get("tower"), item_id),
        )
