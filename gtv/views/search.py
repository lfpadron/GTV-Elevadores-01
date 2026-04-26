"""Structured and full-text search views."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from gtv.models import AuthenticatedUser
from gtv.services import exports as export_service
from gtv.services import search as search_service
from gtv.views.common import (
    equipment_filter_selectbox,
    inclusion_filter_selectbox,
    mark_user_activity,
    render_pdf_preview,
    tower_filter_selectbox,
)

DOCUMENT_TYPE_OPTIONS = ["", "reporte", "hallazgo", "ticket_usuario", "estimacion"]


def _origin_label(row: dict) -> str:
    source_type = row.get("document_type") or ""
    reference = row.get("source_reference") or row.get("primary_identifier") or "sin referencia"
    if source_type == "reporte":
        return f"Reporte {reference}"
    if source_type == "hallazgo":
        return f"Hallazgo {reference}"
    if source_type == "ticket_usuario":
        return f"Ticket usuario {reference}"
    if source_type == "estimacion":
        return f"Estimación {reference}"
    return f"{source_type.title()} {reference}".strip()


def _document_type_filter_label(value: str) -> str:
    labels = {
        "reporte": "Reporte",
        "hallazgo": "Hallazgo",
        "ticket_usuario": "Ticket usuario",
        "estimacion": "Estimación",
    }
    return labels.get(value, value.title())


def render(connection, user: AuthenticatedUser) -> None:
    st.header("Busqueda")
    structured_tab, text_tab = st.tabs(["Filtros estructurados", "Texto libre FTS5"])

    with structured_tab:
        with st.form("structured-search-form"):
            date_range = st.date_input("Rango de fechas", value=())
            ticket = st.text_input("Numero de ticket o identificador")
            cols = st.columns(5)
            with cols[0]:
                tower = tower_filter_selectbox("Torre", key="structured-tower")
            with cols[1]:
                equipment = equipment_filter_selectbox("Equipo", key="structured-equipment", tower=tower, include_other=True)
            with cols[2]:
                document_type = st.selectbox(
                    "Tipo de documento",
                    options=DOCUMENT_TYPE_OPTIONS,
                    key="structured-document-type",
                    format_func=lambda value: "Todos" if value == "" else _document_type_filter_label(value),
                )
            with cols[3]:
                inclusion_status = inclusion_filter_selectbox("Incluidos / ignorados", key="structured-inclusion")
            submit_structured = cols[4].form_submit_button("Buscar")
        if submit_structured:
            date_from = date_range[0] if len(date_range) > 0 else None
            date_to = date_range[1] if len(date_range) > 1 else date_from
            filters = {
                "date_from": date_from.isoformat() if date_from else None,
                "date_to": date_to.isoformat() if date_to else None,
                "ticket_or_identifier": ticket or None,
                "tower": tower or None,
                "equipment": equipment or None,
                "document_type": document_type or None,
                "inclusion_status": inclusion_status or None,
            }
            st.session_state["structured_search_filters"] = filters
            st.session_state["structured_results"] = search_service.run_structured_search(connection, filters)
            mark_user_activity(connection)
            connection.commit()

        rows = st.session_state.get("structured_results", [])
        if rows:
            active_filters = st.session_state.get("structured_search_filters", {})
            selected_record_key = st.session_state.get("selected_structured_record_key")
            visible_keys = [row["record_key"] for row in rows]
            if selected_record_key not in visible_keys:
                selected_record_key = visible_keys[0]
                st.session_state["selected_structured_record_key"] = selected_record_key

            table_rows = [
                {
                    "Seleccionar": row["record_key"] == selected_record_key,
                    "record_key": row["record_key"],
                    "origen_documental": row.get("document_type") or "",
                    "referencia_origen": row.get("source_reference") or row.get("primary_identifier") or "",
                    "identificador_principal": row.get("primary_identifier") or "",
                    "fecha": row.get("document_date") or "",
                    "hora": row.get("document_time") or "",
                    "torre": row.get("tower") or "",
                    "equipo": row.get("equipment_text_original") or row.get("position_name") or "",
                    "estado": row.get("current_state") or "",
                    "incluido_ignorado": (row.get("inclusion_status") or "incluido").title(),
                    "causa": row.get("cause_text") or "",
                    "recomendacion": row.get("recommendation_text") or "",
                    "documento_original": row.get("file_name_original") or "",
                    "descripcion_sucinta": row.get("concise_description") or row.get("short_description") or "",
                }
                for row in rows
            ]
            table_df = pd.DataFrame(table_rows)
            edited_df = st.data_editor(
                table_df,
                hide_index=True,
                use_container_width=True,
                key="structured-search-editor",
                disabled=[column for column in table_df.columns if column != "Seleccionar"],
                column_config={
                    "Seleccionar": st.column_config.CheckboxColumn("Seleccionar"),
                    "record_key": None,
                },
            )

            selected_rows = edited_df[edited_df["Seleccionar"] == True]
            if len(selected_rows) > 1:
                st.warning("Selecciona solo un documento a la vez. Se mostrará el primero marcado.")
            if not selected_rows.empty:
                selected_record_key = str(selected_rows.iloc[0]["record_key"])
                st.session_state["selected_structured_record_key"] = selected_record_key

            criteria_lines = export_service.format_filter_criteria(
                active_filters,
                {
                    "date_from": "Fecha desde",
                    "date_to": "Fecha hasta",
                    "ticket_or_identifier": "Ticket o identificador",
                    "tower": "Torre",
                    "equipment": "Equipo",
                    "document_type": "Tipo de documento",
                    "inclusion_status": "Incluidos / ignorados",
                },
            )
            export_rows = [
                {key: value for key, value in row.items() if key not in {"Seleccionar", "record_key"}}
                for row in table_rows
            ]
            excel_bytes, pdf_bytes = export_service.export_search_rows(export_rows, criteria_lines=criteria_lines)
            st.download_button(
                "Exportar Excel",
                data=excel_bytes,
                file_name=export_service.export_filename("tickets_filtrados", "xlsx"),
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            st.download_button(
                "Exportar PDF",
                data=pdf_bytes,
                file_name=export_service.export_filename("tickets_filtrados", "pdf"),
                mime="application/pdf",
            )

            selected_row = next((row for row in rows if row["record_key"] == selected_record_key), None)
            if selected_row:
                st.subheader("Documento seleccionado")
                st.write(f"Documento original: {selected_row.get('file_name_original') or ''}")
                st.write(f"Origen: {_origin_label(selected_row)}")
                if st.checkbox("Previsualizar documento seleccionado", key=f"structured-preview-{selected_record_key}"):
                    storage_path = selected_row.get("storage_path")
                    if storage_path:
                        render_pdf_preview(storage_path, key=f"structured-pdf-{selected_record_key}")
                    else:
                        st.info("El registro seleccionado no tiene PDF propio para previsualizar.")

    with text_tab:
        with st.form("fts-search-form"):
            free_text = st.text_input("Texto libre")
            cols = st.columns(5)
            with cols[0]:
                tower_fts = tower_filter_selectbox("Torre (opcional)", key="tower-fts")
            with cols[1]:
                equipment_fts = equipment_filter_selectbox("Equipo (opcional)", key="equipment-fts", tower=tower_fts, include_other=True)
            with cols[2]:
                document_type_fts = st.selectbox(
                    "Tipo de documento",
                    options=DOCUMENT_TYPE_OPTIONS,
                    key="fts-document-type",
                    format_func=lambda value: "Todos" if value == "" else _document_type_filter_label(value),
                )
            with cols[3]:
                inclusion_fts = inclusion_filter_selectbox("Incluidos / ignorados", key="fts-inclusion")
            submit_fts = cols[4].form_submit_button("Buscar en texto")
        if submit_fts and free_text:
            filters = {
                "free_text": free_text,
                "tower": tower_fts or None,
                "equipment": equipment_fts or None,
                "document_type": document_type_fts or None,
                "inclusion_status": inclusion_fts or None,
            }
            results, error = search_service.run_full_text_search(connection, filters)
            st.session_state["fts_results"] = results
            st.session_state["fts_error"] = error
            st.session_state["fts_filters"] = filters
            mark_user_activity(connection)
            connection.commit()

        if st.session_state.get("fts_error"):
            st.error(st.session_state["fts_error"])
        fts_rows = st.session_state.get("fts_results", [])
        if fts_rows:
            visible_keys = [row["record_key"] for row in fts_rows]
            selected_result_key = st.session_state.get("selected_fts_result_key")
            if selected_result_key not in visible_keys:
                selected_result_key = visible_keys[0]
                st.session_state["selected_fts_result_key"] = selected_result_key

            table_rows = [
                {
                    "Seleccionar": row["record_key"] == selected_result_key,
                    "result_key": row["record_key"],
                    "causa": row.get("cause_text") or "",
                    "recomendacion": row.get("recommendation_text") or "",
                    "documento_original": row.get("file_name_original") or "",
                    "pagina": row.get("page_number") or 0,
                    "origen_documental": _origin_label(row),
                    "incluido_ignorado": (row.get("inclusion_status") or "incluido").title(),
                    "fecha_documento": row.get("document_date") or "",
                    "snippet": row.get("snippet") or "",
                }
                for row in fts_rows
            ]
            table_df = pd.DataFrame(table_rows)
            edited_df = st.data_editor(
                table_df,
                hide_index=True,
                use_container_width=True,
                key="fts-search-editor",
                disabled=[column for column in table_df.columns if column != "Seleccionar"],
                column_config={
                    "Seleccionar": st.column_config.CheckboxColumn("Seleccionar"),
                    "result_key": None,
                },
            )

            selected_rows = edited_df[edited_df["Seleccionar"] == True]
            if len(selected_rows) > 1:
                st.warning("Selecciona solo un resultado a la vez. Se mostrará el primero marcado.")
            if not selected_rows.empty:
                selected_result_key = str(selected_rows.iloc[0]["result_key"])
                st.session_state["selected_fts_result_key"] = selected_result_key

            active_fts_filters = st.session_state.get("fts_filters", {})
            criteria_lines = export_service.format_filter_criteria(
                active_fts_filters,
                {
                    "free_text": "Texto libre",
                    "tower": "Torre",
                    "equipment": "Equipo",
                    "document_type": "Tipo de documento",
                    "inclusion_status": "Incluidos / ignorados",
                },
            )
            export_rows = [
                {key: value for key, value in row.items() if key not in {"Seleccionar", "result_key"}}
                for row in table_rows
            ]
            excel_bytes, pdf_bytes = export_service.export_search_rows(export_rows, criteria_lines=criteria_lines)
            export_cols = st.columns(2)
            export_cols[0].download_button(
                "Exportar Excel",
                data=excel_bytes,
                file_name=export_service.export_filename("busqueda_texto_libre", "xlsx"),
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="fts-export-excel",
            )
            export_cols[1].download_button(
                "Exportar PDF",
                data=pdf_bytes,
                file_name=export_service.export_filename("busqueda_texto_libre", "pdf"),
                mime="application/pdf",
                key="fts-export-pdf",
            )

            selected_row = next(
                (
                    row
                    for row in fts_rows
                    if row["record_key"] == selected_result_key
                ),
                None,
            )
            if selected_row:
                st.subheader("Resultado seleccionado")
                st.write(f"Documento original: {selected_row.get('file_name_original') or ''}")
                st.write(f"Origen: {_origin_label(selected_row)}")
                st.write(f"Fecha del documento: {selected_row.get('document_date') or 'sin fecha'}")
                st.write(f"Página: {selected_row.get('page_number') or 0}")
                st.write(selected_row.get("snippet") or "")
                if st.checkbox(
                    "Previsualizar documento seleccionado",
                    key=f"fts-preview-{selected_result_key}",
                ):
                    storage_path = selected_row.get("storage_path")
                    if storage_path:
                        render_pdf_preview(storage_path, key=f"fts-pdf-{selected_result_key}")
                    else:
                        st.info("El registro seleccionado no tiene PDF propio para previsualizar.")
                storage_path = selected_row.get("storage_path")
                pdf_path = Path(storage_path) if storage_path else None
                if pdf_path and pdf_path.exists():
                    st.download_button(
                        "Descargar documento seleccionado",
                        data=pdf_path.read_bytes(),
                        file_name=pdf_path.name,
                        mime="application/pdf",
                        key=f"download-{selected_result_key}",
                    )
