"""Case listing view with operational filters and origin drill-down."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from gtv.constants import CASE_STATUS_PRESETS
from gtv.repositories import cases as case_repo
from gtv.services import cases as case_service
from gtv.utils.equipment import resolve_equipment_code_alias
from gtv.views.common import (
    document_reference_text,
    equipment_filter_selectbox,
    numbered_dataframe,
    request_navigation,
    tower_filter_selectbox,
)


def _source_label(case: dict) -> str:
    source_type = case.get("source_document_type")
    source_reference = case.get("source_reference") or "sin referencia"
    if source_type == "reporte":
        return f"REPORTE {source_reference}"
    if source_type == "hallazgo":
        return f"HALLAZGO {source_reference}"
    if source_type == "estimacion":
        return f"ESTIMACIÓN {source_reference}"
    return source_reference


def _effective_status(case: dict) -> str:
    return case.get("manual_consolidated_status") or case.get("suggested_consolidated_status") or ""


def _matches_free_text(case: dict, query: str) -> bool:
    if not query:
        return True
    needle = query.strip().lower()
    haystack = " ".join(
        [
            case.get("case_folio") or "",
            case.get("tower") or "",
            case.get("position_name") or "",
            case.get("equipment_text_original") or "",
            case.get("equipment_key") or "",
            case.get("source_document_type") or "",
            case.get("source_reference") or "",
            case.get("source_file_name") or "",
        ]
    ).lower()
    return needle in haystack


def _filter_cases(cases: list[dict], filters: dict) -> list[dict]:
    resolved_equipment_code = resolve_equipment_code_alias(filters.get("equipment"))
    filtered: list[dict] = []
    for case in cases:
        anchor_date = case.get("anchor_date") or ""
        if filters.get("date_from") and anchor_date and anchor_date < filters["date_from"]:
            continue
        if filters.get("date_to") and anchor_date and anchor_date > filters["date_to"]:
            continue
        if filters.get("status") and _effective_status(case) != filters["status"]:
            continue
        if filters.get("tower") and (case.get("tower") or "").upper() != filters["tower"].upper():
            continue
        equipment_haystack = " ".join(
            [
                case.get("equipment_text_original") or "",
                case.get("equipment_key") or "",
                case.get("position_name") or "",
            ]
        ).lower()
        if filters.get("equipment"):
            if resolved_equipment_code:
                if (case.get("equipment_key") or "").upper() != resolved_equipment_code:
                    continue
            elif filters["equipment"].lower() not in equipment_haystack:
                continue
        if not _matches_free_text(case, filters.get("free_text") or ""):
            continue
        filtered.append(case)
    return filtered


def _origin_rows(case: dict, bundle: dict) -> list[dict]:
    documents = [
        *bundle.get("reports", []),
        *bundle.get("finding_documents", []),
        *bundle.get("estimate_documents", []),
    ]
    rows: list[dict] = []
    for document in documents:
        rows.append(
            {
                "Origen": "Documento origen" if document["id"] == case.get("origin_document_id") else "Vinculado",
                "Tipo de documento": document.get("document_type") or "",
                "Ticket/reporte": document_reference_text(document),
                "Nombre del documento": document.get("file_name_original") or "",
            }
        )
    return rows


def render(connection) -> None:
    st.header("Listado de casos")
    st.caption("Filtra casos, selecciona uno en la tabla y revisa abajo su origen documental.")

    cases = case_repo.list_cases(connection)
    if not cases:
        st.info("Aun no hay casos creados.")
        return

    with st.form("case-list-filters"):
        date_range = st.date_input("Rango de fechas", value=(), key="case-list-dates")
        cols = st.columns(4)
        status = cols[0].selectbox("Status", options=[""] + CASE_STATUS_PRESETS, key="case-list-status")
        with cols[1]:
            tower = tower_filter_selectbox("Torre", key="case-list-tower")
        with cols[2]:
            equipment = equipment_filter_selectbox("Equipo", key="case-list-equipment")
        free_text = cols[3].text_input("Búsqueda texto libre", key="case-list-free-text")
        apply_filters = st.form_submit_button("Aplicar filtros")

    if apply_filters:
        st.session_state["case_list_filters"] = {
            "date_from": date_range[0].isoformat() if len(date_range) > 0 else None,
            "date_to": date_range[1].isoformat() if len(date_range) > 1 else (date_range[0].isoformat() if len(date_range) > 0 else None),
            "status": status or None,
            "tower": tower or None,
            "equipment": equipment or None,
            "free_text": free_text or None,
        }

    filters = st.session_state.get("case_list_filters", {})
    filtered_cases = _filter_cases(cases, filters)
    if not filtered_cases:
        st.info("No hay casos que coincidan con los filtros actuales.")
        return

    visible_case_ids = [case["id"] for case in filtered_cases]
    selected_case_id = st.session_state.get("selected_case_id")
    if selected_case_id not in visible_case_ids:
        selected_case_id = visible_case_ids[0]
        st.session_state["selected_case_id"] = selected_case_id

    table_rows = []
    for row_number, case in enumerate(filtered_cases):
        table_rows.append(
            {
                "Seleccionar": case["id"] == selected_case_id,
                "case_id": case["id"],
                "No.": row_number,
                "Caso": case["case_folio"],
                "Fecha": case.get("anchor_date") or "",
                "Status": _effective_status(case),
                "Torre": case.get("tower") or "",
                "Equipo": case.get("equipment_text_original") or case.get("equipment_key") or "",
                "Documento fuente": _source_label(case),
                "Archivo fuente": case.get("source_file_name") or "",
            }
        )

    table_df = pd.DataFrame(table_rows)
    edited_df = st.data_editor(
        table_df,
        hide_index=True,
        use_container_width=True,
        key="case-list-editor",
        disabled=[column for column in table_df.columns if column != "Seleccionar"],
        column_config={
            "Seleccionar": st.column_config.CheckboxColumn("Seleccionar"),
            "case_id": None,
        },
    )

    selected_rows = edited_df[edited_df["Seleccionar"] == True]
    if len(selected_rows) > 1:
        st.warning("Selecciona solo un caso a la vez. Se mostrara el primero marcado.")
    if not selected_rows.empty:
        selected_case_id = int(selected_rows.iloc[0]["case_id"])
        st.session_state["selected_case_id"] = selected_case_id

    selected_case = next((case for case in filtered_cases if case["id"] == selected_case_id), None)
    if not selected_case:
        st.info("Selecciona un caso para ver su origen documental.")
        return

    bundle = case_service.build_case_bundle(connection, selected_case_id)
    if not bundle:
        st.error("No se encontro el caso seleccionado.")
        return

    st.subheader(f"Origen documental del caso {selected_case['case_folio']}")
    origin_rows = _origin_rows(selected_case, bundle)
    if origin_rows:
        st.dataframe(numbered_dataframe(origin_rows, start=0), use_container_width=True)
    else:
        st.caption("Este caso aun no tiene documentos vinculados.")

    if st.button("Abrir detalle del caso", key=f"open-case-detail-{selected_case_id}"):
        request_navigation("Detalle de caso", selected_case_id=selected_case_id)
        st.rerun()
