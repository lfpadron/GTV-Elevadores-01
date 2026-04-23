"""Audit history view."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from gtv.repositories import audit as audit_repo


def render(connection) -> None:
    st.header("Historial de auditoria")
    logs = audit_repo.list_audit_logs(connection)
    if not logs:
        st.info("No hay eventos de auditoria registrados todavia.")
        return
    st.dataframe(pd.DataFrame(logs), use_container_width=True)
