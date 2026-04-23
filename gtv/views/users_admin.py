"""User administration and notification history."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from gtv.config import Settings
from gtv.models import AuthenticatedUser
from gtv.repositories import app_settings as app_settings_repo
from gtv.repositories import notifications as notification_repo
from gtv.repositories import users as user_repo
from gtv.services import auth as auth_service
from gtv.services import updates
from gtv.views.common import mark_notifications_read, mark_user_activity


def render(connection, settings: Settings, user: AuthenticatedUser) -> None:
    st.header("Administracion de usuarios")
    if user.role != "semilla_admin":
        st.warning("Solo los administradores semilla pueden ver esta pantalla.")
        return

    st.subheader("Configuración de sesión")
    current_timeout = app_settings_repo.get_setting_int(connection, "session_timeout_minutes", settings.session_timeout_minutes)
    timeout_value = st.number_input(
        "Tiempo de inactividad para logout (minutos)",
        min_value=1,
        max_value=480,
        value=int(current_timeout),
        step=1,
    )
    if st.button("Guardar tiempo de inactividad"):
        app_settings_repo.upsert_setting(connection, "session_timeout_minutes", str(int(timeout_value)))
        mark_user_activity(connection)
        connection.commit()
        st.success("Tiempo de inactividad actualizado.")
        st.rerun()

    pending = user_repo.list_pending_access_requests(connection)
    st.subheader("Solicitudes pendientes")
    st.dataframe(pd.DataFrame(pending), use_container_width=True)
    if pending:
        selected_request_label = st.selectbox(
            "Solicitud",
            options=[f"{row['id']} - {row['email']}" for row in pending],
        )
        request_id = int(selected_request_label.split(" - ", 1)[0])
        notes = st.text_input("Notas de resolucion")
        col1, col2 = st.columns(2)
        if col1.button("Aprobar solicitud"):
            auth_service.approve_access_request(connection, settings, request_id=request_id, resolver_user=user, notes=notes or None)
            mark_user_activity(connection)
            connection.commit()
            st.success("Solicitud aprobada.")
            st.rerun()
        if col2.button("Rechazar solicitud"):
            auth_service.reject_access_request(connection, settings, request_id=request_id, resolver_user=user, notes=notes or None)
            mark_user_activity(connection)
            connection.commit()
            st.success("Solicitud rechazada.")
            st.rerun()

    st.subheader("Usuarios")
    users = user_repo.list_users(connection)
    st.dataframe(pd.DataFrame(users), use_container_width=True)
    selected_user_label = st.selectbox(
        "Usuario",
        options=[f"{row['id']} - {row['email']}" for row in users],
    )
    target_user_id = int(selected_user_label.split(" - ", 1)[0])
    new_status = st.selectbox("Nuevo estado", options=["activo", "deshabilitado", "rechazado", "pendiente_aprobacion"])
    if st.button("Actualizar estado de usuario"):
        updates.update_user_status(connection, target_user_id=target_user_id, status=new_status, actor=user)
        mark_user_activity(connection)
        connection.commit()
        st.success("Estado actualizado.")
        st.rerun()

    st.subheader("Historial de notificaciones")
    mark_notifications_read(connection, user)
    notifications = notification_repo.list_notifications_for_user(connection, user.email)
    connection.commit()
    st.dataframe(pd.DataFrame(notifications), use_container_width=True)
