"""Case creation, status suggestion and bundle builders."""

from __future__ import annotations

from sqlite3 import Connection

from gtv.repositories import cases as case_repo
from gtv.repositories import documents as document_repo
from gtv.repositories import user_tickets as user_ticket_repo
from gtv.services.classifiers import proximity_label
from gtv.utils.dates import days_between


def suggest_case_status(connection: Connection, case_id: int) -> str:
    reports = document_repo.list_documents_by_case_and_type(connection, case_id, "reporte")
    findings = document_repo.list_documents_by_case_and_type(connection, case_id, "hallazgo")
    estimates = document_repo.list_documents_by_case_and_type(connection, case_id, "estimacion")
    user_tickets = user_ticket_repo.list_case_user_tickets(connection, case_id)
    estimate_items = document_repo.list_estimate_items_for_case(connection, case_id)

    if not reports and not findings and not estimates and not user_tickets:
        return "pendiente_documentacion"
    if (findings or user_tickets) and not estimates:
        return "pendiente_revision"
    if estimates and any(item["receipt_status"] != "recibida_total" for item in estimate_items):
        return "pendiente_recepcion"
    if estimates and any(item["payment_status"] != "pagada_total" for item in estimate_items):
        return "pendiente_compra"

    report_open = any(
        connection.execute(
            "SELECT report_state FROM fault_reports WHERE document_id = ?",
            (report["id"],),
        ).fetchone()["report_state"]
        != "cerrado"
        for report in reports
    )
    finding_open = any(
        connection.execute(
            "SELECT finding_state FROM findings WHERE document_id = ?",
            (finding["id"],),
        ).fetchone()["finding_state"]
        != "cerrado"
        for finding in findings
    )
    estimate_open = any(
        connection.execute(
            "SELECT estimate_state FROM estimates WHERE document_id = ?",
            (estimate["id"],),
        ).fetchone()["estimate_state"]
        != "completada"
        for estimate in estimates
    )

    if report_open or finding_open or estimate_open:
        return "en_gestion"
    return "cerrado"


def create_case_from_document(
    connection: Connection,
    *,
    document: dict,
    user_id: int | None,
    origin: str,
) -> int:
    case_id = case_repo.create_case(
        connection,
        equipment_key=document["equipment_key"],
        tower=document.get("tower"),
        position_id=document.get("position_id"),
        equipment_text_original=document.get("equipment_text_original"),
        origin_document_id=document["id"],
        anchor_date=document.get("document_date"),
        suggested_consolidated_status="pendiente_documentacion",
        manual_consolidated_status=None,
        created_by_user_id=user_id,
    )
    document_repo.create_case_document_link(
        connection,
        case_id=case_id,
        document_id=document["id"],
        link_status="confirmada_manual",
        linked_by_user_id=user_id,
        origin=origin,
        notes="Caso creado desde documento origen",
    )
    refresh_case_status(connection, case_id)
    return case_id


def refresh_case_status(connection: Connection, case_id: int) -> None:
    status = suggest_case_status(connection, case_id)
    connection.execute(
        """
        UPDATE cases
        SET suggested_consolidated_status = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (status, case_id),
    )


def suggest_case_links_for_document(connection: Connection, *, document: dict) -> list[dict]:
    if not document.get("equipment_key") or not document.get("document_date"):
        return []
    candidates = case_repo.find_candidate_cases(
        connection,
        equipment_key=document["equipment_key"],
        document_date=document["document_date"],
    )
    suggestions: list[dict] = []
    for case in candidates:
        days_diff = days_between(document["document_date"], case.get("anchor_date"))
        label = proximity_label(days_diff)
        if label:
            document_repo.create_case_suggestion(
                connection,
                document_id=document["id"],
                case_id=case["id"],
                days_difference=days_diff or 0,
                proximity_label=label,
            )
            suggestions.append(case)
    return suggestions


def build_case_bundle(connection: Connection, case_id: int) -> dict | None:
    case = case_repo.get_case_by_id(connection, case_id)
    if not case:
        return None
    reports = document_repo.list_documents_by_case_and_type(connection, case_id, "reporte")
    findings_docs = document_repo.list_documents_by_case_and_type(connection, case_id, "hallazgo")
    estimate_docs = document_repo.list_documents_by_case_and_type(connection, case_id, "estimacion")
    user_tickets = user_ticket_repo.list_case_user_tickets(connection, case_id)
    findings = document_repo.list_findings_for_case(connection, case_id)
    estimate_items = document_repo.list_estimate_items_for_case(connection, case_id)
    units = document_repo.list_units_for_case(connection, case_id)
    matches = document_repo.list_matches_for_case(connection, case_id)
    return {
        "case": case,
        "reports": reports,
        "finding_documents": findings_docs,
        "estimate_documents": estimate_docs,
        "user_tickets": user_tickets,
        "findings": findings,
        "estimate_items": estimate_items,
        "units": units,
        "matches": matches,
    }
