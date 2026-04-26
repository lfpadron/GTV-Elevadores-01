"""Manual update workflows with audit logging."""

from __future__ import annotations

from datetime import datetime, timedelta
from sqlite3 import Connection

from gtv.models import AuthenticatedUser
from gtv.repositories import audit as audit_repo
from gtv.repositories import cases as case_repo
from gtv.repositories import documents as document_repo
from gtv.repositories import equipment_catalog as equipment_repo
from gtv.repositories import user_tickets as user_ticket_repo
from gtv.repositories import users as user_repo
from gtv.services import cases as case_service
from gtv.services.auditing import audit_diff
from gtv.utils.equipment import equipment_display_name, infer_equipment_code, normalize_alias_text, normalize_equipment_key


def update_document_corrections(
    connection: Connection,
    *,
    document_id: int,
    user: AuthenticatedUser,
    document_fields: dict,
    detail_fields: dict,
) -> None:
    current = document_repo.get_document_with_details(connection, document_id)
    if not current:
        raise ValueError("Documento no encontrado")

    if "position_name" in document_fields:
        position_id = document_repo.get_position_id(connection, document_fields["position_name"])
        document_fields["position_id"] = position_id
        document_fields.pop("position_name")

    if {"tower", "equipment_text_original", "position_id"} & set(document_fields):
        tower = document_fields.get("tower", current.get("tower"))
        equipment_text = document_fields.get("equipment_text_original", current.get("equipment_text_original"))
        if "position_id" in document_fields:
            position_row = connection.execute(
                "SELECT name FROM positions WHERE id = ?",
                (document_fields["position_id"],),
            ).fetchone()
            position_name = position_row["name"] if position_row else current.get("position_name")
        else:
            position_name = current.get("position_name")
        equipment_code = infer_equipment_code(
            raw_text=current.get("raw_text"),
            equipment_text=equipment_text,
            tower=tower,
            position=position_name,
        )
        document_fields["equipment_code"] = equipment_code
        document_fields["equipment_key"] = normalize_equipment_key(
            equipment_code=equipment_code,
            tower=tower,
            position=position_name,
            equipment_text=equipment_text,
        )

    if document_fields:
        audit_diff(
            connection,
            user_email=user.email,
            entity_type="document",
            entity_id=str(document_id),
            before=current,
            after=document_fields,
            context="Correccion manual de extraccion",
        )
        document_repo.update_document_fields(connection, document_id, document_fields)

    document_type = current["document_type"]
    existing_details = current.get("details", {})
    if detail_fields:
        audit_diff(
            connection,
            user_email=user.email,
            entity_type=document_type,
            entity_id=str(document_id),
            before=existing_details,
            after=detail_fields,
            context="Correccion manual de extraccion",
        )
        merged = {**existing_details, **detail_fields}
        if document_type == "reporte":
            document_repo.upsert_fault_report(connection, document_id, merged)
        elif document_type == "hallazgo":
            document_repo.upsert_finding(connection, document_id, merged)
        elif document_type == "estimacion":
            items = merged.get("items") or document_repo.list_estimate_items(connection, document_id)
            document_repo.upsert_estimate(connection, document_id, merged)
            if isinstance(items, list) and items and isinstance(items[0], dict):
                document_repo.replace_estimate_items(connection, document_id, items)


def update_case_manual_status(
    connection: Connection,
    *,
    case_id: int,
    manual_status: str | None,
    user: AuthenticatedUser,
) -> None:
    current = case_repo.get_case_by_id(connection, case_id)
    if not current:
        raise ValueError("Caso no encontrado")
    audit_repo.log_change(
        connection,
        user_email=user.email,
        entity_type="case",
        entity_id=str(case_id),
        field_name="manual_consolidated_status",
        old_value=current.get("manual_consolidated_status"),
        new_value=manual_status,
        context=f"Caso {current['case_folio']}",
    )
    case_repo.update_case_manual_status(connection, case_id, manual_status)
    case_service.refresh_case_status(connection, case_id)


def update_item_operational_fields(
    connection: Connection,
    *,
    item_id: int,
    payload: dict,
    propagate_mode: str | None,
    user: AuthenticatedUser,
) -> None:
    rows = connection.execute("SELECT * FROM estimate_items WHERE id = ?", (item_id,)).fetchone()
    if not rows:
        raise ValueError("Partida no encontrada")
    current = dict(rows)
    audit_diff(
        connection,
        user_email=user.email,
        entity_type="estimate_item",
        entity_id=str(item_id),
        before=current,
        after=payload,
        context="Edicion operativa a nivel partida",
    )
    document_repo.update_estimate_item_fields(connection, item_id, payload)

    if not propagate_mode:
        return
    units = document_repo.list_estimate_item_units(connection, item_id)
    for unit in units:
        unit_payload = {}
        for field_name, value in payload.items():
            if field_name not in {
                "receipt_status",
                "payment_status",
                "reception_date",
                "payment_date",
                "payment_method",
                "invoice_date",
                "invoice_number",
            }:
                continue
            if propagate_mode == "solo_vacios" and unit.get(field_name):
                continue
            unit_payload[field_name] = value
        if not unit_payload:
            continue
        audit_diff(
            connection,
            user_email=user.email,
            entity_type="estimate_item_unit",
            entity_id=str(unit["id"]),
            before=unit,
            after=unit_payload,
            context=f"Propagacion desde partida {item_id} ({propagate_mode})",
        )
        document_repo.update_estimate_unit_fields(connection, unit["id"], unit_payload)


def update_unit_operational_fields(
    connection: Connection,
    *,
    unit_id: int,
    payload: dict,
    user: AuthenticatedUser,
) -> None:
    row = connection.execute("SELECT * FROM estimate_item_units WHERE id = ?", (unit_id,)).fetchone()
    if not row:
        raise ValueError("Unidad no encontrada")
    current = dict(row)
    audit_diff(
        connection,
        user_email=user.email,
        entity_type="estimate_item_unit",
        entity_id=str(unit_id),
        before=current,
        after=payload,
        context="Edicion operativa a nivel unidad",
    )
    document_repo.update_estimate_unit_fields(connection, unit_id, payload)


def update_summary(
    connection: Connection,
    *,
    document_id: int,
    summary_user_edited: str,
    user: AuthenticatedUser,
) -> None:
    document = document_repo.get_document(connection, document_id)
    if not document:
        raise ValueError("Documento no encontrado")
    audit_repo.log_change(
        connection,
        user_email=user.email,
        entity_type="document",
        entity_id=str(document_id),
        field_name="summary_user_edited",
        old_value=document.get("summary_user_edited"),
        new_value=summary_user_edited,
        context="Resumen editable del documento",
    )
    document_repo.update_document_fields(
        connection,
        document_id,
        {"summary_user_edited": summary_user_edited},
    )


def update_document_inclusion_status(
    connection: Connection,
    *,
    document_id: int,
    inclusion_status: str,
    user: AuthenticatedUser,
) -> None:
    document = document_repo.get_document(connection, document_id)
    if not document:
        raise ValueError("Documento no encontrado")

    payload = {"inclusion_status": inclusion_status}
    if inclusion_status == "incluido" and document.get("document_status") == "descartado":
        payload["document_status"] = "activo"
        if document.get("duplicate_status") and document.get("duplicate_status") != "original":
            payload["duplicate_status"] = "kept_duplicate"

    audit_diff(
        connection,
        user_email=user.email,
        entity_type="document",
        entity_id=str(document_id),
        before=document,
        after=payload,
        context="Actualizacion manual de inclusion documental",
    )
    document_repo.update_document_fields(connection, document_id, payload)


def upsert_equipment_catalog_entry(
    connection: Connection,
    *,
    equipment_code: str,
    tower: str,
    position_name: str | None,
    display_name: str,
    user: AuthenticatedUser,
) -> None:
    current = equipment_repo.get_equipment_catalog_entry(connection, equipment_code)
    after = {
        "equipment_code": equipment_code.upper(),
        "tower": tower.upper(),
        "position_name": position_name.lower() if position_name else None,
        "display_name": display_name,
        "is_active": 1,
    }
    audit_diff(
        connection,
        user_email=user.email,
        entity_type="equipment_catalog",
        entity_id=equipment_code.upper(),
        before=current or {},
        after=after,
        context="Alta o edición de equipo en catálogo",
    )
    equipment_repo.upsert_equipment_catalog_entry(
        connection,
        equipment_code=equipment_code,
        tower=tower,
        position_name=position_name,
        display_name=display_name,
    )
    equipment_repo.upsert_equipment_alias(
        connection,
        alias_text=display_name,
        equipment_code=equipment_code,
        source="manual",
    )


def map_document_to_catalog(
    connection: Connection,
    *,
    document_id: int,
    equipment_code: str,
    alias_text: str | None,
    user: AuthenticatedUser,
) -> None:
    document = document_repo.get_document(connection, document_id)
    if not document:
        raise ValueError("Documento no encontrado")

    payload = {
        "equipment_code": equipment_code.upper(),
        "equipment_key": equipment_code.upper(),
    }
    catalog_row = equipment_repo.get_equipment_catalog_entry(connection, equipment_code)
    if catalog_row:
        payload["tower"] = catalog_row.get("tower")
        if catalog_row.get("position_name"):
            payload["position_id"] = document_repo.get_position_id(connection, catalog_row.get("position_name"))
    if alias_text and not document.get("equipment_text_original"):
        payload["equipment_text_original"] = alias_text

    audit_diff(
        connection,
        user_email=user.email,
        entity_type="document",
        entity_id=str(document_id),
        before=document,
        after=payload,
        context="Mapeo manual de documento a elevador en catálogo",
    )
    document_repo.update_document_fields(connection, document_id, payload)
    if alias_text:
        equipment_repo.upsert_equipment_alias(
            connection,
            alias_text=alias_text,
            equipment_code=equipment_code,
            source="manual",
        )


def map_estimate_item_to_catalog(
    connection: Connection,
    *,
    item_id: int,
    equipment_code: str,
    alias_text: str | None,
    user: AuthenticatedUser,
) -> None:
    row = connection.execute("SELECT * FROM estimate_items WHERE id = ?", (item_id,)).fetchone()
    if not row:
        raise ValueError("Partida no encontrada")
    current = dict(row)
    payload = {
        "equipment_code": equipment_code.upper(),
        "missing_catalog_equipment": 0,
    }
    if alias_text and not current.get("equipment_text_original"):
        payload["equipment_text_original"] = alias_text
    audit_diff(
        connection,
        user_email=user.email,
        entity_type="estimate_item",
        entity_id=str(item_id),
        before=current,
        after=payload,
        context="Mapeo manual de partida a elevador en catálogo",
    )
    document_repo.update_estimate_item_fields(connection, item_id, payload)
    if alias_text:
        equipment_repo.upsert_equipment_alias(
            connection,
            alias_text=alias_text,
            equipment_code=equipment_code,
            source="manual",
        )


def create_user_ticket(
    connection: Connection,
    *,
    payload: dict,
    user: AuthenticatedUser,
) -> int:
    user_ticket_id = user_ticket_repo.create_user_ticket(
        connection,
        document_date=payload["document_date"],
        document_time=payload.get("document_time"),
        tower=payload.get("tower"),
        equipment_code=payload.get("equipment_code"),
        equipment_text_original=payload.get("equipment_text_original"),
        description=payload["description"],
        ticket_state=payload.get("ticket_state") or "abierto",
        observations=payload.get("observations"),
        source_document_id=payload.get("source_document_id"),
        original_report_reference=payload.get("original_report_reference"),
        original_finding_reference=payload.get("original_finding_reference"),
        original_estimate_reference=payload.get("original_estimate_reference"),
        created_by_user_id=user.id,
    )
    ticket = user_ticket_repo.get_user_ticket(connection, user_ticket_id)
    audit_repo.log_change(
        connection,
        user_email=user.email,
        entity_type="user_ticket",
        entity_id=str(user_ticket_id),
        field_name="created",
        old_value=None,
        new_value=ticket.get("ticket_folio") if ticket else str(user_ticket_id),
        context="Creación manual de ticket usuario",
    )
    return user_ticket_id


def update_user_ticket_fields(
    connection: Connection,
    *,
    user_ticket_id: int,
    payload: dict,
    user: AuthenticatedUser,
) -> None:
    current = user_ticket_repo.get_user_ticket(connection, user_ticket_id)
    if not current:
        raise ValueError("Ticket usuario no encontrado")
    audit_diff(
        connection,
        user_email=user.email,
        entity_type="user_ticket",
        entity_id=str(user_ticket_id),
        before=current,
        after=payload,
        context=current.get("ticket_folio") or "Edición de ticket usuario",
    )
    user_ticket_repo.update_user_ticket_fields(connection, user_ticket_id, payload)


def update_user_ticket_case_link(
    connection: Connection,
    *,
    user_ticket_id: int,
    case_id: int,
    user: AuthenticatedUser,
) -> None:
    ticket = user_ticket_repo.get_user_ticket(connection, user_ticket_id)
    if not ticket:
        raise ValueError("Ticket usuario no encontrado")
    user_ticket_repo.link_user_ticket_to_case(
        connection,
        case_id=case_id,
        user_ticket_id=user_ticket_id,
        linked_by_user_id=user.id,
        notes="Mapeo manual desde catálogo/remediación",
    )
    audit_repo.log_change(
        connection,
        user_email=user.email,
        entity_type="user_ticket",
        entity_id=str(user_ticket_id),
        field_name="case_id",
        old_value=None,
        new_value=str(case_id),
        context=ticket.get("ticket_folio"),
    )
    case_service.refresh_case_status(connection, case_id)


def update_estimate_item_links(
    connection: Connection,
    *,
    item_id: int,
    report_document_id: int | None,
    finding_document_id: int | None,
    user_ticket_id: int | None,
    propagate_to_document: bool,
    user: AuthenticatedUser,
) -> None:
    row = connection.execute("SELECT * FROM estimate_items WHERE id = ?", (item_id,)).fetchone()
    if not row:
        raise ValueError("Partida no encontrada")
    current = dict(row)

    report_reference_text = current.get("report_reference_text")
    finding_reference_text = current.get("finding_reference_text")
    if report_document_id:
        report_document = document_repo.get_document_with_details(connection, report_document_id)
        report_reference_text = report_document.get("details", {}).get("ticket_number") or report_document.get("primary_identifier")
    if finding_document_id:
        finding_document = document_repo.get_document_with_details(connection, finding_document_id)
        finding_reference_text = (
            finding_document.get("details", {}).get("base_ticket_number")
            or finding_document.get("details", {}).get("finding_folio")
            or finding_document.get("primary_identifier")
        )

    payload = {
        "report_document_id": report_document_id,
        "finding_document_id": finding_document_id,
        "user_ticket_id": user_ticket_id,
        "report_reference_text": report_reference_text,
        "finding_reference_text": finding_reference_text,
        "missing_supporting_reference": 0 if (report_document_id or finding_document_id or report_reference_text or finding_reference_text) else 1,
    }
    audit_diff(
        connection,
        user_email=user.email,
        entity_type="estimate_item",
        entity_id=str(item_id),
        before=current,
        after=payload,
        context="Mapeo manual de soporte para partida de estimación",
    )
    document_repo.update_estimate_item_fields(connection, item_id, payload)

    estimate_document_id = int(current["estimate_document_id"])
    if propagate_to_document:
        connection.execute(
            """
            UPDATE estimate_items
            SET report_document_id = ?,
                finding_document_id = ?,
                user_ticket_id = ?,
                report_reference_text = ?,
                finding_reference_text = ?,
                missing_supporting_reference = ?
            WHERE estimate_document_id = ?
            """,
            (
                report_document_id,
                finding_document_id,
                user_ticket_id,
                report_reference_text,
                finding_reference_text,
                payload["missing_supporting_reference"],
                estimate_document_id,
            ),
        )
    _refresh_estimate_supporting_flags(connection, estimate_document_id)


def recalculate_estimate_delivery_dates(
    connection: Connection,
    *,
    estimate_document_id: int,
    user: AuthenticatedUser,
) -> None:
    estimate_row = connection.execute(
        """
        SELECT d.document_date, e.delivery_days, e.estimated_delivery_date
        FROM estimates e
        JOIN documents d ON d.id = e.document_id
        WHERE e.document_id = ?
        """,
        (estimate_document_id,),
    ).fetchone()
    if not estimate_row:
        raise ValueError("Estimación no encontrada")

    document_date = estimate_row["document_date"]
    if document_date and estimate_row["delivery_days"] is not None:
        new_estimate_date = (
            datetime.fromisoformat(document_date) + timedelta(days=int(estimate_row["delivery_days"]))
        ).date().isoformat()
    else:
        new_estimate_date = None

    audit_repo.log_change(
        connection,
        user_email=user.email,
        entity_type="estimate",
        entity_id=str(estimate_document_id),
        field_name="estimated_delivery_date",
        old_value=estimate_row["estimated_delivery_date"],
        new_value=new_estimate_date,
        context="Recalculo manual de fecha estimada de entrega",
    )
    connection.execute(
        """
        UPDATE estimates
        SET estimated_delivery_date = ?
        WHERE document_id = ?
        """,
        (new_estimate_date, estimate_document_id),
    )

    item_rows = document_repo.list_estimate_items(connection, estimate_document_id)
    for item in item_rows:
        delivery_days = item.get("delivery_days")
        if document_date and delivery_days is not None:
            new_item_date = (
                datetime.fromisoformat(document_date) + timedelta(days=int(delivery_days))
            ).date().isoformat()
        else:
            new_item_date = None
        audit_repo.log_change(
            connection,
            user_email=user.email,
            entity_type="estimate_item",
            entity_id=str(item["id"]),
            field_name="estimated_delivery_date",
            old_value=item.get("estimated_delivery_date"),
            new_value=new_item_date,
            context="Recalculo manual de fecha estimada de entrega",
        )
        document_repo.update_estimate_item_fields(
            connection,
            item["id"],
            {"estimated_delivery_date": new_item_date},
        )


def _refresh_estimate_supporting_flags(connection: Connection, estimate_document_id: int) -> None:
    row = connection.execute(
        """
        SELECT
            SUM(CASE WHEN COALESCE(missing_supporting_reference, 0) = 1 THEN 1 ELSE 0 END) AS missing_total,
            COUNT(*) AS total_items
        FROM estimate_items
        WHERE estimate_document_id = ?
        """,
        (estimate_document_id,),
    ).fetchone()
    total_items = int(row["total_items"] or 0) if row else 0
    missing_total = int(row["missing_total"] or 0) if row else 0
    missing_flag = 1 if total_items > 0 and missing_total == total_items else 0
    connection.execute(
        """
        UPDATE estimates
        SET missing_supporting_reference = ?
        WHERE document_id = ?
        """,
        (missing_flag, estimate_document_id),
    )


def update_user_status(
    connection: Connection,
    *,
    target_user_id: int,
    status: str,
    actor: AuthenticatedUser,
) -> None:
    user = user_repo.get_user_by_id(connection, target_user_id)
    if not user:
        raise ValueError("Usuario no encontrado")
    audit_repo.log_change(
        connection,
        user_email=actor.email,
        entity_type="user",
        entity_id=str(target_user_id),
        field_name="status",
        old_value=user.get("status"),
        new_value=status,
        context=user["email"],
    )
    user_repo.update_user_status(connection, target_user_id, status)
