"""Operational item tracking page with exports."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from gtv.constants import ITEM_PAYMENT_STATES, ITEM_RECEIPT_STATES
from gtv.models import AuthenticatedUser
from gtv.repositories import documents as document_repo
from gtv.repositories import listings as listings_repo
from gtv.services import exports as export_service
from gtv.services import updates
from gtv.views.common import mark_user_activity, render_pdf_preview
from gtv.views.common import equipment_filter_selectbox, tower_filter_selectbox

ITEM_STATE_FILTERS = [
    "",
    "pendiente",
    "recibida",
    "pagada",
    "facturada",
    "sin_factura",
    "no_recibida",
    "parcialmente_recibida",
    "recibida_total",
    "no_pagada",
    "pagada_parcial",
    "pagada_total",
]


def render(connection, user: AuthenticatedUser) -> None:
    st.header("Partidas")
    st.caption("Revisa partidas pendientes, recibidas, pagadas o facturadas y exporta el control operativo.")

    if "partidas_filters" not in st.session_state:
        st.session_state["partidas_filters"] = {}

    with st.form("partidas-filters"):
        date_range = st.date_input("Fechas", value=(), key="partidas-dates")
        cols = st.columns(5)
        case_search = cols[0].text_input("Caso", key="partidas-case")
        with cols[1]:
            tower = tower_filter_selectbox("Torre", key="partidas-tower")
        with cols[2]:
            equipment = equipment_filter_selectbox("Equipo", key="partidas-equipment")
        ticket = cols[3].text_input("Ticket", key="partidas-ticket")
        item_state = cols[4].selectbox("Estado", options=ITEM_STATE_FILTERS, key="partidas-state")
        submitted = st.form_submit_button("Aplicar filtros")

    if submitted:
        st.session_state["partidas_filters"] = {
            "date_from": date_range[0].isoformat() if len(date_range) > 0 else None,
            "date_to": date_range[1].isoformat() if len(date_range) > 1 else (date_range[0].isoformat() if len(date_range) > 0 else None),
            "case_search": case_search or None,
            "tower": tower or None,
            "equipment": equipment or None,
            "ticket": ticket or None,
            "item_state": item_state or None,
        }
        mark_user_activity(connection)
        connection.commit()

    rows = listings_repo.list_estimate_item_rows(connection, st.session_state.get("partidas_filters", {}))
    if not rows:
        st.info("No se encontraron partidas con esos filtros.")
        return

    display_rows = [
        {
            "Seleccionar": False,
            "estimate_item_id": row["estimate_item_id"],
            "Caso": row.get("case_folio") or "Sin caso",
            "Reporte/hallazgo": row.get("linked_references") or "No vinculado",
            "Documento": f"{row.get('estimate_reference') or ''} | {row.get('file_name_original') or ''}",
            "Torre y equipo": _equipment_label(row),
            "Descripción pieza": row.get("concept_text") or "",
            "Cant. estimación": row.get("quantity") or 0,
            "Cant. recibida": row.get("received_units") or 0,
            "Monto estimación": row.get("subtotal") or 0,
            "Monto pagado": row.get("paid_amount") or 0,
            "Factura": row.get("invoice_display") or ("SI" if row.get("invoice_flag") == "SI" else ""),
        }
        for row in rows
    ]

    selected_item_id = st.session_state.get("selected_partida_item_id")
    visible_ids = [row["estimate_item_id"] for row in rows]
    if selected_item_id not in visible_ids:
        selected_item_id = visible_ids[0]
        st.session_state["selected_partida_item_id"] = selected_item_id

    for row in display_rows:
        row["Seleccionar"] = row["estimate_item_id"] == selected_item_id

    table_df = pd.DataFrame(display_rows)
    edited_df = st.data_editor(
        table_df,
        hide_index=True,
        use_container_width=True,
        key="partidas-editor",
        disabled=[column for column in table_df.columns if column != "Seleccionar"],
        column_config={
            "Seleccionar": st.column_config.CheckboxColumn("Seleccionar"),
            "estimate_item_id": None,
        },
    )

    selected_rows = edited_df[edited_df["Seleccionar"] == True]
    if len(selected_rows) > 1:
        st.warning("Selecciona solo una partida a la vez. Se tomará la primera marcada.")
    if not selected_rows.empty:
        selected_item_id = int(selected_rows.iloc[0]["estimate_item_id"])
        st.session_state["selected_partida_item_id"] = selected_item_id

    export_rows = _build_export_rows(rows)
    criteria_lines = export_service.format_filter_criteria(
        st.session_state.get("partidas_filters", {}),
        {
            "date_from": "Fecha desde",
            "date_to": "Fecha hasta",
            "case_search": "Caso",
            "tower": "Torre",
            "equipment": "Equipo",
            "ticket": "Ticket",
            "item_state": "Estado",
        },
    )
    excel_bytes, pdf_bytes = export_service.export_item_tracking_report(
        export_rows,
        title="Reporte de partidas",
        criteria_lines=criteria_lines,
    )
    export_cols = st.columns(2)
    export_cols[0].download_button(
        "Exportar reporte de partidas a Excel",
        data=excel_bytes,
        file_name=export_service.export_filename("reporte_partidas", "xlsx"),
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    export_cols[1].download_button(
        "Exportar reporte de partidas a PDF",
        data=pdf_bytes,
        file_name=export_service.export_filename("reporte_partidas", "pdf"),
        mime="application/pdf",
    )

    selected_row = next((row for row in rows if row["estimate_item_id"] == selected_item_id), None)
    if not selected_row:
        st.info("Selecciona una partida para ver su detalle.")
        return

    st.subheader("Detalle de la partida seleccionada")
    metric_cols = st.columns(5)
    metric_cols[0].metric("Caso", selected_row.get("case_folio") or "Sin caso")
    metric_cols[1].metric("Cotización", selected_row.get("estimate_reference") or "")
    metric_cols[2].metric("Estado", selected_row.get("operational_bucket") or "")
    metric_cols[3].metric("Unidades recibidas", str(selected_row.get("received_units") or 0))
    metric_cols[4].metric("Importe pagado", f"${float(selected_row.get('paid_amount') or 0):,.2f}")

    st.write(f"Reporte/hallazgo: {selected_row.get('linked_references') or 'No vinculado'}")
    st.write(f"Documento: {selected_row.get('file_name_original') or ''}")
    st.write(f"Torre y equipo: {_equipment_label(selected_row)}")
    st.write(f"Descripción: {selected_row.get('concept_text') or ''}")

    with st.form(f"partida-edit-{selected_row['estimate_item_id']}"):
        receipt_status = st.selectbox(
            "Estado de recepción",
            options=ITEM_RECEIPT_STATES,
            index=ITEM_RECEIPT_STATES.index(selected_row.get("receipt_status") or ITEM_RECEIPT_STATES[0]),
        )
        payment_status = st.selectbox(
            "Estado de pago",
            options=ITEM_PAYMENT_STATES,
            index=ITEM_PAYMENT_STATES.index(selected_row.get("payment_status") or ITEM_PAYMENT_STATES[0]),
        )
        reception_date = st.text_input("Fecha de recepción", value=selected_row.get("reception_date") or "")
        payment_date = st.text_input("Fecha de pago", value=selected_row.get("payment_date") or "")
        payment_method = st.text_input("Forma de pago", value=selected_row.get("payment_method") or "")
        invoice_date = st.text_input("Fecha de factura", value=selected_row.get("invoice_date") or "")
        invoice_number = st.text_input("Número de factura", value=selected_row.get("invoice_number") or "")
        propagate_mode = st.selectbox(
            "Propagar a unidades",
            options=["sin_propagacion", "sobrescribe_todo", "solo_vacios"],
        )
        save = st.form_submit_button("Guardar cambios operativos")

    if save:
        updates.update_item_operational_fields(
            connection,
            item_id=selected_row["estimate_item_id"],
            payload={
                "receipt_status": receipt_status,
                "payment_status": payment_status,
                "reception_date": reception_date or None,
                "payment_date": payment_date or None,
                "payment_method": payment_method or None,
                "invoice_date": invoice_date or None,
                "invoice_number": invoice_number or None,
            },
            propagate_mode=None if propagate_mode == "sin_propagacion" else propagate_mode,
            user=user,
        )
        mark_user_activity(connection)
        connection.commit()
        st.success("Partida actualizada.")
        st.rerun()

    if st.checkbox("Mostrar documento original de estimación", key=f"partida-preview-{selected_row['estimate_item_id']}"):
        render_pdf_preview(selected_row["storage_path"], key=f"partida-pdf-{selected_row['document_id']}")

    document = document_repo.get_document(selected_row["document_id"])
    if document:
        st.caption(f"Resumen del documento original: {document.get('summary_user_edited') or document.get('summary_ai_original') or document.get('short_description') or ''}")


def _build_export_rows(rows: list[dict]) -> list[dict]:
    export_rows: list[dict] = []
    for row in rows:
        export_rows.append(
            {
                "Número de ticket": row.get("linked_references") or "No vinculado",
                "Número de caso": row.get("case_folio") or "Sin caso",
                "Si es reporte o hallazgo": row.get("related_origin_types") or "",
                "Número de cot": row.get("estimate_reference") or "",
                "Documento origen (estimación)": row.get("file_name_original") or "",
                "Descripción pieza": row.get("concept_text") or "",
                "Fecha solicitada": row.get("requested_date") or "",
                "Número de unidades solicitadas": row.get("quantity") or 0,
                "Número de unidades recibidas": row.get("received_units") or 0,
                "Importe presupuestado": row.get("subtotal") or 0,
                "Importe pagado": row.get("paid_amount") or 0,
                "Si ya está facturado": row.get("invoice_flag") or "NO",
            }
        )
    return export_rows


def _equipment_label(row: dict) -> str:
    pieces = [
        row.get("equipment_code") or "",
        row.get("tower") or "",
        row.get("position_name") or "",
        row.get("equipment_text_original") or "",
    ]
    return " | ".join(piece for piece in pieces if piece)
