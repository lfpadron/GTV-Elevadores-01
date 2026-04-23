"""Document correlation report across reports, findings and estimates."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from gtv.models import AuthenticatedUser
from gtv.repositories import listings as listings_repo
from gtv.services import exports as export_service
from gtv.utils.equipment import (
    EQUIPMENT_OTHER_FILTER_VALUE,
    format_equipment_filter_option,
    is_catalog_equipment_code,
    list_equipment_filter_codes,
)
from gtv.views.common import (
    mark_user_activity,
    render_pdf_preview,
    tower_filter_selectbox,
)

DOCUMENT_TYPE_OPTIONS = ["", "reporte", "hallazgo", "estimacion"]


def render(connection, user: AuthenticatedUser) -> None:
    st.header("Reporte de hallazgos")
    st.caption("Correlaciona rápidamente equipo y documento que lo menciona, con exportación y previsualización.")

    if "finding_report_filters" not in st.session_state:
        st.session_state["finding_report_filters"] = {}

    with st.form("finding-report-filters"):
        date_range = st.date_input("Rango de fechas", value=(), key="finding-report-dates")
        cols = st.columns(4)
        with cols[0]:
            tower = tower_filter_selectbox("Torre", key="finding-report-tower")
        with cols[1]:
            equipment = st.selectbox(
                "Equipo",
                options=["", *list_equipment_filter_codes(), EQUIPMENT_OTHER_FILTER_VALUE],
                key="finding-report-equipment",
                format_func=lambda value: "Todos" if value == "" else format_equipment_filter_option(value),
            ) or None
        document_type = cols[2].selectbox(
            "Tipo de documento",
            options=DOCUMENT_TYPE_OPTIONS,
            key="finding-report-document-type",
            format_func=lambda value: "Todos" if value == "" else value.title(),
        )
        submitted = cols[3].form_submit_button("Aplicar filtros")

    if submitted:
        st.session_state["finding_report_filters"] = {
            "date_from": date_range[0].isoformat() if len(date_range) > 0 else None,
            "date_to": date_range[1].isoformat() if len(date_range) > 1 else (date_range[0].isoformat() if len(date_range) > 0 else None),
            "tower": tower or None,
            "equipment": equipment or None,
            "document_type": document_type or None,
        }
        mark_user_activity(connection)
        connection.commit()

    rows = listings_repo.list_hallazgo_report_rows(connection, st.session_state.get("finding_report_filters", {}))
    if not rows:
        st.info("No se encontraron documentos con esos filtros.")
        return

    selected_document_id = st.session_state.get("selected_finding_report_document_id")
    visible_ids = [row["document_id"] for row in rows]
    if selected_document_id not in visible_ids:
        selected_document_id = visible_ids[0]
        st.session_state["selected_finding_report_document_id"] = selected_document_id

    table_rows = [
        {
            "Seleccionar": row["document_id"] == selected_document_id,
            "document_id": row["document_id"],
            "Torre": row.get("tower") or "",
            "Equipo": _equipment_label(row),
            "Fecha": row.get("document_date") or "",
            "Hora": row.get("document_time") or "",
            "Tipo de documento": row.get("document_type") or "",
            "Número de ticket": row.get("ticket_number") or "No Encontrado",
            "Causa": row.get("cause_text") or "",
            "Solución": row.get("solution_text") or "",
            "Nombre del documento": row.get("file_name_original") or "",
        }
        for row in rows
    ]

    table_df = pd.DataFrame(table_rows)
    edited_df = st.data_editor(
        table_df,
        hide_index=True,
        use_container_width=True,
        key="finding-report-editor",
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
        st.session_state["selected_finding_report_document_id"] = selected_document_id

    total_documents = len(rows)
    total_reports = sum(1 for row in rows if row.get("document_type") == "reporte")
    total_findings = sum(1 for row in rows if row.get("document_type") == "hallazgo")
    total_estimates = sum(1 for row in rows if row.get("document_type") == "estimacion")
    metric_cols = st.columns(4)
    metric_cols[0].metric("Número de documentos", str(total_documents))
    metric_cols[1].metric("Cuántos son reportes", str(total_reports))
    metric_cols[2].metric("Cuántos son hallazgos", str(total_findings))
    metric_cols[3].metric("Cuántos son estimaciones", str(total_estimates))

    export_rows = [
        {key: value for key, value in row.items() if key not in {"Seleccionar", "document_id"}}
        for row in table_rows
    ]
    criteria_filters = dict(st.session_state.get("finding_report_filters", {}))
    if criteria_filters.get("equipment") == EQUIPMENT_OTHER_FILTER_VALUE:
        criteria_filters["equipment"] = format_equipment_filter_option(EQUIPMENT_OTHER_FILTER_VALUE)
    criteria_lines = export_service.format_filter_criteria(
        criteria_filters,
        {
            "date_from": "Fecha desde",
            "date_to": "Fecha hasta",
            "tower": "Torre",
            "equipment": "Equipo",
            "document_type": "Tipo de documento",
        },
    )
    excel_bytes, pdf_bytes = export_service.export_item_tracking_report(
        export_rows,
        title="Reporte de hallazgos",
        criteria_lines=criteria_lines,
    )
    export_cols = st.columns(2)
    export_cols[0].download_button(
        "Exportar tabla a Excel",
        data=excel_bytes,
        file_name=export_service.export_filename("reporte_hallazgos", "xlsx"),
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    export_cols[1].download_button(
        "Exportar tabla a PDF",
        data=pdf_bytes,
        file_name=export_service.export_filename("reporte_hallazgos", "pdf"),
        mime="application/pdf",
    )

    selected_row = next((row for row in rows if row["document_id"] == selected_document_id), None)
    if not selected_row:
        st.info("Selecciona un documento para ver su detalle.")
        return

    st.subheader("Detalles relevantes")
    detail_cols = st.columns(3)
    detail_cols[0].metric(
        "Fecha",
        " ".join(part for part in [selected_row.get("document_date") or "", selected_row.get("document_time") or ""] if part),
    )
    detail_cols[1].metric("Ticket", selected_row.get("ticket_number") or "No Encontrado")
    detail_cols[2].metric("Equipo", _equipment_label(selected_row) or "Sin equipo")

    if st.button("Previsualizar documento seleccionado", key=f"finding-report-preview-{selected_document_id}"):
        storage_path = selected_row.get("storage_path")
        if storage_path:
            render_pdf_preview(storage_path, key=f"finding-report-pdf-{selected_document_id}")
        else:
            st.error("El documento seleccionado no tiene ruta de archivo asociada.")


def _equipment_label(row: dict) -> str:
    is_uncataloged = not is_catalog_equipment_code(row.get("equipment_code"))
    pieces = [
        "Sin catálogo" if is_uncataloged else "",
        row.get("equipment_code") or "",
        row.get("position_name") or "",
        row.get("equipment_text_original") or "",
    ]
    return " | ".join(piece for piece in pieces if piece)
