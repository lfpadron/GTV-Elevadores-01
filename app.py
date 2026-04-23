"""Main Streamlit application entry point."""

from __future__ import annotations

import streamlit as st

from gtv.app_state import get_runtime
from gtv.config import SecretsConfigurationError, render_secret_error
from gtv.views import (
    audit,
    case_detail,
    cases,
    estimate_listing,
    incidents,
    loaded_documents,
    linking,
    login,
    matching,
    partidas,
    report_hallazgos,
    report_tickets,
    search,
    uploads,
    users_admin,
)
from gtv.views.common import apply_requested_navigation, ensure_active_session, render_header, render_sidebar_navigation


st.set_page_config(page_title="Grand Tower del Valle", layout="wide")

try:
    settings, connection = get_runtime()
except SecretsConfigurationError as exc:
    st.error(render_secret_error(exc))
    st.stop()

user = ensure_active_session(connection, settings)

if not user:
    login.render(connection, settings)
    st.stop()

render_header(connection, settings, user)
apply_requested_navigation()

page = render_sidebar_navigation(connection, settings, user)

if page == "Carga de archivos":
    uploads.render(connection, settings, user)
elif page == "Listado de reportes/tickets":
    report_tickets.render(connection, user)
elif page == "Reporte de fallas":
    report_hallazgos.render(connection, user)
elif page == "Listado de estimaciones":
    estimate_listing.render(connection, user)
elif page == "Partidas":
    partidas.render(connection, user)
elif page == "Incidencias":
    incidents.render(connection, settings, user)
elif page == "Búsqueda":
    search.render(connection, user)
elif page == "Documentos cargados":
    loaded_documents.render(connection, user)
elif page == "Listado de casos":
    cases.render(connection)
elif page == "Detalle de caso":
    case_detail.render(connection, user)
elif page == "Vinculación pendiente":
    linking.render(connection, user)
elif page == "Revisión piezas hallazgo vs estimación":
    matching.render(connection, user)
elif page == "Administración de usuarios":
    users_admin.render(connection, settings, user)
elif page == "Historial de auditoría":
    audit.render(connection)
