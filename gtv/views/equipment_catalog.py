"""Equipment catalog maintenance and manual remediation workflows."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from gtv.constants import POSITION_DEFAULTS, USER_TICKET_STATES
from gtv.models import AuthenticatedUser
from gtv.repositories import cases as case_repo
from gtv.repositories import documents as document_repo
from gtv.repositories import equipment_catalog as equipment_repo
from gtv.repositories import user_tickets as user_ticket_repo
from gtv.services import linking as linking_service
from gtv.services import updates
from gtv.views.common import equipment_filter_selectbox, mark_user_activity, render_pdf_preview, tower_filter_selectbox


def render(connection, user: AuthenticatedUser) -> None:
    st.header("Catálogo de elevadores")
    st.caption("Administra el catálogo, corrige elevadores sin catálogo y resuelve documentos huérfanos o duplicados con tickets usuario.")

    catalog_tab, uncataloged_tab, remediation_tab = st.tabs(
        ["Catálogo", "Sin catálogo", "Huérfanos y tickets usuario"]
    )

    with catalog_tab:
        _render_catalog_tab(connection, user)
    with uncataloged_tab:
        _render_uncataloged_tab(connection, user)
    with remediation_tab:
        _render_remediation_tab(connection, user)


def _render_catalog_tab(connection, user: AuthenticatedUser) -> None:
    selected_tower = tower_filter_selectbox("Filtrar catálogo por torre", key="catalog-filter-tower")
    catalog_rows = equipment_repo.list_equipment_catalog(connection, tower=selected_tower or None)
    if catalog_rows:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Código": row["equipment_code"],
                        "Torre": row.get("tower") or "",
                        "Posición": row.get("position_name") or "",
                        "Equipo en catálogo": row.get("display_name") or "",
                    }
                    for row in catalog_rows
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.info("No hay elevadores en el catálogo con ese filtro.")

    entry_options = {row["equipment_code"]: row for row in catalog_rows}
    if entry_options:
        selected_code = st.selectbox(
            "Equipo en catálogo para editar",
            options=list(entry_options.keys()),
            key="catalog-edit-code",
        )
        current = entry_options[selected_code]
        with st.form("catalog-edit-form"):
            tower = st.selectbox("Torre", options=["A", "B", "C", "D", "E", "F"], index=["A", "B", "C", "D", "E", "F"].index(current.get("tower") or "A"))
            position_name = st.selectbox(
                "Posición",
                options=POSITION_DEFAULTS,
                index=POSITION_DEFAULTS.index(current.get("position_name") or POSITION_DEFAULTS[0]),
            )
            display_name = st.text_input("Equipo en catálogo", value=current.get("display_name") or "")
            save_edit = st.form_submit_button("Guardar cambios en catálogo")
        if save_edit:
            updates.upsert_equipment_catalog_entry(
                connection,
                equipment_code=selected_code,
                tower=tower,
                position_name=position_name,
                display_name=display_name.strip(),
                user=user,
            )
            mark_user_activity(connection)
            connection.commit()
            st.success("Equipo en catálogo actualizado.")
            st.rerun()

    st.markdown("**Añadir equipo nuevo**")
    with st.form("catalog-new-form"):
        new_code = st.text_input("Código de equipo", value="", placeholder="10270-MEX-ELE-BLT")
        new_tower = st.selectbox("Torre nueva", options=["A", "B", "C", "D", "E", "F"], key="catalog-new-tower")
        new_position = st.selectbox("Posición nueva", options=POSITION_DEFAULTS, key="catalog-new-position")
        new_name = st.text_input("Equipo en catálogo", value="", placeholder="Torre F Elevador Derecho")
        create_new = st.form_submit_button("Crear equipo nuevo")
    if create_new:
        updates.upsert_equipment_catalog_entry(
            connection,
            equipment_code=new_code.strip(),
            tower=new_tower,
            position_name=new_position,
            display_name=new_name.strip(),
            user=user,
        )
        mark_user_activity(connection)
        connection.commit()
        st.success("Equipo nuevo agregado al catálogo.")
        st.rerun()


def _render_uncataloged_tab(connection, user: AuthenticatedUser) -> None:
    filter_cols = st.columns(2)
    tower = tower_filter_selectbox("Torre", key="uncataloged-tower")
    free_text = filter_cols[1].text_input("Buscar texto libre", key="uncataloged-free-text")

    rows = [
        row
        for row in equipment_repo.list_uncataloged_equipment_usage(connection)
        if (not tower or (row.get("tower") or "").upper() == tower.upper())
        and (not free_text or free_text.lower() in " ".join(
            [
                row.get("document_type") or "",
                row.get("source_name") or "",
                row.get("alias_text") or "",
                row.get("source_reference") or "",
            ]
        ).lower())
    ]
    if not rows:
        st.info("No hay elevadores fuera de catálogo pendientes de corrección.")
        return

    selected_key = st.session_state.get("selected_uncataloged_key")
    visible_keys = [f"{row['entity_type']}:{row['entity_id']}" for row in rows]
    if selected_key not in visible_keys:
        selected_key = visible_keys[0]
        st.session_state["selected_uncataloged_key"] = selected_key

    table_rows = []
    for row in rows:
        row_key = f"{row['entity_type']}:{row['entity_id']}"
        table_rows.append(
            {
                "Seleccionar": row_key == selected_key,
                "row_key": row_key,
                "Origen": row.get("entity_type") or "",
                "Tipo documento": row.get("document_type") or "",
                "Referencia": row.get("source_reference") or "",
                "Fecha": row.get("document_date") or "",
                "Hora": row.get("document_time") or "",
                "Torre": row.get("tower") or "",
                "Equipo fuera de catálogo": row.get("alias_text") or "",
                "Documento": row.get("source_name") or "",
            }
        )

    edited_df = st.data_editor(
        pd.DataFrame(table_rows),
        hide_index=True,
        use_container_width=True,
        key="uncataloged-editor",
        disabled=[column for column in table_rows[0].keys() if column != "Seleccionar"],
        column_config={
            "Seleccionar": st.column_config.CheckboxColumn("Seleccionar"),
            "row_key": None,
        },
    )
    selected_rows = edited_df[edited_df["Seleccionar"] == True]
    if not selected_rows.empty:
        selected_key = str(selected_rows.iloc[0]["row_key"])
        st.session_state["selected_uncataloged_key"] = selected_key

    selected_row = next((row for row in rows if f"{row['entity_type']}:{row['entity_id']}" == selected_key), None)
    if not selected_row:
        return

    st.subheader("Registro fuera de catálogo")
    st.write(f"Documento: {selected_row.get('source_name') or ''}")
    st.write(f"Referencia: {selected_row.get('source_reference') or ''}")
    st.write(f"Equipo detectado: {selected_row.get('alias_text') or ''}")

    target_code = equipment_filter_selectbox(
        "Mapear a equipo en catálogo",
        key=f"uncataloged-map-{selected_key}",
        tower=selected_row.get("tower"),
        include_all=False,
    )
    if st.button("Aplicar mapeo a catálogo", key=f"uncataloged-save-{selected_key}", disabled=not target_code):
        if selected_row["entity_type"] == "documento":
            updates.map_document_to_catalog(
                connection,
                document_id=int(selected_row["entity_id"]),
                equipment_code=target_code,
                alias_text=selected_row.get("alias_text"),
                user=user,
            )
        else:
            updates.map_estimate_item_to_catalog(
                connection,
                item_id=int(selected_row["entity_id"]),
                equipment_code=target_code,
                alias_text=selected_row.get("alias_text"),
                user=user,
            )
        mark_user_activity(connection)
        connection.commit()
        st.success("Mapeo a catálogo guardado.")
        st.rerun()

    if st.button("Previsualizar documento fuente", key=f"uncataloged-preview-{selected_key}"):
        storage_path = selected_row.get("storage_path")
        if storage_path:
            render_pdf_preview(storage_path, key=f"uncataloged-pdf-{selected_key}")
        else:
            st.info("Este registro no tiene PDF disponible para previsualizar.")


def _render_remediation_tab(connection, user: AuthenticatedUser) -> None:
    st.markdown("**Documentos huérfanos**")
    orphan_rows = document_repo.list_documents_without_case(connection)
    if orphan_rows:
        selected_orphan_id = st.session_state.get("selected_orphan_document_id")
        visible_ids = [row["id"] for row in orphan_rows]
        if selected_orphan_id not in visible_ids:
            selected_orphan_id = visible_ids[0]
            st.session_state["selected_orphan_document_id"] = selected_orphan_id

        orphan_table = pd.DataFrame(
            [
                {
                    "Seleccionar": row["id"] == selected_orphan_id,
                    "document_id": row["id"],
                    "Tipo": row.get("document_type") or "",
                    "Referencia": row.get("source_reference") or row.get("primary_identifier") or "",
                    "Fecha": row.get("document_date") or "",
                    "Hora": row.get("document_time") or "",
                    "Torre": row.get("tower") or "",
                    "Equipo": row.get("equipment_text_original") or row.get("equipment_key") or "",
                    "Documento": row.get("file_name_original") or "",
                }
                for row in orphan_rows
            ]
        )
        edited_orphans = st.data_editor(
            orphan_table,
            hide_index=True,
            use_container_width=True,
            key="orphan-documents-editor",
            disabled=[column for column in orphan_table.columns if column != "Seleccionar"],
            column_config={
                "Seleccionar": st.column_config.CheckboxColumn("Seleccionar"),
                "document_id": None,
            },
        )
        selected_orphans = edited_orphans[edited_orphans["Seleccionar"] == True]
        if not selected_orphans.empty:
            selected_orphan_id = int(selected_orphans.iloc[0]["document_id"])
            st.session_state["selected_orphan_document_id"] = selected_orphan_id

        selected_document = next((row for row in orphan_rows if row["id"] == selected_orphan_id), None)
        if selected_document:
            st.write(f"Documento huérfano: {selected_document.get('file_name_original') or ''}")
            candidate_options = _case_options_for_document(connection, selected_document)
            selected_case_label = st.selectbox(
                "Mapear documento huérfano a caso",
                options=list(candidate_options.keys()) if candidate_options else ["Sin casos disponibles"],
                key=f"orphan-case-option-{selected_orphan_id}",
            )
            action_cols = st.columns(3)
            if action_cols[0].button("Vincular a caso", key=f"orphan-link-{selected_orphan_id}", disabled=not candidate_options):
                linking_service.link_document_to_existing_case(
                    connection,
                    document_id=selected_orphan_id,
                    case_id=candidate_options[selected_case_label],
                    user_id=user.id,
                )
                mark_user_activity(connection)
                connection.commit()
                st.success("Documento huérfano vinculado al caso.")
                st.rerun()
            if action_cols[1].button("Crear caso nuevo", key=f"orphan-new-case-{selected_orphan_id}"):
                linking_service.create_new_case_and_link(
                    connection,
                    document_id=selected_orphan_id,
                    user_id=user.id,
                )
                mark_user_activity(connection)
                connection.commit()
                st.success("Se creó un nuevo caso para el documento huérfano.")
                st.rerun()
            if action_cols[2].button("Previsualizar documento huérfano", key=f"orphan-preview-{selected_orphan_id}"):
                storage_path = selected_document.get("storage_path")
                if storage_path:
                    render_pdf_preview(storage_path, key=f"orphan-pdf-{selected_orphan_id}")

            st.markdown("**Crear ticket usuario desde documento huérfano**")
            with st.form(f"create-user-ticket-{selected_orphan_id}"):
                ticket_date = st.text_input("Fecha", value=selected_document.get("document_date") or "")
                ticket_time = st.text_input("Hora", value=selected_document.get("document_time") or "")
                ticket_description = st.text_area(
                    "Descripción",
                    value=selected_document.get("short_description") or selected_document.get("file_name_original") or "",
                    height=100,
                )
                ticket_state = st.selectbox("Estado", options=USER_TICKET_STATES, key=f"user-ticket-state-{selected_orphan_id}")
                observations = st.text_area("Observaciones", value="", height=80)
                create_ticket = st.form_submit_button("Crear ticket usuario")
            if create_ticket:
                updates.create_user_ticket(
                    connection,
                    payload={
                        "document_date": ticket_date,
                        "document_time": ticket_time or None,
                        "tower": selected_document.get("tower"),
                        "equipment_code": selected_document.get("equipment_code"),
                        "equipment_text_original": selected_document.get("equipment_text_original"),
                        "description": ticket_description.strip(),
                        "ticket_state": ticket_state,
                        "observations": observations.strip() or None,
                        "source_document_id": selected_document["id"],
                        "original_report_reference": selected_document.get("source_reference") if selected_document.get("document_type") == "reporte" else None,
                        "original_finding_reference": selected_document.get("source_reference") if selected_document.get("document_type") == "hallazgo" else None,
                        "original_estimate_reference": selected_document.get("source_reference") if selected_document.get("document_type") == "estimacion" else None,
                    },
                    user=user,
                )
                mark_user_activity(connection)
                connection.commit()
                st.success("Ticket usuario creado.")
                st.rerun()
    else:
        st.caption("No hay documentos huérfanos por resolver.")

    st.divider()
    st.markdown("**Tickets usuario**")
    ticket_rows = user_ticket_repo.list_user_tickets(connection)
    if not ticket_rows:
        st.caption("Aún no hay tickets usuario.")
        return

    selected_ticket_id = st.session_state.get("selected_user_ticket_id")
    ticket_ids = [row["id"] for row in ticket_rows]
    if selected_ticket_id not in ticket_ids:
        selected_ticket_id = ticket_ids[0]
        st.session_state["selected_user_ticket_id"] = selected_ticket_id

    ticket_table = pd.DataFrame(
        [
            {
                "Seleccionar": row["id"] == selected_ticket_id,
                "user_ticket_id": row["id"],
                "Folio": row.get("ticket_folio") or "",
                "Fecha": row.get("document_date") or "",
                "Hora": row.get("document_time") or "",
                "Equipo": row.get("equipment_text_original") or row.get("equipment_code") or "",
                "Estado": row.get("ticket_state") or "",
                "Caso": row.get("case_folio") or "Sin caso",
                "Documento fuente": row.get("source_document_name") or "",
            }
            for row in ticket_rows
        ]
    )
    edited_tickets = st.data_editor(
        ticket_table,
        hide_index=True,
        use_container_width=True,
        key="user-ticket-editor",
        disabled=[column for column in ticket_table.columns if column != "Seleccionar"],
        column_config={
            "Seleccionar": st.column_config.CheckboxColumn("Seleccionar"),
            "user_ticket_id": None,
        },
    )
    selected_ticket_rows = edited_tickets[edited_tickets["Seleccionar"] == True]
    if not selected_ticket_rows.empty:
        selected_ticket_id = int(selected_ticket_rows.iloc[0]["user_ticket_id"])
        st.session_state["selected_user_ticket_id"] = selected_ticket_id

    selected_ticket = next((row for row in ticket_rows if row["id"] == selected_ticket_id), None)
    if not selected_ticket:
        return

    st.write(f"Ticket usuario: {selected_ticket.get('ticket_folio') or ''}")
    st.write(f"Descripción: {selected_ticket.get('description') or ''}")
    st.write(f"Observaciones: {selected_ticket.get('observations') or ''}")
    case_options = _case_options(connection)
    selected_case_label = st.selectbox(
        "Vincular ticket usuario a caso",
        options=list(case_options.keys()) if case_options else ["Sin casos disponibles"],
        key=f"user-ticket-case-option-{selected_ticket_id}",
    )
    ticket_cols = st.columns(3)
    if ticket_cols[0].button("Vincular ticket a caso", key=f"user-ticket-link-{selected_ticket_id}", disabled=not case_options):
        updates.update_user_ticket_case_link(
            connection,
            user_ticket_id=selected_ticket_id,
            case_id=case_options[selected_case_label],
            user=user,
        )
        mark_user_activity(connection)
        connection.commit()
        st.success("Ticket usuario vinculado al caso.")
        st.rerun()
    if ticket_cols[1].button("Previsualizar documento fuente", key=f"user-ticket-preview-{selected_ticket_id}"):
        source_document = (
            document_repo.get_document(connection, selected_ticket.get("source_document_id"))
            if selected_ticket.get("source_document_id")
            else None
        )
        if source_document and source_document.get("storage_path"):
            render_pdf_preview(source_document["storage_path"], key=f"user-ticket-pdf-{selected_ticket_id}")
        else:
            st.info("Este ticket usuario no tiene documento PDF fuente disponible.")
    with st.form(f"user-ticket-update-{selected_ticket_id}"):
        new_state = st.selectbox(
            "Actualizar estado del ticket usuario",
            options=USER_TICKET_STATES,
            index=USER_TICKET_STATES.index(selected_ticket.get("ticket_state") or USER_TICKET_STATES[0]),
        )
        new_observations = st.text_area("Actualizar observaciones", value=selected_ticket.get("observations") or "", height=80)
        save_ticket = st.form_submit_button("Guardar ticket usuario")
    if save_ticket:
        updates.update_user_ticket_fields(
            connection,
            user_ticket_id=selected_ticket_id,
            payload={
                "ticket_state": new_state,
                "observations": new_observations.strip() or None,
            },
            user=user,
        )
        mark_user_activity(connection)
        connection.commit()
        st.success("Ticket usuario actualizado.")
        st.rerun()


def _case_options(connection) -> dict[str, int]:
    return {
        f"{case['case_folio']} | {case.get('tower') or ''} | {case.get('equipment_text_original') or case.get('equipment_key') or ''}": case["id"]
        for case in case_repo.list_cases(connection)
    }


def _case_options_for_document(connection, document: dict) -> dict[str, int]:
    ordered_cases: list[dict] = []
    seen_case_ids: set[int] = set()
    if document.get("equipment_key") and document.get("document_date"):
        for candidate in case_repo.find_candidate_cases(
            connection,
            equipment_key=document["equipment_key"],
            document_date=document["document_date"],
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
