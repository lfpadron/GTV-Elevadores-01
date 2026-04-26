"""Case detail view with operational editing."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from gtv.constants import CASE_STATUS_PRESETS, ITEM_PAYMENT_STATES, ITEM_RECEIPT_STATES, UNIT_PAYMENT_STATES, UNIT_RECEIPT_STATES
from gtv.models import AuthenticatedUser
from gtv.repositories import cases as case_repo
from gtv.services import cases as case_service
from gtv.services import exports as export_service
from gtv.services import updates
from gtv.views.common import mark_user_activity, request_navigation


def render(connection, user: AuthenticatedUser) -> None:
    st.header("Detalle de caso")
    cases = case_repo.list_cases(connection)
    if not cases:
        st.info("No hay casos disponibles.")
        return

    selected_case_id = st.session_state.get("selected_case_id", cases[0]["id"])
    selected_label = st.selectbox(
        "Caso",
        options=[f"{case['id']} - {case['case_folio']}" for case in cases],
        index=next((index for index, case in enumerate(cases) if case["id"] == selected_case_id), 0),
    )
    selected_case_id = int(selected_label.split(" - ", 1)[0])
    st.session_state["selected_case_id"] = selected_case_id

    bundle = case_service.build_case_bundle(connection, selected_case_id)
    if not bundle:
        st.error("No se encontro el caso.")
        return

    case = bundle["case"]
    st.subheader("Seccion 1")
    col1, col2, col3 = st.columns(3)
    col1.metric("Folio caso", case["case_folio"])
    col2.metric("Estado sugerido", case.get("suggested_consolidated_status") or "")
    col3.metric("Estado manual vigente", case.get("manual_consolidated_status") or "Sin definir")
    st.write(f"Equipo: {case.get('equipment_text_original') or case.get('equipment_key')}")

    manual_options = [""] + CASE_STATUS_PRESETS
    selected_manual = st.selectbox(
        "Estado manual",
        options=manual_options,
        index=manual_options.index(case.get("manual_consolidated_status") or ""),
    )
    if st.button("Guardar estado manual del caso"):
        updates.update_case_manual_status(
            connection,
            case_id=selected_case_id,
            manual_status=selected_manual or None,
            user=user,
        )
        mark_user_activity(connection)
        connection.commit()
        st.success("Estado manual actualizado.")
        st.rerun()

    st.subheader("Seccion 2")
    st.markdown("**Reportes vinculados**")
    st.dataframe(pd.DataFrame(bundle["reports"]), use_container_width=True)
    st.markdown("**Hallazgos vinculados**")
    st.dataframe(pd.DataFrame(bundle["finding_documents"]), use_container_width=True)
    st.markdown("**Estimaciones vinculadas**")
    st.dataframe(pd.DataFrame(bundle["estimate_documents"]), use_container_width=True)
    st.markdown("**Tickets usuario vinculados**")
    st.dataframe(pd.DataFrame(bundle["user_tickets"]), use_container_width=True)

    all_documents = bundle["reports"] + bundle["finding_documents"] + bundle["estimate_documents"]
    if all_documents:
        selected_doc_label = st.selectbox(
            "Resumen editable por documento",
            options=[f"{doc['id']} - {doc['file_name_original']}" for doc in all_documents],
        )
        selected_doc_id = int(selected_doc_label.split(" - ", 1)[0])
        current_doc = next(doc for doc in all_documents if doc["id"] == selected_doc_id)
        summary_value = st.text_area(
            "Resumen inteligente editable",
            value=current_doc.get("summary_user_edited") or current_doc.get("summary_ai_original") or "",
            height=120,
        )
        if st.button("Guardar resumen editable"):
            updates.update_summary(
                connection,
                document_id=selected_doc_id,
                summary_user_edited=summary_value,
                user=user,
            )
            mark_user_activity(connection)
            connection.commit()
            st.success("Resumen actualizado.")
            st.rerun()

    st.subheader("Seccion 3")
    st.dataframe(pd.DataFrame(bundle["findings"]), use_container_width=True)

    st.subheader("Seccion 4")
    st.dataframe(pd.DataFrame(bundle["estimate_items"]), use_container_width=True)
    st.dataframe(pd.DataFrame(bundle["units"]), use_container_width=True)

    if bundle["estimate_items"]:
        selected_item_label = st.selectbox(
            "Editar partida",
            options=[f"{item['id']} - {item['concept_text'][:80]}" for item in bundle["estimate_items"]],
        )
        selected_item_id = int(selected_item_label.split(" - ", 1)[0])
        item = next(item for item in bundle["estimate_items"] if item["id"] == selected_item_id)
        with st.form(f"item-edit-{selected_item_id}"):
            receipt_status = st.selectbox(
                "Estado recepcion de partida",
                options=ITEM_RECEIPT_STATES,
                index=ITEM_RECEIPT_STATES.index(item.get("receipt_status") or ITEM_RECEIPT_STATES[0]),
            )
            payment_status = st.selectbox(
                "Estado pago de partida",
                options=ITEM_PAYMENT_STATES,
                index=ITEM_PAYMENT_STATES.index(item.get("payment_status") or ITEM_PAYMENT_STATES[0]),
            )
            reception_date = st.text_input("Fecha recepcion", value=item.get("reception_date") or "")
            payment_date = st.text_input("Fecha pago", value=item.get("payment_date") or "")
            payment_method = st.text_input("Forma de pago", value=item.get("payment_method") or "")
            invoice_date = st.text_input("Fecha factura", value=item.get("invoice_date") or "")
            invoice_number = st.text_input("Numero factura", value=item.get("invoice_number") or "")
            propagate_mode = st.selectbox(
                "Propagacion a unidades",
                options=["sin_propagacion", "sobrescribe_todo", "solo_vacios"],
            )
            save_item = st.form_submit_button("Guardar partida")
        if save_item:
            updates.update_item_operational_fields(
                connection,
                item_id=selected_item_id,
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

    if bundle["units"]:
        selected_unit_label = st.selectbox(
            "Editar unidad",
            options=[f"{unit['id']} - Item {unit['estimate_item_id']} / unidad {unit['unit_index']}" for unit in bundle["units"]],
        )
        selected_unit_id = int(selected_unit_label.split(" - ", 1)[0])
        unit = next(unit for unit in bundle["units"] if unit["id"] == selected_unit_id)
        with st.form(f"unit-edit-{selected_unit_id}"):
            unit_receipt_status = st.selectbox(
                "Estado recepcion unidad",
                options=UNIT_RECEIPT_STATES,
                index=UNIT_RECEIPT_STATES.index(unit.get("receipt_status") or UNIT_RECEIPT_STATES[0]),
            )
            unit_payment_status = st.selectbox(
                "Estado pago unidad",
                options=UNIT_PAYMENT_STATES,
                index=UNIT_PAYMENT_STATES.index(unit.get("payment_status") or UNIT_PAYMENT_STATES[0]),
            )
            unit_reception_date = st.text_input("Fecha recepcion unidad", value=unit.get("reception_date") or "")
            unit_payment_date = st.text_input("Fecha pago unidad", value=unit.get("payment_date") or "")
            unit_payment_method = st.text_input("Forma de pago unidad", value=unit.get("payment_method") or "")
            unit_invoice_date = st.text_input("Fecha factura unidad", value=unit.get("invoice_date") or "")
            unit_invoice_number = st.text_input("Numero factura unidad", value=unit.get("invoice_number") or "")
            save_unit = st.form_submit_button("Guardar unidad")
        if save_unit:
            updates.update_unit_operational_fields(
                connection,
                unit_id=selected_unit_id,
                payload={
                    "receipt_status": unit_receipt_status,
                    "payment_status": unit_payment_status,
                    "reception_date": unit_reception_date or None,
                    "payment_date": unit_payment_date or None,
                    "payment_method": unit_payment_method or None,
                    "invoice_date": unit_invoice_date or None,
                    "invoice_number": unit_invoice_number or None,
                },
                user=user,
            )
            mark_user_activity(connection)
            connection.commit()
            st.success("Unidad actualizada.")
            st.rerun()

    st.subheader("Seccion 5")
    st.dataframe(pd.DataFrame(bundle["matches"]), use_container_width=True)
    if st.button("Ir a revision hallazgo vs estimacion"):
        request_navigation("Revisión piezas hallazgo vs estimación", selected_case_id=selected_case_id)
        st.rerun()

    excel_bytes, pdf_bytes = export_service.export_case_bundle(bundle)
    st.download_button(
        "Exportar detalle de caso a Excel",
        data=excel_bytes,
        file_name=export_service.export_filename(case["case_folio"], "xlsx"),
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    st.download_button(
        "Exportar detalle de caso a PDF",
        data=pdf_bytes,
        file_name=export_service.export_filename(case["case_folio"], "pdf"),
        mime="application/pdf",
    )
