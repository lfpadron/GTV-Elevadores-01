"""Upload view for one or many PDFs."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from gtv.config import Settings
from gtv.models import AuthenticatedUser
from gtv.services import ingestion
from gtv.views.common import mark_user_activity


def render(connection, settings: Settings, user: AuthenticatedUser) -> None:
    st.header("Carga de archivos")
    st.caption("La carga masiva procesa todos los PDFs y deja incidencias para revision posterior.")

    staging_folder = settings.data_dir / "por_procesar"
    staging_files = sorted(staging_folder.rglob("*.pdf")) if staging_folder.exists() else []
    if staging_folder.exists():
        st.info(f"Carpeta local detectada: `{staging_folder}`. PDFs encontrados: {len(staging_files)}")
        if st.button("Procesar PDFs desde data/por_procesar", disabled=not staging_files):
            try:
                results = ingestion.process_pdf_folder(
                    connection,
                    settings,
                    folder_path=staging_folder,
                    uploaded_by=user,
                )
                mark_user_activity(connection)
                connection.commit()
                st.success(f"Procesados {len(results)} archivo(s) desde carpeta local.")
                st.dataframe(pd.DataFrame(results), use_container_width=True)
            except Exception as exc:  # pragma: no cover - depende de PDFs reales.
                st.error(f"No fue posible procesar la carpeta: {exc}")

    uploaded_files = st.file_uploader(
        "Arrastra uno o varios PDFs",
        type=["pdf"],
        accept_multiple_files=True,
    )
    process = st.button("Procesar carga")

    if process and uploaded_files:
        results: list[dict] = []
        for uploaded in uploaded_files:
            try:
                result = ingestion.process_uploaded_pdf(
                    connection,
                    settings,
                    file_name=uploaded.name,
                    file_bytes=uploaded.getvalue(),
                    uploaded_by=user,
                )
                results.append(result)
            except Exception as exc:  # pragma: no cover - depende de PDFs reales.
                results.append(
                    {
                        "document_id": None,
                        "document_type": "error",
                        "extraction_status": "fallo",
                        "incidents": [str(exc)],
                        "stored_path": "",
                    }
                )
        mark_user_activity(connection)
        connection.commit()
        st.success(f"Procesados {len(results)} archivo(s).")
        st.dataframe(pd.DataFrame(results), use_container_width=True)
    elif process:
        st.warning("Selecciona al menos un PDF.")
