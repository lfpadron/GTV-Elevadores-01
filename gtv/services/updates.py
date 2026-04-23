"""Manual update workflows with audit logging."""

from __future__ import annotations

from sqlite3 import Connection

from gtv.models import AuthenticatedUser
from gtv.repositories import audit as audit_repo
from gtv.repositories import cases as case_repo
from gtv.repositories import documents as document_repo
from gtv.repositories import users as user_repo
from gtv.services import cases as case_service
from gtv.services.auditing import audit_diff
from gtv.utils.equipment import infer_equipment_code, normalize_equipment_key


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
