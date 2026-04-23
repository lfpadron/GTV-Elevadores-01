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
    mark_user_activity,
    render_pdf_preview,
    tower_filter_selectbox,
)


def _origin_label(row: dict) -> str:
    source_type = row.get("document_type") or ""
    reference = row.get("source_reference") or row.get("primary_identifier") or "sin referencia"
    if source_type == "reporte":
        return f"Reporte {reference}"
    if source_type == "hallazgo":
        return f"Hallazgo {reference}"
    if source_type == "estimacion":
        return f"Estimación {reference}"
    return f"{source_type.title()} {reference}".strip()


def render(connection, user: AuthenticatedUser) -> None:
    st.header("Busqueda")
    structured_tab, text_tab = st.tabs(["Filtros estructurados", "Texto libre FTS5"])

    with structured_tab:
        with st.form("structured-search-form"):
            date_range = st.date_input("Rango de fechas", value=())
            ticket = st.text_input("Numero de ticket o identificador")
            cols = st.columns(4)
            with cols[0]:
                tower = tower_filter_selectbox("Torre", key="structured-tower")
            with cols[1]:
                equipment = equipment_filter_selectbox("Equipo", key="structured-equipment")
            state = cols[2].text_input("Estado")
            submit_structured = cols[3].form_submit_button("Buscar")
        if submit_structured:
            date_from = date_range[0] if len(date_range) > 0 else None
            date_to = date_range[1] if len(date_range) > 1 else date_from
            filters = {
                "date_from": date_from.isoformat() if date_from else None,
                "date_to": date_to.isoformat() if date_to else None,
                "ticket_or_identifier": ticket or None,
                "tower": tower or None,
                "equipment": equipment or None,
                "state": state or None,
            }
            st.session_state["structured_search_filters"] = filters
            st.session_state["structured_results"] = search_service.run_structured_search(connection, filters)
            mark_user_activity(connection)
            connection.commit()

        rows = st.session_state.get("structured_results", [])
        if rows:
            active_filters = st.session_state.get("structured_search_filters", {})
            selected_document_id = st.session_state.get("selected_structured_document_id")
            visible_ids = [row["document_id"] for row in rows]
            if selected_document_id not in visible_ids:
                selected_document_id = visible_ids[0]
                st.session_state["selected_structured_document_id"] = selected_document_id

            table_rows = [
                {
                    "Seleccionar": row["document_id"] == selected_document_id,
                    "document_id": row["document_id"],
                    "origen_documental": row.get("document_type") or "",
                    "referencia_origen": row.get("source_reference") or row.get("primary_identifier") or "",
                    "identificador_principal": row.get("primary_identifier") or "",
                    "fecha": row.get("document_date") or "",
                    "hora": row.get("document_time") or "",
                    "torre": row.get("tower") or "",
                    "equipo": row.get("equipment_text_original") or row.get("position_name") or "",
                    "estado": row.get("current_state") or "",
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
                    "document_id": None,
                },
            )

            selected_rows = edited_df[edited_df["Seleccionar"] == True]
            if len(selected_rows) > 1:
                st.warning("Selecciona solo un documento a la vez. Se mostrará el primero marcado.")
            if not selected_rows.empty:
                selected_document_id = int(selected_rows.iloc[0]["document_id"])
                st.session_state["selected_structured_document_id"] = selected_document_id

            criteria_lines = export_service.format_filter_criteria(
                active_filters,
                {
                    "date_from": "Fecha desde",
                    "date_to": "Fecha hasta",
                    "ticket_or_identifier": "Ticket o identificador",
                    "tower": "Torre",
                    "equipment": "Equipo",
                    "state": "Estado",
                },
            )
            excel_bytes, pdf_bytes = export_service.export_search_rows(rows, criteria_lines=criteria_lines)
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

            selected_row = next((row for row in rows if row["document_id"] == selected_document_id), None)
            if selected_row:
                st.subheader("Documento seleccionado")
                st.write(f"Documento original: {selected_row.get('file_name_original') or ''}")
                st.write(f"Origen: {_origin_label(selected_row)}")
                if st.checkbox("Previsualizar documento seleccionado", key=f"structured-preview-{selected_document_id}"):
                    storage_path = selected_row.get("storage_path")
                    if storage_path:
                        render_pdf_preview(storage_path, key=f"structured-pdf-{selected_document_id}")
                    else:
                        st.error("El documento seleccionado no tiene ruta de archivo asociada.")

    with text_tab:
        with st.form("fts-search-form"):
            free_text = st.text_input("Texto libre")
            cols = st.columns(3)
            with cols[0]:
                tower_fts = tower_filter_selectbox("Torre (opcional)", key="tower-fts")
            with cols[1]:
                equipment_fts = equipment_filter_selectbox("Equipo (opcional)", key="equipment-fts")
            submit_fts = cols[2].form_submit_button("Buscar en texto")
        if submit_fts and free_text:
            filters = {
                "free_text": free_text,
                "tower": tower_fts or None,
                "equipment": equipment_fts or None,
            }
            results, error = search_service.run_full_text_search(connection, filters)
            st.session_state["fts_results"] = results
            st.session_state["fts_error"] = error
            mark_user_activity(connection)
            connection.commit()

        if st.session_state.get("fts_error"):
            st.error(st.session_state["fts_error"])
        fts_rows = st.session_state.get("fts_results", [])
        if fts_rows:
            visible_keys = [f"{row['document_id']}:{row['page_number']}" for row in fts_rows]
            selected_result_key = st.session_state.get("selected_fts_result_key")
            if selected_result_key not in visible_keys:
                selected_result_key = visible_keys[0]
                st.session_state["selected_fts_result_key"] = selected_result_key

            table_rows = [
                {
                    "Seleccionar": f"{row['document_id']}:{row['page_number']}" == selected_result_key,
                    "result_key": f"{row['document_id']}:{row['page_number']}",
                    "documento_original": row.get("file_name_original") or "",
                    "pagina": row.get("page_number") or 0,
                    "origen_documental": _origin_label(row),
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

            selected_row = next(
                (
                    row
                    for row in fts_rows
                    if f"{row['document_id']}:{row['page_number']}" == selected_result_key
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
                    key=f"fts-preview-{selected_row['document_id']}-{selected_row['page_number']}",
                ):
                    render_pdf_preview(selected_row["storage_path"], key=f"fts-pdf-{selected_row['document_id']}")
                pdf_path = Path(selected_row["storage_path"])
                if pdf_path.exists():
                    st.download_button(
                        "Descargar documento seleccionado",
                        data=pdf_path.read_bytes(),
                        file_name=pdf_path.name,
                        mime="application/pdf",
                        key=f"download-{selected_row['document_id']}-{selected_row['page_number']}",
                    )
