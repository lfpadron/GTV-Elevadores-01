"""Operational estimate-item view focused on support and catalog mapping."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from gtv.models import AuthenticatedUser
from gtv.repositories import cases as case_repo
from gtv.repositories import documents as document_repo
from gtv.repositories import listings as listings_repo
from gtv.repositories import user_tickets as user_ticket_repo
from gtv.services import cases as case_service
from gtv.services import exports as export_service
from gtv.services import linking as linking_service
from gtv.services import updates
from gtv.views.common import (
    equipment_filter_selectbox,
    mark_user_activity,
    render_pdf_preview,
    render_related_documents,
    request_navigation,
    tower_filter_selectbox,
)

LINK_FILTER_OPTIONS = ["todos", "vinculado", "por_vincular"]
SUPPORT_FILTER_OPTIONS = ["todos", "con_soporte", "sin_soporte"]
CATALOG_FILTER_OPTIONS = ["todos", "en_catalogo", "sin_catalogo"]
DELIVERY_FILTER_OPTIONS = [
    ("", "Todos"),
    ("proximos_3_dias", "Próximos a entregar (3 días)"),
    ("proximos_5_dias", "Próximos a entregar (5 días)"),
    ("atrasados", "Ya atrasados"),
    ("entregados", "Ya entregados"),
    ("con_falta_pago", "Con falta de pago"),
    ("ya_pagados", "Ya pagados"),
    ("con_falta_factura", "Con falta de factura"),
    ("ya_facturados", "Ya facturados"),
]


def render(connection, user: AuthenticatedUser) -> None:
    st.header("Estimaciones")
    st.caption("Revisa partidas de estimación, resuelve soporte documental y corrige mapeos de elevador por partida.")

    if "estimate_item_filters" not in st.session_state:
        st.session_state["estimate_item_filters"] = {}

    with st.form("estimate-item-filters"):
        date_range = st.date_input("Fechas", value=(), key="estimate-item-dates")
        top_cols = st.columns(4)
        with top_cols[0]:
            tower = tower_filter_selectbox("Torre", key="estimate-item-tower")
        with top_cols[1]:
            equipment = equipment_filter_selectbox("Equipo", key="estimate-item-equipment", tower=tower, include_other=True)
        free_text = top_cols[2].text_input("Búsqueda texto libre", key="estimate-item-free-text")
        link_status = top_cols[3].selectbox("Vinculación de caso", options=LINK_FILTER_OPTIONS, key="estimate-item-link-status")
        bottom_cols = st.columns(4)
        support_status = bottom_cols[0].selectbox("Reporte / hallazgo", options=SUPPORT_FILTER_OPTIONS, key="estimate-item-support-status")
        catalog_status = bottom_cols[1].selectbox("Elevador en catálogo", options=CATALOG_FILTER_OPTIONS, key="estimate-item-catalog-status")
        delivery_filter = bottom_cols[2].selectbox(
            "Entrega / pago / factura",
            options=[value for value, _ in DELIVERY_FILTER_OPTIONS],
            key="estimate-item-delivery-filter",
            format_func=lambda value: dict(DELIVERY_FILTER_OPTIONS).get(value, value),
        )
        submitted = bottom_cols[3].form_submit_button("Aplicar filtros")

    if submitted:
        st.session_state["estimate_item_filters"] = {
            "date_from": date_range[0].isoformat() if len(date_range) > 0 else None,
            "date_to": date_range[1].isoformat() if len(date_range) > 1 else (date_range[0].isoformat() if len(date_range) > 0 else None),
            "tower": tower or None,
            "equipment": equipment or None,
            "piece_text": free_text or None,
            "link_status": None if link_status == "todos" else link_status,
            "support_status": None if support_status == "todos" else support_status,
            "catalog_status": None if catalog_status == "todos" else catalog_status,
            "delivery_filter": delivery_filter or None,
        }
        mark_user_activity(connection)
        connection.commit()

    rows = listings_repo.list_estimate_item_rows(connection, st.session_state.get("estimate_item_filters", {}))
    if not rows:
        st.info("No se encontraron partidas de estimación con esos filtros.")
        return

    selected_item_id = st.session_state.get("selected_estimate_item_id")
    visible_ids = [row["estimate_item_id"] for row in rows]
    if selected_item_id not in visible_ids:
        selected_item_id = visible_ids[0]
        st.session_state["selected_estimate_item_id"] = selected_item_id

    table_rows = [
        {
            "Seleccionar": row["estimate_item_id"] == selected_item_id,
            "estimate_item_id": row["estimate_item_id"],
            "document_id": row["document_id"],
            "Estimación": row.get("estimate_reference") or "",
            "Caso": row.get("case_folio") or "Sin caso",
            "Reporte / hallazgo / ticket usuario": row.get("support_reference_display") or "No vinculado",
            "Torre y equipo": _equipment_label(row),
            "Partida": f"{row.get('concept_text') or ''} | Cantidad: {row.get('quantity') or 0}",
            "Entrega estimada": row.get("estimated_delivery_date") or "",
            "Atraso entrega": row.get("delivery_delay_flag") or "",
            "Documento de cotización": row.get("file_name_original") or "",
        }
        for row in rows
    ]

    edited_df = st.data_editor(
        pd.DataFrame(table_rows),
        hide_index=True,
        use_container_width=True,
        key="estimate-item-editor",
        disabled=[column for column in table_rows[0].keys() if column != "Seleccionar"],
        column_config={
            "Seleccionar": st.column_config.CheckboxColumn("Seleccionar"),
            "estimate_item_id": None,
            "document_id": None,
        },
    )

    selected_rows = edited_df[edited_df["Seleccionar"] == True]
    if len(selected_rows) > 1:
        st.warning("Selecciona solo una partida a la vez. Se tomará la primera marcada.")
    if not selected_rows.empty:
        selected_item_id = int(selected_rows.iloc[0]["estimate_item_id"])
        st.session_state["selected_estimate_item_id"] = selected_item_id

    export_rows = [
        {
            "Estimación": row.get("estimate_reference") or "",
            "Caso": row.get("case_folio") or "Sin caso",
            "Reporte / hallazgo / ticket usuario": row.get("support_reference_display") or "No vinculado",
            "Torre": row.get("tower") or "",
            "Equipo": row.get("effective_equipment_text") or row.get("equipment_text_original") or "",
            "Código": row.get("effective_equipment_code") or row.get("equipment_code") or "",
            "Partida": row.get("concept_text") or "",
            "Cantidad": row.get("quantity") or 0,
            "Entrega estimada": row.get("estimated_delivery_date") or "",
            "Atraso entrega": row.get("delivery_delay_flag") or "",
            "Documento de cotización": row.get("file_name_original") or "",
        }
        for row in rows
    ]
    criteria_lines = export_service.format_filter_criteria(
        st.session_state.get("estimate_item_filters", {}),
        {
            "date_from": "Fecha desde",
            "date_to": "Fecha hasta",
            "tower": "Torre",
            "equipment": "Equipo",
            "piece_text": "Texto libre",
            "link_status": "Vinculación de caso",
            "support_status": "Reporte / hallazgo",
            "catalog_status": "Elevador en catálogo",
            "delivery_filter": "Entrega / pago / factura",
        },
    )
    excel_bytes, pdf_bytes = export_service.export_item_tracking_report(
        export_rows,
        title="Estimaciones y conceptos",
        criteria_lines=criteria_lines,
    )
    export_cols = st.columns(2)
    export_cols[0].download_button(
        "Exportar Excel",
        data=excel_bytes,
        file_name=export_service.export_filename("estimaciones_conceptos", "xlsx"),
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    export_cols[1].download_button(
        "Exportar PDF",
        data=pdf_bytes,
        file_name=export_service.export_filename("estimaciones_conceptos", "pdf"),
        mime="application/pdf",
    )

    selected_row = next((row for row in rows if row["estimate_item_id"] == selected_item_id), None)
    if not selected_row:
        st.info("Selecciona una partida para revisar su mapeo.")
        return

    st.subheader("Partida seleccionada")
    top_cols = st.columns(5)
    top_cols[0].metric("Estimación", selected_row.get("estimate_reference") or "")
    top_cols[1].metric("Caso", selected_row.get("case_folio") or "Sin caso")
    top_cols[2].metric("Estado operativo", selected_row.get("operational_bucket") or "pendiente")
    top_cols[3].metric("Entrega estimada", selected_row.get("estimated_delivery_date") or "Sin fecha")
    top_cols[4].metric("Atraso entrega", selected_row.get("delivery_delay_flag") or "NO")
    st.write(f"Partida: {selected_row.get('concept_text') or ''}")
    st.write(f"Equipo detectado: {_equipment_label(selected_row)}")
    st.write(f"Soporte actual: {selected_row.get('support_reference_display') or 'No vinculado'}")

    flag_cols = st.columns(2)
    flag_cols[0].caption(
        "Bandera soporte: "
        + ("estimación sin reporte ni hallazgo correspondiente" if selected_row.get("missing_supporting_reference") else "OK")
    )
    flag_cols[1].caption(
        "Bandera elevador: "
        + ("pieza sin elevador en catálogo" if selected_row.get("missing_catalog_equipment") else "OK")
    )

    st.markdown("**Mapeo manual del elevador de la partida**")
    target_equipment_code = equipment_filter_selectbox(
        "Equipo en catálogo",
        key=f"estimate-item-equipment-map-{selected_item_id}",
        tower=selected_row.get("tower"),
        include_all=False,
    )
    if st.button("Guardar elevador de la partida", key=f"estimate-item-save-equipment-{selected_item_id}", disabled=not target_equipment_code):
        updates.map_estimate_item_to_catalog(
            connection,
            item_id=selected_item_id,
            equipment_code=target_equipment_code,
            alias_text=selected_row.get("effective_equipment_text"),
            user=user,
        )
        mark_user_activity(connection)
        connection.commit()
        st.success("Elevador de la partida actualizado.")
        st.rerun()

    st.markdown("**Mapeo manual de reporte / hallazgo / ticket usuario**")
    report_options = _document_options(connection, "reporte", selected_row)
    finding_options = _document_options(connection, "hallazgo", selected_row)
    user_ticket_options = _user_ticket_options(connection, selected_row)
    support_cols = st.columns(4)
    selected_report = support_cols[0].selectbox("Reporte", options=list(report_options.keys()), key=f"estimate-item-report-{selected_item_id}")
    selected_finding = support_cols[1].selectbox("Hallazgo", options=list(finding_options.keys()), key=f"estimate-item-finding-{selected_item_id}")
    selected_user_ticket = support_cols[2].selectbox("Ticket usuario", options=list(user_ticket_options.keys()), key=f"estimate-item-user-ticket-{selected_item_id}")
    propagate = support_cols[3].checkbox("Aplicar a toda la estimación", key=f"estimate-item-propagate-{selected_item_id}")

    action_cols = st.columns(3)
    if action_cols[0].button("Guardar soporte de la partida", key=f"estimate-item-save-links-{selected_item_id}"):
        updates.update_estimate_item_links(
            connection,
            item_id=selected_item_id,
            report_document_id=report_options[selected_report],
            finding_document_id=finding_options[selected_finding],
            user_ticket_id=user_ticket_options[selected_user_ticket],
            propagate_to_document=propagate,
            user=user,
        )
        mark_user_activity(connection)
        connection.commit()
        st.success("Soporte documental de la partida actualizado.")
        st.rerun()

    if action_cols[1].button("Recalcular fechas estimadas", key=f"estimate-item-recalc-{selected_item_id}"):
        updates.recalculate_estimate_delivery_dates(
            connection,
            estimate_document_id=selected_row["document_id"],
            user=user,
        )
        mark_user_activity(connection)
        connection.commit()
        st.success("Fechas estimadas recalculadas.")
        st.rerun()

    case_options = _case_options(connection, selected_row)
    selected_case_label = action_cols[2].selectbox(
        "Caso",
        options=list(case_options.keys()) if case_options else ["Sin casos disponibles"],
        key=f"estimate-item-case-option-{selected_item_id}",
    )

    case_action_cols = st.columns(3)
    if case_action_cols[0].button("Vincular estimación al caso", key=f"estimate-item-link-case-{selected_item_id}", disabled=not case_options):
        case_id = case_options[selected_case_label]
        linking_service.link_document_to_existing_case(
            connection,
            document_id=selected_row["document_id"],
            case_id=case_id,
            user_id=user.id,
        )
        st.session_state["selected_case_id"] = case_id
        mark_user_activity(connection)
        connection.commit()
        st.success("Estimación vinculada al caso.")
        st.rerun()

    if case_action_cols[1].button("Crear caso nuevo", key=f"estimate-item-new-case-{selected_item_id}"):
        new_case_id = linking_service.create_new_case_and_link(
            connection,
            document_id=selected_row["document_id"],
            user_id=user.id,
        )
        st.session_state["selected_case_id"] = new_case_id
        mark_user_activity(connection)
        connection.commit()
        st.success("Se creó un caso nuevo con esta estimación.")
        st.rerun()

    if case_action_cols[2].button("Abrir detalle del caso", key=f"estimate-item-open-case-{selected_item_id}", disabled=not selected_row.get("case_id")):
        request_navigation("Detalle de caso", selected_case_id=selected_row["case_id"])
        st.rerun()

    if st.checkbox("Mostrar visualización del documento de estimación", key=f"preview-estimate-{selected_item_id}"):
        render_pdf_preview(selected_row["storage_path"], key=f"estimate-pdf-{selected_row['document_id']}")

    bundle = _bundle_for_document(connection, selected_row["document_id"], selected_row.get("case_id"))
    render_related_documents(bundle, key_prefix=f"estimate-item-{selected_item_id}")


def _case_options(connection, row: dict) -> dict[str, int]:
    ordered_cases: list[dict] = []
    seen_case_ids: set[int] = set()
    equipment_key = row.get("effective_equipment_code") or row.get("equipment_key")

    if equipment_key and row.get("document_date"):
        for candidate in case_repo.find_candidate_cases(
            connection,
            equipment_key=equipment_key,
            document_date=row["document_date"],
        ):
            if candidate["id"] not in seen_case_ids:
                ordered_cases.append(candidate)
                seen_case_ids.add(candidate["id"])

    for case in case_repo.list_cases(connection):
        if case["id"] not in seen_case_ids:
            ordered_cases.append(case)
            seen_case_ids.add(case["id"])

    return {
        f"{case['case_folio']} | {case.get('tower') or ''} | {case.get('equipment_text_original') or case.get('equipment_key') or ''}": case["id"]
        for case in ordered_cases
    }


def _document_options(connection, document_type: str, row: dict) -> dict[str, int | None]:
    options: dict[str, int | None] = {"Sin seleccionar": None}
    equipment_code = row.get("effective_equipment_code") or row.get("equipment_code")
    for document in document_repo.list_documents_by_type(
        connection,
        document_type,
        tower=row.get("tower"),
        equipment_code=equipment_code,
    ):
        details = document_repo.get_document_with_details(connection, document["id"]) or document
        if document_type == "reporte":
            reference = details.get("details", {}).get("ticket_number") or document.get("primary_identifier") or "sin referencia"
            label = f"Reporte {reference} | {document.get('document_date') or ''} | {document.get('file_name_original') or ''}"
        else:
            reference = (
                details.get("details", {}).get("base_ticket_number")
                or details.get("details", {}).get("finding_folio")
                or document.get("primary_identifier")
                or "sin referencia"
            )
            label = f"Hallazgo {reference} | {document.get('document_date') or ''} | {document.get('file_name_original') or ''}"
        options[label] = document["id"]
    return options


def _user_ticket_options(connection, row: dict) -> dict[str, int | None]:
    options: dict[str, int | None] = {"Sin seleccionar": None}
    filters = {
        "tower": row.get("tower"),
        "equipment_code": row.get("effective_equipment_code") or row.get("equipment_code"),
    }
    for ticket in user_ticket_repo.list_user_tickets(connection, filters):
        label = f"{ticket.get('ticket_folio') or ''} | {ticket.get('document_date') or ''} | {ticket.get('description') or ''}"
        options[label] = ticket["id"]
    return options


def _bundle_for_document(connection, document_id: int, case_id: int | None) -> dict:
    if case_id:
        bundle = case_service.build_case_bundle(connection, case_id)
        if bundle:
            return bundle

    document = document_repo.get_document(connection, document_id)
    if not document:
        return {"reports": [], "finding_documents": [], "estimate_documents": [], "user_tickets": []}
    return {"reports": [], "finding_documents": [], "estimate_documents": [document], "user_tickets": []}


def _equipment_label(row: dict) -> str:
    pieces = [
        row.get("effective_equipment_code") or row.get("equipment_code") or "",
        row.get("tower") or "",
        row.get("position_name") or "",
        row.get("effective_equipment_text") or row.get("equipment_text_original") or "",
    ]
    return " | ".join(piece for piece in pieces if piece)
