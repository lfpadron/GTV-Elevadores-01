"""Operational report for tickets and findings with export support."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from gtv.constants import ESTIMATE_STATES, FINDING_STATES, REPORT_STATES
from gtv.models import AuthenticatedUser
from gtv.repositories import documents as document_repo
from gtv.repositories import listings as listings_repo
from gtv.services import cases as case_service
from gtv.services import exports as export_service
from gtv.views.common import (
    document_reference_text,
    equipment_filter_selectbox,
    mark_user_activity,
    numbered_dataframe,
    render_pdf_preview,
    render_related_documents,
    tower_filter_selectbox,
)

DOCUMENT_TYPE_OPTIONS = ["", "reporte", "hallazgo", "estimacion"]


def render(connection, user: AuthenticatedUser) -> None:
    st.header("Listado de reportes y hallazgos")
    st.caption("Filtra reportes, hallazgos y estimaciones por fecha, torre, equipo y estado. Exporta el listado a Excel o PDF.")

    if "report_ticket_filters" not in st.session_state:
        st.session_state["report_ticket_filters"] = {}

    state_options = [""] + list(dict.fromkeys([*REPORT_STATES, *FINDING_STATES, *ESTIMATE_STATES]))
    with st.form("report-ticket-filters"):
        date_range = st.date_input("Rango de fechas", value=(), key="report-ticket-dates")
        cols = st.columns(5)
        with cols[0]:
            tower = tower_filter_selectbox("Torre", key="report-ticket-tower")
        with cols[1]:
            equipment = equipment_filter_selectbox("Equipo", key="report-ticket-equipment", tower=tower, include_other=True)
        state = cols[2].selectbox("Estado", options=state_options, key="report-ticket-state")
        ticket = cols[3].text_input("Ticket / hallazgo", key="report-ticket-ticket")
        document_type = cols[4].selectbox(
            "Tipo de documento",
            options=DOCUMENT_TYPE_OPTIONS,
            key="report-ticket-document-type",
            format_func=lambda value: "Todos" if value == "" else _document_type_label(value),
        )
        submitted = st.form_submit_button("Aplicar filtros")

    if submitted:
        st.session_state["report_ticket_filters"] = {
            "date_from": date_range[0].isoformat() if len(date_range) > 0 else None,
            "date_to": date_range[1].isoformat() if len(date_range) > 1 else (date_range[0].isoformat() if len(date_range) > 0 else None),
            "tower": tower or None,
            "equipment": equipment or None,
            "state": state or None,
            "ticket": ticket or None,
            "document_type": document_type or None,
        }
        mark_user_activity(connection)
        connection.commit()

    rows = listings_repo.list_report_ticket_rows(connection, st.session_state.get("report_ticket_filters", {}))
    if not rows:
        st.info("No se encontraron tickets o hallazgos con esos filtros.")
        return

    report_rows = _build_report_rows(rows)
    selected_document_id = st.session_state.get("selected_report_ticket_document_id")
    visible_ids = [row["document_id"] for row in rows]
    if selected_document_id not in visible_ids:
        selected_document_id = visible_ids[0]
        st.session_state["selected_report_ticket_document_id"] = selected_document_id

    table_rows = []
    for row_number, row in enumerate(rows):
        table_rows.append(
            {
                "Seleccionar": row["document_id"] == selected_document_id,
                "document_id": row["document_id"],
                "No.": row_number,
                **report_rows[row_number],
            }
        )

    table_df = pd.DataFrame(table_rows)
    edited_df = st.data_editor(
        table_df,
        hide_index=True,
        use_container_width=True,
        key="report-ticket-editor",
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
        st.session_state["selected_report_ticket_document_id"] = selected_document_id

    total_rows = len(rows)
    unique_ticket_count = _count_distinct_references(rows, "reporte")
    unique_finding_count = _count_distinct_references(rows, "hallazgo")
    unique_total = unique_ticket_count + unique_finding_count
    total_quoted = _total_quoted_amount(rows)
    total_cols = st.columns(5)
    total_cols[0].metric("Número total de tickets y hallazgos", str(total_rows))
    total_cols[1].metric("Número de tickets y hallazgos diferentes", str(unique_total))
    total_cols[2].metric("Número de tickets", str(unique_ticket_count))
    total_cols[3].metric("Número de hallazgos", str(unique_finding_count))
    total_cols[4].metric("Importe cotizado total", f"${total_quoted:,.2f}")

    criteria_lines = export_service.format_filter_criteria(
        st.session_state.get("report_ticket_filters", {}),
        {
            "date_from": "Fecha desde",
            "date_to": "Fecha hasta",
            "tower": "Torre",
            "equipment": "Equipo",
            "state": "Estado",
            "ticket": "Ticket / hallazgo",
            "document_type": "Tipo de documento",
        },
    )
    excel_bytes, pdf_bytes = export_service.export_report_ticket_report(report_rows, criteria_lines=criteria_lines)
    export_cols = st.columns(2)
    export_cols[0].download_button(
        "Exportar a Excel",
        data=excel_bytes,
        file_name=export_service.export_filename("reporte_tickets_hallazgos", "xlsx"),
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    export_cols[1].download_button(
        "Exportar a PDF",
        data=pdf_bytes,
        file_name=export_service.export_filename("reporte_tickets_hallazgos", "pdf"),
        mime="application/pdf",
    )

    selected_row = next((row for row in rows if row["document_id"] == selected_document_id), None)
    if not selected_row:
        st.info("Selecciona un documento para revisar su detalle.")
        return

    st.subheader("Detalle documental")
    detail_cols = st.columns(5)
    detail_cols[0].metric("Caso", selected_row.get("case_folio") or "Sin caso")
    detail_cols[1].metric("Referencia", document_reference_text(selected_row))
    detail_cols[2].metric("Código", selected_row.get("equipment_code") or "Sin código")
    detail_cols[3].metric("Estado", selected_row.get("current_status") or "Sin estado")
    detail_cols[4].metric("Importe cotizado", f"${float(selected_row.get('quoted_amount') or 0):,.2f}")
    st.write(f"Torre y equipo: {_equipment_label(selected_row)}")
    st.write(f"Fecha de apertura: {selected_row.get('opened_at') or ''}")
    st.write(f"Fecha de atendimiento: {selected_row.get('attended_at') or ''}")
    st.write(f"Fecha de cierre: {selected_row.get('closed_at') or ''}")

    if st.checkbox("Mostrar documento original", key=f"report-ticket-preview-{selected_row['document_id']}"):
        render_pdf_preview(selected_row["storage_path"], key=f"report-ticket-pdf-{selected_row['document_id']}")

    bundle = _bundle_for_document(connection, selected_row["document_id"], selected_row.get("case_id"))
    st.markdown("**Documentos relacionados**")
    render_related_documents(bundle, key_prefix=f"report-ticket-{selected_row['document_id']}")

    st.markdown("**Partidas**")
    estimate_items = bundle.get("estimate_items", [])
    if estimate_items:
        item_rows = [
            {
                "Estimación": item.get("normalized_folio") or item.get("original_folio") or "",
                "Concepto": item.get("concept_text") or "",
                "Cantidad": item.get("quantity") or 0,
                "Monto": item.get("subtotal") or 0,
                "Recepción": item.get("receipt_status") or "",
                "Pago": item.get("payment_status") or "",
            }
            for item in estimate_items
        ]
        st.dataframe(numbered_dataframe(item_rows, start=0), use_container_width=True)
    else:
        st.caption("No hay partidas vinculadas para este ticket/hallazgo.")


def _bundle_for_document(connection, document_id: int, case_id: int | None) -> dict:
    if case_id:
        bundle = case_service.build_case_bundle(connection, case_id)
        if bundle:
            return bundle

    document = document_repo.get_document(connection, document_id)
    if not document:
        return {"reports": [], "finding_documents": [], "estimate_documents": []}
    if document["document_type"] == "reporte":
        return {"reports": [document], "finding_documents": [], "estimate_documents": []}
    if document["document_type"] == "hallazgo":
        return {"reports": [], "finding_documents": [document], "estimate_documents": []}
    return {
        "reports": [],
        "finding_documents": [],
        "estimate_documents": [document],
        "estimate_items": document_repo.list_estimate_items(connection, document_id),
    }


def _build_report_rows(rows: list[dict]) -> list[dict]:
    return [
        {
            "Número de ticket": row.get("source_reference") or "",
            "Tipo de documento": _document_type_label(row.get("document_type") or ""),
            "Código de equipo": row.get("equipment_code") or "",
            "Torre y equipo": _equipment_label(row),
            "Fecha de apertura": row.get("opened_at") or "",
            "Fecha de atendimiento": row.get("attended_at") or "",
            "Fecha de cierre": row.get("closed_at") or "",
            "Importe cotizado": row.get("quoted_amount") or 0,
        }
        for row in rows
    ]


def _document_type_label(value: str) -> str:
    labels = {
        "reporte": "Reporte",
        "hallazgo": "Hallazgo",
        "estimacion": "Estimación",
    }
    return labels.get(value, value.title())


def _equipment_label(row: dict) -> str:
    pieces = [
        row.get("equipment_code") or "",
        row.get("tower") or "",
        row.get("position_name") or "",
        row.get("equipment_text_original") or "",
    ]
    return " | ".join(piece for piece in pieces if piece)


def _count_distinct_references(rows: list[dict], document_type: str) -> int:
    references = {
        (row.get("source_reference") or "").strip().upper()
        for row in rows
        if row.get("document_type") == document_type and (row.get("source_reference") or "").strip()
    }
    return len(references)


def _total_quoted_amount(rows: list[dict]) -> float:
    seen_case_ids: set[int] = set()
    total = 0.0
    for row in rows:
        case_id = row.get("case_id")
        if not case_id or case_id in seen_case_ids:
            continue
        seen_case_ids.add(case_id)
        total += float(row.get("quoted_amount") or 0)
    return round(total, 2)
