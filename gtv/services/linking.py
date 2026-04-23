"""Manual and assisted case linking workflows."""

from __future__ import annotations

from sqlite3 import Connection

from gtv.repositories import documents as document_repo
from gtv.services import cases as case_service


def link_document_to_existing_case(
    connection: Connection,
    *,
    document_id: int,
    case_id: int,
    user_id: int,
) -> None:
    document_repo.create_case_document_link(
        connection,
        case_id=case_id,
        document_id=document_id,
        link_status="confirmada_manual",
        linked_by_user_id=user_id,
        origin="manual",
        notes="Confirmado manualmente desde bandeja de vinculacion",
    )
    for suggestion in document_repo.list_case_suggestions_for_document(connection, document_id):
        status = "confirmada_manual" if suggestion["case_id"] == case_id else "descartada"
        document_repo.update_case_suggestion_status(
            connection,
            suggestion_id=suggestion["id"],
            status=status,
            user_id=user_id,
        )
    document_repo.discard_other_case_suggestions(
        connection,
        document_id=document_id,
        keep_case_id=case_id,
        user_id=user_id,
    )
    case_service.refresh_case_status(connection, case_id)


def create_new_case_and_link(
    connection: Connection,
    *,
    document_id: int,
    user_id: int,
) -> int:
    document = document_repo.get_document(connection, document_id)
    if not document:
        raise ValueError("Documento no encontrado")
    case_id = case_service.create_case_from_document(
        connection,
        document=document,
        user_id=user_id,
        origin="manual",
    )
    for suggestion in document_repo.list_case_suggestions_for_document(connection, document_id):
        document_repo.update_case_suggestion_status(
            connection,
            suggestion_id=suggestion["id"],
            status="descartada",
            user_id=user_id,
        )
    return case_id
