"""Finding vs estimate assisted matching."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from gtv.models import AuthenticatedUser
from gtv.repositories import cases as case_repo
from gtv.repositories import documents as document_repo
from gtv.services import exports as export_service
from gtv.services import matching as matching_service
from gtv.views.common import mark_user_activity


def render(connection, user: AuthenticatedUser) -> None:
    st.header("Revisión piezas hallazgo vs estimación")
    cases = case_repo.list_cases(connection)
    if not cases:
        st.info("No hay casos para revisar.")
        return

    selected_label = st.selectbox(
        "Caso",
        options=[f"{case['id']} - {case['case_folio']}" for case in cases],
        index=next((index for index, case in enumerate(cases) if case["id"] == st.session_state.get("selected_case_id")), 0),
    )
    case_id = int(selected_label.split(" - ", 1)[0])
    st.session_state["selected_case_id"] = case_id

    if st.button("Recalcular sugerencias"):
        matching_service.refresh_case_matches(connection, case_id)
        mark_user_activity(connection)
        connection.commit()
        st.success("Sugerencias actualizadas.")
        st.rerun()

    matches = document_repo.list_matches_for_case(connection, case_id)
    if matches:
        st.dataframe(pd.DataFrame(matches), use_container_width=True)
        selected_match_label = st.selectbox(
            "Selecciona un match",
            options=[f"{match['id']} - {match['match_state']} - score {match['score']}" for match in matches],
        )
        match_id = int(selected_match_label.split(" - ", 1)[0])
        col1, col2 = st.columns(2)
        if col1.button("Confirmar match", key=f"confirm-match-{match_id}"):
            matching_service.confirm_match(connection, match_id=match_id, user_id=user.id)
            mark_user_activity(connection)
            connection.commit()
            st.success("Match confirmado.")
            st.rerun()
        if col2.button("Marcar como sin_match", key=f"mark-no-match-{match_id}"):
            matching_service.mark_match_state(connection, match_id=match_id, state="sin_match", user_id=user.id)
            mark_user_activity(connection)
            connection.commit()
            st.success("Estado actualizado.")
            st.rerun()

        excel_bytes = export_service.export_matches(matches)
        st.download_button(
            "Exportar diferencias a Excel",
            data=excel_bytes,
            file_name=export_service.export_filename("conciliacion_hallazgos_estimacion", "xlsx"),
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    findings = document_repo.list_findings_for_case(connection, case_id)
    items = document_repo.list_estimate_items_for_case(connection, case_id)
    if findings and items:
        st.subheader("Match manual")
        finding_label = st.selectbox(
            "Hallazgo",
            options=[f"{row['document_id']} - {row.get('finding_folio') or row.get('base_ticket_number') or 'sin folio'}" for row in findings],
        )
        item_label = st.selectbox(
            "Concepto estimacion",
            options=[f"{row['id']} - {row['concept_text'][:90]}" for row in items],
        )
        finding_document_id = int(finding_label.split(" - ", 1)[0])
        estimate_item_id = int(item_label.split(" - ", 1)[0])
        if st.button("Crear match manual confirmado"):
            matching_service.create_manual_match(
                connection,
                case_id=case_id,
                finding_document_id=finding_document_id,
                estimate_item_id=estimate_item_id,
                user_id=user.id,
            )
            mark_user_activity(connection)
            connection.commit()
            st.success("Match manual guardado.")
            st.rerun()
