"""Common Streamlit rendering helpers."""

from __future__ import annotations

import base64
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from gtv.app_state import clear_authenticated_session, get_authenticated_user
from gtv.config import Settings
from gtv.constants import DOCUMENT_TYPES
from gtv.models import AuthenticatedUser
from gtv.repositories import app_settings as app_settings_repo
from gtv.repositories import notifications as notification_repo
from gtv.repositories import users as user_repo
from gtv.services import auth as auth_service
from gtv.utils.equipment import (
    format_equipment_filter_option,
    list_equipment_filter_codes,
    list_tower_filter_options,
)

PRIMARY_NAV_PAGES = [
    "Carga de archivos",
    "Reporte de hallazgos",
    "Búsqueda",
]

SECONDARY_NAV_PAGES = [
    "Listado de reportes/tickets",
    "Listado de estimaciones",
    "Partidas",
    "Incidencias",
    "Listado de casos",
    "Detalle de caso",
    "Vinculación pendiente",
    "Revisión piezas hallazgo vs estimación",
]

ADMIN_NAV_PAGES = [
    "Administración de usuarios",
    "Historial de auditoría",
]


def ensure_active_session(connection, settings: Settings) -> AuthenticatedUser | None:
    user = get_authenticated_user()
    session_key = st.session_state.get("auth_session_key")
    if not user or not session_key:
        return None

    last_activity_raw = st.session_state.get("auth_last_activity")
    if not last_activity_raw:
        return user
    timeout_minutes = get_session_timeout_minutes(connection, settings)
    elapsed = datetime.now() - datetime.fromisoformat(last_activity_raw)
    if elapsed.total_seconds() > timeout_minutes * 60:
        auth_service.logout(
            connection,
            session_key=session_key,
            user_email=user.email,
            reason="timeout_inactividad",
        )
        connection.commit()
        clear_authenticated_session()
        st.warning("La sesion expiro por inactividad.")
        return None
    return user


def apply_requested_navigation() -> None:
    requested_page = st.session_state.pop("requested_nav_page", None)
    if requested_page:
        st.session_state["nav_page"] = requested_page


def request_navigation(page: str, **session_updates: object) -> None:
    st.session_state["requested_nav_page"] = page
    for key, value in session_updates.items():
        st.session_state[key] = value


def numbered_dataframe(rows: list[dict], *, start: int = 0) -> pd.DataFrame:
    dataframe = pd.DataFrame(rows)
    if not dataframe.empty:
        dataframe.index = range(start, start + len(dataframe))
    return dataframe


def document_reference_text(document: dict) -> str:
    return (
        document.get("source_reference")
        or document.get("primary_identifier")
        or document.get("normalized_folio")
        or document.get("original_folio")
        or document.get("finding_folio")
        or document.get("base_ticket_number")
        or "sin referencia"
    )


def document_label(document: dict) -> str:
    document_type = document.get("document_type") or ""
    type_label = DOCUMENT_TYPES.get(document_type, document_type.title())
    reference = document_reference_text(document)
    return f"{type_label} - {reference}"


def render_related_documents(bundle: dict, *, key_prefix: str) -> None:
    sections = [
        ("Reportes", bundle.get("reports", [])),
        ("Hallazgos", bundle.get("finding_documents", [])),
        ("Estimaciones", bundle.get("estimate_documents", [])),
    ]
    preview_documents: list[dict] = []

    for section_title, documents in sections:
        st.markdown(f"**{section_title}**")
        if not documents:
            st.caption(f"Sin {section_title.lower()}.")
            continue

        preview_documents.extend(documents)
        rows = [
            {
                "tipo": document_label(document),
                "fecha": document.get("document_date") or "",
                "hora": document.get("document_time") or "",
                "archivo": document.get("file_name_original") or "",
            }
            for document in documents
        ]
        st.dataframe(numbered_dataframe(rows, start=0), use_container_width=True)

    if not preview_documents:
        return

    option_map = {
        f"{doc['id']} - {document_label(doc)} - {doc.get('file_name_original') or ''}": doc
        for doc in preview_documents
    }
    selected_label = st.selectbox(
        "Documento a previsualizar",
        options=list(option_map.keys()),
        key=f"{key_prefix}-preview-select",
    )
    selected_document = option_map[selected_label]
    if st.button("Previsualizar documento seleccionado", key=f"{key_prefix}-preview-button"):
        render_pdf_preview(
            selected_document["storage_path"],
            key=f"{key_prefix}-pdf-{selected_document['id']}",
        )


def tower_filter_selectbox(label: str, *, key: str, include_all: bool = True) -> str | None:
    options = ([""] if include_all else []) + list_tower_filter_options()
    return st.selectbox(
        label,
        options=options,
        key=key,
        format_func=lambda value: "Todas" if value == "" else f"Torre {value}",
    ) or None


def equipment_filter_selectbox(label: str, *, key: str, include_all: bool = True) -> str | None:
    options = ([""] if include_all else []) + list_equipment_filter_codes()
    return st.selectbox(
        label,
        options=options,
        key=key,
        format_func=lambda value: "Todos" if value == "" else format_equipment_filter_option(value),
    ) or None


def mark_user_activity(connection) -> None:
    session_key = st.session_state.get("auth_session_key")
    if not session_key:
        return
    auth_service.touch_session(connection, session_key)
    st.session_state["auth_last_activity"] = datetime.now().replace(microsecond=0).isoformat(sep=" ")


def get_session_timeout_minutes(connection, settings: Settings) -> int:
    return app_settings_repo.get_setting_int(connection, "session_timeout_minutes", settings.session_timeout_minutes)


def render_header(connection, settings: Settings, user: AuthenticatedUser) -> None:
    left, right = st.columns([6, 1])
    left.title(settings.app_title)
    if right.button("Logout", use_container_width=True):
        auth_service.logout(
            connection,
            session_key=st.session_state["auth_session_key"],
            user_email=user.email,
            reason="logout_manual",
        )
        connection.commit()
        clear_authenticated_session()
        st.rerun()
    render_notifications_banner(connection, settings, user)


@st.fragment(run_every="1s")
def _render_sidebar_timeout_panel(connection, settings: Settings, user: AuthenticatedUser) -> None:
    last_activity_raw = st.session_state.get("auth_last_activity")
    if not last_activity_raw:
        st.caption("Sin actividad registrada.")
        return
    timeout_minutes = get_session_timeout_minutes(connection, settings)
    remaining = int(
        timeout_minutes * 60
        - (datetime.now() - datetime.fromisoformat(last_activity_raw)).total_seconds()
    )
    if remaining <= 0:
        auth_service.logout(
            connection,
            session_key=st.session_state["auth_session_key"],
            user_email=user.email,
            reason="timeout_inactividad",
        )
        connection.commit()
        clear_authenticated_session()
        st.rerun()
    st.markdown("**Tiempo para deslogueo por inactividad**")
    st.markdown(f"`{_format_seconds_as_clock(remaining)}`")
    if st.button("Sigo activo", key="sidebar-still-active", use_container_width=True):
        mark_user_activity(connection)
        connection.commit()
        st.rerun()


def render_sidebar_navigation(connection, settings: Settings, user: AuthenticatedUser) -> str:
    if "nav_page" not in st.session_state:
        st.session_state["nav_page"] = PRIMARY_NAV_PAGES[0]

    with st.sidebar:
        st.markdown(f"**{user.preferred_name}**")
        _render_sidebar_timeout_panel(connection, settings, user)
        st.divider()
        for page in PRIMARY_NAV_PAGES:
            _render_nav_button(page)
        st.divider()
        for page in SECONDARY_NAV_PAGES:
            _render_nav_button(page)
        st.divider()
        for page in ADMIN_NAV_PAGES:
            _render_nav_button(page)

    return st.session_state.get("nav_page", PRIMARY_NAV_PAGES[0])


def _render_nav_button(page: str) -> None:
    is_active = st.session_state.get("nav_page") == page
    if st.button(
        page,
        key=f"nav-button-{page}",
        use_container_width=True,
        type="primary" if is_active else "secondary",
    ):
        st.session_state["nav_page"] = page


def _format_seconds_as_clock(total_seconds: int) -> str:
    safe_seconds = max(0, total_seconds)
    minutes, seconds = divmod(safe_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def render_notifications_banner(connection, settings: Settings, user: AuthenticatedUser) -> None:
    if user.role != "semilla_admin":
        return
    pending_requests = user_repo.list_pending_access_requests(connection)
    if not pending_requests:
        return
    st.info("Hay solicitudes de acceso pendientes.")
    for request in pending_requests[:5]:
        cols = st.columns([4, 1, 1])
        cols[0].markdown(
            f"**Solicitud #{request['id']}** - {request['email']} ({request['full_name']})"
        )
        if cols[1].button("Aprobar", key=f"banner-approve-{request['id']}"):
            from gtv.services.auth import approve_access_request

            approve_access_request(connection, settings, request_id=request["id"], resolver_user=user)
            mark_user_activity(connection)
            connection.commit()
            st.rerun()
        if cols[2].button("Rechazar", key=f"banner-reject-{request['id']}"):
            from gtv.services.auth import reject_access_request

            reject_access_request(connection, settings, request_id=request["id"], resolver_user=user)
            mark_user_activity(connection)
            connection.commit()
            st.rerun()


def render_pdf_preview(document_path: str, *, key: str) -> None:
    path = Path(document_path)
    if not path.exists():
        st.error("No se encontro el archivo PDF en disco.")
        return
    pdf_data = base64.b64encode(path.read_bytes()).decode("utf-8")
    st.components.v1.html(
        f"""
        <iframe
            src="data:application/pdf;base64,{pdf_data}"
            width="100%"
            height="700"
            type="application/pdf"
        ></iframe>
        """,
        height=720,
        scrolling=True,
    )


def mark_notifications_read(connection, user: AuthenticatedUser) -> None:
    notifications = notification_repo.list_notifications_for_user(connection, user.email)
    for notification in notifications:
        if notification["status"] == "enviada":
            notification_repo.mark_notification_read(connection, notification["id"])
