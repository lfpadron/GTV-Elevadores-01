"""Login view with OTP and first-access request flow."""

from __future__ import annotations

import streamlit as st

from gtv.app_state import set_authenticated_session
from gtv.config import Settings
from gtv.services import auth as auth_service
from gtv.version import version_display_text


def render(connection, settings: Settings) -> None:
    st.title("Ingreso local")
    st.caption("Acceso con OTP por correo y flujo de aprobacion local.")
    st.caption(version_display_text())

    with st.form("request_login_form", clear_on_submit=False):
        email = st.text_input("Correo", placeholder="usuario@dominio.com").strip().lower()
        full_name = st.text_input(
            "Nombre (solo primera solicitud)",
            placeholder="Nombre completo",
        ).strip()
        preferred_name = st.text_input(
            "Nombre preferido (solo primera solicitud)",
            placeholder="Nombre corto a mostrar",
        ).strip()
        submit_request = st.form_submit_button("Enviar OTP / Solicitar acceso")

    if submit_request and email:
        result = auth_service.request_login_or_access(
            connection,
            settings,
            email=email,
            full_name=full_name or None,
            preferred_name=preferred_name or None,
        )
        connection.commit()
        st.session_state["pending_login_email"] = email
        _render_result_message(result)

    pending_email = st.session_state.get("pending_login_email")
    if pending_email:
        st.divider()
        st.subheader("Validar OTP")
        with st.form("otp_verify_form", clear_on_submit=True):
            otp_code = st.text_input("Codigo OTP", max_chars=6)
            verify = st.form_submit_button("Ingresar")
        if verify and otp_code:
            result = auth_service.verify_otp(connection, email=pending_email, code=otp_code)
            connection.commit()
            if result["status"] == "ok":
                set_authenticated_session(result["user"], result["session_key"])
                st.success(result["message"])
                st.rerun()
            else:
                st.error(result["message"])

        if st.button("Reenviar OTP"):
            result = auth_service.request_login_or_access(connection, settings, email=pending_email)
            connection.commit()
            _render_result_message(result)


def _render_result_message(result: dict) -> None:
    status = result["status"]
    if status in {"otp_sent", "request_created"}:
        st.success(result["message"])
    elif status in {"pending", "otp_wait"}:
        st.warning(result["message"])
    else:
        st.error(result["message"])
