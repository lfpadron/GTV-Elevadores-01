"""Shared Streamlit runtime and session state helpers."""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from gtv.config import Settings, get_settings
from gtv.db.connection import get_connection
from gtv.db.init_db import initialize_database
from gtv.models import AuthenticatedUser


@st.cache_resource
def get_runtime() -> tuple[Settings, object]:
    settings = get_settings()
    initialize_database(settings)
    connection = get_connection(settings)
    return settings, connection


def set_authenticated_session(user: AuthenticatedUser, session_key: str) -> None:
    st.session_state["auth_user"] = user
    st.session_state["auth_session_key"] = session_key
    st.session_state["auth_last_activity"] = datetime.now().replace(microsecond=0).isoformat(sep=" ")


def clear_authenticated_session() -> None:
    for key in [
        "auth_user",
        "auth_session_key",
        "auth_last_activity",
        "pending_login_email",
        "selected_case_id",
        "requested_nav_page",
    ]:
        st.session_state.pop(key, None)


def get_authenticated_user() -> AuthenticatedUser | None:
    user = st.session_state.get("auth_user")
    return user if isinstance(user, AuthenticatedUser) else None
