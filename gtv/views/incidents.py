"""Incident tray for duplicates, unrecognized docs and extraction review."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from gtv.config import Settings
from gtv.models import AuthenticatedUser
from gtv.repositories import documents as document_repo
from gtv.services import ingestion, updates
from gtv.views.common import mark_user_activity, numbered_dataframe


def render(connection, settings: Settings, user: AuthenticatedUser) -> None:
    st.header("Incidencias")
    incidents = document_repo.list_incidents(connection)
    if not incidents:
        st.success("No hay incidencias pendientes.")
        return

    incident_rows = [
        {
            "incidencia_id": row["id"],
            "tipo_incidencia": row["incident_type"],
            "titulo": row["title"],
            "tipo_documento": row.get("document_type") or "",
            "identificador": row.get("primary_identifier") or "",
            "archivo": row.get("file_name_original") or "",
            "estado": row.get("status") or "",
            "creada_en": row.get("created_at") or "",
        }
        for row in incidents
    ]
    st.dataframe(numbered_dataframe(incident_rows, start=1), use_container_width=True)
    selected_label = st.selectbox(
        "Selecciona una incidencia",
        options=[f"{row['id']} - {row['incident_type']} - {row['title']}" for row in incidents],
    )
    incident_id = int(selected_label.split(" - ", 1)[0])
    incident = document_repo.get_incident(connection, incident_id)
    if not incident:
        st.error("No se encontro la incidencia.")
        return

    st.subheader(incident["title"])
    st.write(incident["details"])
    if not incident.get("document_id"):
        return
    document = document_repo.get_document_with_details(connection, incident["document_id"])
    if not document:
        st.error("No se encontro el documento asociado.")
        return

    st.json(
        {
            "document_id": document["id"],
            "tipo": document["document_type"],
            "archivo": document["file_name_original"],
            "identificador": document.get("primary_identifier"),
            "fecha": document.get("document_date"),
            "equipo": document.get("equipment_text_original"),
            "extraccion": document.get("extraction_status"),
        }
    )

    if incident["incident_type"] == "tipo_no_reconocido":
        _render_reclassify_form(connection, settings, user, incident_id, document["id"])
    elif incident["incident_type"] == "duplicado_nombre":
        _render_duplicate_review(connection, settings, user, incident_id, incident, document)
    else:
        _render_correction_form(connection, user, incident_id, document)


def _render_reclassify_form(connection, settings: Settings, user: AuthenticatedUser, incident_id: int, document_id: int) -> None:
    new_type = st.selectbox(
        "Clasificacion manual",
        options=["reporte", "hallazgo", "estimacion"],
        key=f"reclassify-{document_id}",
    )
    if st.button("Guardar clasificacion manual", key=f"btn-reclassify-{document_id}"):
        ingestion.reclassify_document(
            connection,
            settings,
            document_id=document_id,
            new_document_type=new_type,
        )
        document_repo.resolve_incident(
            connection,
            incident_id=incident_id,
            user_id=user.id,
            resolution_notes=f"Clasificado manualmente como {new_type}",
        )
        mark_user_activity(connection)
        connection.commit()
        st.success("Documento reclasificado.")
        st.rerun()


def _render_duplicate_review(connection, settings: Settings, user: AuthenticatedUser, incident_id: int, incident: dict, document: dict) -> None:
    if incident.get("duplicate_of_document_id"):
        previous = document_repo.get_document(connection, incident["duplicate_of_document_id"])
        if previous:
            st.info(
                f"Documento previo: ID {previous['id']} - {previous['file_name_original']} - {previous.get('primary_identifier')}"
            )

    col1, col2 = st.columns(2)
    if col1.button("Conservar y renombrar", key=f"keep-dup-{document['id']}"):
        result = ingestion.keep_duplicate_document(connection, settings, document_id=document["id"])
        document_repo.resolve_incident(
            connection,
            incident_id=incident_id,
            user_id=user.id,
            resolution_notes=f"Duplicado conservado como {result['file_name_stored']}",
        )
        mark_user_activity(connection)
        connection.commit()
        st.success("Duplicado conservado.")
        st.rerun()

    if col2.button("Descartar documento duplicado", key=f"discard-dup-{document['id']}"):
        ingestion.discard_duplicate_document(connection, document_id=document["id"])
        document_repo.resolve_incident(
            connection,
            incident_id=incident_id,
            user_id=user.id,
            resolution_notes="Documento duplicado descartado por usuario",
            discarded=True,
        )
        mark_user_activity(connection)
        connection.commit()
        st.success("Duplicado descartado.")
        st.rerun()


def _render_correction_form(connection, user: AuthenticatedUser, incident_id: int, document: dict) -> None:
    positions = [row["name"] for row in document_repo.list_positions(connection)]
    details = document.get("details", {})

    with st.form(f"correction-form-{document['id']}"):
        date_value = st.text_input("Fecha", value=document.get("document_date") or "")
        time_value = st.text_input("Hora", value=document.get("document_time") or "")
        tower = st.text_input("Torre", value=document.get("tower") or "")
        position = st.selectbox(
            "Posicion",
            options=[""] + positions,
            index=([""] + positions).index(document.get("position_name") or "") if (document.get("position_name") or "") in ([""] + positions) else 0,
        )
        equipment = st.text_input("Equipo", value=document.get("equipment_text_original") or "")
        identifier = st.text_input("Identificador principal", value=document.get("primary_identifier") or "")

        detail_fields: dict[str, object] = {}
        if document["document_type"] == "reporte":
            detail_fields["ticket_number"] = st.text_input("Ticket", value=details.get("ticket_number") or "")
            detail_fields["description"] = st.text_area("Descripcion", value=details.get("description") or "", height=160)
            detail_fields["cause_text"] = st.text_area("Causa", value=details.get("cause_text") or "", height=100)
            detail_fields["solution_text"] = st.text_area("Solucion", value=details.get("solution_text") or "", height=100)
        elif document["document_type"] == "hallazgo":
            detail_fields["base_ticket_number"] = st.text_input("Ticket base", value=details.get("base_ticket_number") or "")
            detail_fields["finding_folio"] = st.text_input("Folio hallazgo", value=details.get("finding_folio") or "")
            detail_fields["description"] = st.text_area("Descripcion hallazgo", value=details.get("description") or "", height=160)
            detail_fields["affected_part_text"] = st.text_area("Pieza afectada", value=details.get("affected_part_text") or "", height=100)
            detail_fields["recommendation_text"] = st.text_area("Recomendacion", value=details.get("recommendation_text") or "", height=100)
        elif document["document_type"] == "estimacion":
            detail_fields["original_folio"] = st.text_input("Folio original", value=details.get("original_folio") or "")
            detail_fields["normalized_folio"] = st.text_input("Folio normalizado", value=details.get("normalized_folio") or "")
            detail_fields["delivery_days"] = st.number_input("Dias naturales", min_value=0, value=int(details.get("delivery_days") or 0))
            detail_fields["estimated_delivery_date"] = st.text_input(
                "Fecha estimada de entrega",
                value=details.get("estimated_delivery_date") or "",
            )
            detail_fields["subtotal_amount"] = st.number_input(
                "Subtotal",
                min_value=0.0,
                value=float(details.get("subtotal_amount") or 0.0),
                step=1.0,
            )
            detail_fields["tax_amount"] = st.number_input(
                "Impuesto",
                min_value=0.0,
                value=float(details.get("tax_amount") or 0.0),
                step=1.0,
            )
            detail_fields["total_amount"] = st.number_input(
                "Total",
                min_value=0.0,
                value=float(details.get("total_amount") or 0.0),
                step=1.0,
            )
            items = document_repo.list_estimate_items(connection, document["id"])
            if items:
                st.caption("Partidas extraidas actualmente")
                st.dataframe(pd.DataFrame(items), use_container_width=True)

        submit = st.form_submit_button("Guardar correcciones y resolver")

    if submit:
        document_fields = {
            "document_date": date_value or None,
            "document_time": time_value or None,
            "tower": tower or None,
            "position_name": position or None,
            "equipment_text_original": equipment or None,
            "primary_identifier": identifier or None,
        }
        cleaned_detail_fields = {key: (value if value != "" else None) for key, value in detail_fields.items()}
        updates.update_document_corrections(
            connection,
            document_id=document["id"],
            user=user,
            document_fields=document_fields,
            detail_fields=cleaned_detail_fields,
        )
        document_repo.resolve_incident(
            connection,
            incident_id=incident_id,
            user_id=user.id,
            resolution_notes="Correccion manual completada",
        )
        mark_user_activity(connection)
        connection.commit()
        st.success("Correcciones guardadas.")
        st.rerun()
