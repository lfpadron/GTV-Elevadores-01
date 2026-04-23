"""Loaded documents operational tray."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from gtv.models import AuthenticatedUser
from gtv.repositories import documents as document_repo
from gtv.services import updates as update_service
from gtv.utils.equipment import is_catalog_equipment_code
from gtv.views.common import (
    equipment_filter_selectbox,
    mark_user_activity,
    render_pdf_preview,
    tower_filter_selectbox,
)

DOCUMENT_TYPE_OPTIONS = ["", "reporte", "hallazgo", "estimacion", "duplicado"]


def render(connection, user: AuthenticatedUser) -> None:
    st.header("Documentos cargados")
    st.caption("Revisa rápidamente los documentos cargados, su origen y si deben quedar incluidos o ignorados.")

    with st.form("loaded-documents-filters"):
        date_range = st.date_input("Rango de fechas", value=(), key="loaded-documents-dates")
        cols = st.columns(4)
        with cols[0]:
            tower = tower_filter_selectbox("Torre", key="loaded-documents-tower")
        with cols[1]:
            equipment = equipment_filter_selectbox(
                "Equipo",
                key="loaded-documents-equipment",
                include_other=True,
            )
        with cols[2]:
            document_type = st.selectbox(
                "Tipo de documento",
                options=DOCUMENT_TYPE_OPTIONS,
                format_func=lambda value: "Todos" if value == "" else _filter_type_label(value),
                key="loaded-documents-type",
            )
        submitted = cols[3].form_submit_button("Aplicar filtros")

    if submitted:
        st.session_state["loaded_documents_filters"] = {
            "date_from": date_range[0].isoformat() if len(date_range) > 0 else None,
            "date_to": date_range[1].isoformat() if len(date_range) > 1 else (date_range[0].isoformat() if len(date_range) > 0 else None),
            "tower": tower or None,
            "equipment": equipment or None,
            "document_type": document_type or None,
        }
        mark_user_activity(connection)
        connection.commit()

    filters = st.session_state.get("loaded_documents_filters", {})
    rows = document_repo.list_loaded_documents(connection, filters)
    if not rows:
        st.info("No se encontraron documentos con esos filtros.")
        return

    selected_document_id = st.session_state.get("selected_loaded_document_id")
    visible_ids = [row["document_id"] for row in rows]
    if selected_document_id not in visible_ids:
        selected_document_id = visible_ids[0]
        st.session_state["selected_loaded_document_id"] = selected_document_id

    table_rows = [
        {
            "Seleccionar": row["document_id"] == selected_document_id,
            "document_id": row["document_id"],
            "Fecha": row.get("document_date") or "",
            "Hora": row.get("document_time") or "",
            "Tipo de documento": _document_type_label(row),
            "Nombre del documento": row.get("file_name_original") or "",
            "Torre, equipo": _equipment_label(row),
            "Descripción suscinta": row.get("concise_description") or "",
        }
        for row in rows
    ]

    table_df = pd.DataFrame(table_rows)
    edited_df = st.data_editor(
        table_df,
        hide_index=True,
        use_container_width=True,
        key="loaded-documents-editor",
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
        st.session_state["selected_loaded_document_id"] = selected_document_id

    selected_row = next((row for row in rows if row["document_id"] == selected_document_id), None)
    if not selected_row:
        return

    st.subheader("Documento seleccionado")
    st.write(f"Documento original: {selected_row.get('file_name_original') or ''}")
    st.write(f"Tipo: {_document_type_label(selected_row)}")
    st.write(f"Torre / equipo: {_equipment_label(selected_row)}")
    st.caption(f"Estado actual: {(selected_row.get('inclusion_status') or 'incluido').title()}")

    action_cols = st.columns(3)
    if action_cols[0].button("Previsualizar documento", key=f"loaded-preview-{selected_document_id}", use_container_width=True):
        storage_path = selected_row.get("storage_path")
        if storage_path:
            render_pdf_preview(storage_path, key=f"loaded-pdf-{selected_document_id}")
        else:
            st.error("El documento seleccionado no tiene ruta de archivo asociada.")

    if action_cols[1].button("Ignorar", key=f"loaded-ignore-{selected_document_id}", use_container_width=True):
        update_service.update_document_inclusion_status(
            connection,
            document_id=selected_document_id,
            inclusion_status="ignorado",
            user=user,
        )
        mark_user_activity(connection)
        connection.commit()
        st.success("Documento marcado como ignorado.")
        st.rerun()

    if action_cols[2].button("Incluir", key=f"loaded-include-{selected_document_id}", use_container_width=True):
        update_service.update_document_inclusion_status(
            connection,
            document_id=selected_document_id,
            inclusion_status="incluido",
            user=user,
        )
        mark_user_activity(connection)
        connection.commit()
        st.success("Documento marcado como incluido.")
        st.rerun()


def _filter_type_label(value: str) -> str:
    labels = {
        "reporte": "Reporte",
        "hallazgo": "Hallazgo",
        "estimacion": "Estimación",
        "duplicado": "Duplicado",
        "no_reconocido": "No reconocido",
    }
    return labels.get(value, value.title())


def _document_type_label(row: dict) -> str:
    if row.get("duplicate_status") and row.get("duplicate_status") != "original":
        return "Duplicado"
    return _filter_type_label(row.get("document_type") or "")


def _equipment_label(row: dict) -> str:
    pieces = [row.get("tower") or ""]
    if not is_catalog_equipment_code(row.get("equipment_code")):
        pieces.append("Sin catálogo")
    if row.get("equipment_code"):
        pieces.append(row["equipment_code"])
    if row.get("position_name"):
        pieces.append(row["position_name"])
    if row.get("equipment_text_original"):
        pieces.append(row["equipment_text_original"])
    return " | ".join(piece for piece in pieces if piece)
