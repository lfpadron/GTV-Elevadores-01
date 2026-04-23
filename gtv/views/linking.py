"""Pending linking workflow."""

from __future__ import annotations

import streamlit as st

from gtv.models import AuthenticatedUser
from gtv.repositories import cases as case_repo
from gtv.repositories import documents as document_repo
from gtv.services import linking as linking_service
from gtv.views.common import mark_user_activity, numbered_dataframe, request_navigation


def render(connection, user: AuthenticatedUser) -> None:
    st.header("Vinculacion pendiente")
    documents = document_repo.list_documents_without_case(connection)
    if not documents:
        st.success("No hay documentos pendientes de vinculacion.")
        return

    display_rows = [
        {
            "documento_id": doc["id"],
            "tipo": doc.get("document_type") or "",
            "identificador": doc.get("primary_identifier") or "",
            "fecha": doc.get("document_date") or "",
            "hora": doc.get("document_time") or "",
            "torre": doc.get("tower") or "",
            "posicion": doc.get("position_name") or "",
            "equipo": doc.get("equipment_text_original") or "",
            "archivo": doc.get("file_name_original") or "",
        }
        for doc in documents
    ]
    st.dataframe(numbered_dataframe(display_rows, start=0), use_container_width=True)
    selected_label = st.selectbox(
        "Documento",
        options=[f"{doc['id']} - {doc['file_name_original']}" for doc in documents],
    )
    document_id = int(selected_label.split(" - ", 1)[0])
    document = next(doc for doc in documents if doc["id"] == document_id)
    st.json(
        {
            "tipo": document["document_type"],
            "identificador": document.get("primary_identifier"),
            "fecha": document.get("document_date"),
            "equipo": document.get("equipment_text_original"),
        }
    )

    suggestions = document_repo.list_case_suggestions_for_document(connection, document_id)
    if suggestions:
        st.markdown("**Sugerencias del sistema**")
        st.dataframe(numbered_dataframe(suggestions, start=0), use_container_width=True)
        for suggestion in suggestions:
            if st.button(
                f"Confirmar vinculo con {suggestion['case_folio']} ({suggestion['proximity_label']})",
                key=f"confirm-suggestion-{suggestion['id']}",
            ):
                linking_service.link_document_to_existing_case(
                    connection,
                    document_id=document_id,
                    case_id=suggestion["case_id"],
                    user_id=user.id,
                )
                mark_user_activity(connection)
                connection.commit()
                st.success("Documento vinculado al caso.")
                st.rerun()

    all_cases = case_repo.list_cases(connection)
    if all_cases:
        manual_case_label = st.selectbox(
            "Vincular a un caso existente",
            options=[f"{case['id']} - {case['case_folio']}" for case in all_cases],
        )
        manual_case_id = int(manual_case_label.split(" - ", 1)[0])
        if st.button("Vincular manualmente al caso seleccionado"):
            linking_service.link_document_to_existing_case(
                connection,
                document_id=document_id,
                case_id=manual_case_id,
                user_id=user.id,
            )
            mark_user_activity(connection)
            connection.commit()
            st.success("Vinculacion manual realizada.")
            st.rerun()

    if st.button("Crear caso nuevo con este documento"):
        new_case_id = linking_service.create_new_case_and_link(
            connection,
            document_id=document_id,
            user_id=user.id,
        )
        request_navigation("Detalle de caso", selected_case_id=new_case_id)
        mark_user_activity(connection)
        connection.commit()
        st.success("Se creo un nuevo caso.")
        st.rerun()
