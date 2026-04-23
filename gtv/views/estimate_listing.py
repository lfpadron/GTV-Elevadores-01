"""Operational estimate-item view focused on pending linking."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from gtv.models import AuthenticatedUser
from gtv.repositories import cases as case_repo
from gtv.repositories import documents as document_repo
from gtv.repositories import listings as listings_repo
from gtv.services import cases as case_service
from gtv.services import linking as linking_service
from gtv.views.common import (
    equipment_filter_selectbox,
    mark_user_activity,
    render_pdf_preview,
    render_related_documents,
    request_navigation,
    tower_filter_selectbox,
)


def render(connection, user: AuthenticatedUser) -> None:
    st.header("Estimaciones")
    st.caption("Revisa partidas no vinculadas y vincula la estimación completa al caso correspondiente.")

    if "estimate_item_filters" not in st.session_state:
        st.session_state["estimate_item_filters"] = {}

    with st.form("estimate-item-filters"):
        date_range = st.date_input("Fechas", value=(), key="estimate-item-dates")
        cols = st.columns(4)
        with cols[0]:
            tower = tower_filter_selectbox("Torre", key="estimate-item-tower")
        with cols[1]:
            equipment = equipment_filter_selectbox("Equipo", key="estimate-item-equipment")
        link_status = cols[2].selectbox(
            "Filtro de vinculación",
            options=["todos", "vinculado", "por_vincular"],
            key="estimate-item-link-status",
        )
        free_text = cols[3].text_input("Búsqueda texto libre", key="estimate-item-free-text")
        submitted = st.form_submit_button("Aplicar filtros")

    if submitted:
        st.session_state["estimate_item_filters"] = {
            "date_from": date_range[0].isoformat() if len(date_range) > 0 else None,
            "date_to": date_range[1].isoformat() if len(date_range) > 1 else (date_range[0].isoformat() if len(date_range) > 0 else None),
            "tower": tower or None,
            "equipment": equipment or None,
            "piece_text": free_text or None,
            "link_status": None if link_status == "todos" else link_status,
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
            "Ticket/hallazgo": row.get("linked_references") or "No vinculado",
            "Torre y equipo": _equipment_label(row),
            "Partida": f"{row.get('concept_text') or ''} | Cantidad: {row.get('quantity') or 0}",
            "Nombre documento de cotización": row.get("file_name_original") or "",
        }
        for row in rows
    ]

    table_df = pd.DataFrame(table_rows)
    edited_df = st.data_editor(
        table_df,
        hide_index=True,
        use_container_width=True,
        key="estimate-item-editor",
        disabled=[column for column in table_df.columns if column != "Seleccionar"],
        column_config={
            "Seleccionar": st.column_config.CheckboxColumn("Seleccionar"),
            "estimate_item_id": None,
            "document_id": None,
        },
    )

    selected_rows = edited_df[edited_df["Seleccionar"] == True]
    if len(selected_rows) > 1:
        st.warning("Selecciona solo una partida a la vez. Se tomara la primera marcada.")
    if not selected_rows.empty:
        selected_item_id = int(selected_rows.iloc[0]["estimate_item_id"])
        st.session_state["selected_estimate_item_id"] = selected_item_id

    selected_row = next((row for row in rows if row["estimate_item_id"] == selected_item_id), None)
    if not selected_row:
        st.info("Selecciona una partida para revisar su vinculación.")
        return

    st.subheader("Registro seleccionado")
    top_cols = st.columns(4)
    top_cols[0].metric("Estimación", selected_row.get("estimate_reference") or "")
    top_cols[1].metric("Caso actual", selected_row.get("case_folio") or "Sin caso")
    top_cols[2].metric("Estado de vinculación", selected_row.get("link_status") or "")
    top_cols[3].metric("Cantidad", str(selected_row.get("quantity") or 0))
    st.write(f"Partida: {selected_row.get('concept_text') or ''}")
    st.write(f"Ticket/hallazgo relacionado: {selected_row.get('linked_references') or 'No vinculado'}")
    if selected_row.get("summary_text"):
        st.write(selected_row["summary_text"])

    case_options = _build_case_options(connection, selected_row)
    selected_case_option = None
    if case_options:
        selected_case_option = st.selectbox(
            "Vincular documento de estimación al caso",
            options=list(case_options.keys()),
            key=f"estimate-case-option-{selected_row['estimate_item_id']}",
        )
    else:
        st.info("Aún no existen casos disponibles. Puedes crear uno nuevo con esta estimación.")

    action_cols = st.columns(3)
    if action_cols[0].button(
        "Vincular al caso seleccionado",
        key=f"link-estimate-{selected_row['estimate_item_id']}",
        disabled=selected_case_option is None,
    ):
        case_id = case_options[selected_case_option]
        linking_service.link_document_to_existing_case(
            connection,
            document_id=selected_row["document_id"],
            case_id=case_id,
            user_id=user.id,
        )
        st.session_state["selected_case_id"] = case_id
        mark_user_activity(connection)
        connection.commit()
        st.success("Estimación vinculada al caso seleccionado.")
        st.rerun()

    if action_cols[1].button("Crear caso nuevo con esta estimación", key=f"new-case-estimate-{selected_row['estimate_item_id']}"):
        new_case_id = linking_service.create_new_case_and_link(
            connection,
            document_id=selected_row["document_id"],
            user_id=user.id,
        )
        st.session_state["selected_case_id"] = new_case_id
        mark_user_activity(connection)
        connection.commit()
        st.success("Se creó un nuevo caso usando esta estimación.")
        st.rerun()

    if action_cols[2].button("Abrir detalle del caso", key=f"open-estimate-case-{selected_row['estimate_item_id']}", disabled=not selected_row.get("case_id")):
        request_navigation("Detalle de caso", selected_case_id=selected_row["case_id"])
        st.rerun()

    if st.checkbox("Mostrar visualización del documento de estimación", key=f"preview-estimate-{selected_row['estimate_item_id']}"):
        render_pdf_preview(selected_row["storage_path"], key=f"estimate-pdf-{selected_row['document_id']}")

    bundle = _bundle_for_document(connection, selected_row["document_id"], selected_row.get("case_id"))
    render_related_documents(bundle, key_prefix=f"estimate-item-{selected_row['estimate_item_id']}")


def _build_case_options(connection, row: dict) -> dict[str, int]:
    ordered_cases: list[dict] = []
    seen_case_ids: set[int] = set()

    if row.get("equipment_key") and row.get("document_date"):
        for candidate in case_repo.find_candidate_cases(
            connection,
            equipment_key=row["equipment_key"],
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


def _bundle_for_document(connection, document_id: int, case_id: int | None) -> dict:
    if case_id:
        bundle = case_service.build_case_bundle(connection, case_id)
        if bundle:
            return bundle

    document = document_repo.get_document(connection, document_id)
    if not document:
        return {"reports": [], "finding_documents": [], "estimate_documents": []}
    return {"reports": [], "finding_documents": [], "estimate_documents": [document]}


def _equipment_label(row: dict) -> str:
    pieces = [
        row.get("equipment_code") or "",
        row.get("tower") or "",
        row.get("position_name") or "",
        row.get("equipment_text_original") or "",
    ]
    return " | ".join(piece for piece in pieces if piece)
