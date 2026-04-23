"""Textual TUI to reset all document data and recreate an empty database."""

from __future__ import annotations

from pathlib import Path
import sqlite3
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Header, Input, Static

from gtv.config import get_settings
from gtv.db.connection import get_connection
from gtv.db.init_db import initialize_database

DOCUMENT_RESET_FOLDERS = [
    "por_procesar",
    "reportes",
    "hallazgos",
    "estimaciones",
    "no_reconocidos",
    "duplicados",
]


def _count_pdf_files(root: Path) -> int:
    if not root.exists():
        return 0
    return sum(1 for path in root.rglob("*.pdf") if path.is_file())


def _safe_document_count(db_path: Path) -> int:
    if not db_path.exists():
        return 0
    try:
        with sqlite3.connect(db_path) as connection:
            table_exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'documents'"
            ).fetchone()
            if not table_exists:
                return 0
            row = connection.execute("SELECT COUNT(*) FROM documents").fetchone()
            return int(row[0]) if row else 0
    except sqlite3.DatabaseError:
        return 0


def _clear_folder_contents(root: Path) -> tuple[int, int]:
    root.mkdir(parents=True, exist_ok=True)
    deleted_files = 0
    deleted_directories = 0

    for child in sorted(root.rglob("*"), reverse=True):
        if child.is_file():
            child.unlink(missing_ok=True)
            deleted_files += 1
        elif child.is_dir():
            try:
                child.rmdir()
                deleted_directories += 1
            except OSError:
                pass

    return deleted_files, deleted_directories


def inspect_reset_context() -> dict[str, str | int]:
    settings = get_settings(validate_secrets=False)
    folder_counts = {
        folder_name: _count_pdf_files(settings.data_dir / folder_name)
        for folder_name in DOCUMENT_RESET_FOLDERS
    }

    return {
        "db_path": str(settings.db_path),
        "documents_in_db": _safe_document_count(settings.db_path),
        "por_procesar": folder_counts["por_procesar"],
        "processed_pdfs": sum(
            folder_counts[folder_name]
            for folder_name in DOCUMENT_RESET_FOLDERS
            if folder_name != "por_procesar"
        ),
        "total_pdf_files": sum(folder_counts.values()),
    }


def reset_documents() -> dict[str, int]:
    settings = get_settings()
    deleted_files = 0
    deleted_directories = 0

    for folder_name in DOCUMENT_RESET_FOLDERS:
        files_removed, directories_removed = _clear_folder_contents(settings.data_dir / folder_name)
        deleted_files += files_removed
        deleted_directories += directories_removed

    if settings.db_path.exists():
        try:
            settings.db_path.unlink()
            deleted_files += 1
        except PermissionError as exc:
            raise RuntimeError(
                "No se pudo resetear la base de datos porque está en uso. "
                "Cierra Streamlit u otros procesos que tengan abierto el archivo SQLite y vuelve a intentarlo."
            ) from exc

    initialize_database(settings)

    with get_connection(settings) as connection:
        documents_after_reset = connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        seed_users = connection.execute("SELECT COUNT(*) FROM users WHERE is_seed = 1").fetchone()[0]

    return {
        "deleted_files": deleted_files,
        "deleted_directories": deleted_directories,
        "documents_after_reset": int(documents_after_reset),
        "seed_users": int(seed_users),
    }


class RefreshDocumentsApp(App[None]):
    """Interactive reset utility for all document data."""

    CSS = """
    Screen {
        align: center middle;
    }

    #root {
        width: 104;
        max-width: 120;
        height: auto;
        border: round $primary;
        padding: 1 2;
        background: $surface;
    }

    .title {
        text-style: bold;
        margin-bottom: 1;
    }

    .subtitle {
        color: $text-muted;
        margin-bottom: 1;
    }

    #warning {
        color: $warning;
        margin-top: 1;
        margin-bottom: 1;
    }

    #summary {
        height: auto;
        min-height: 7;
        border: round $panel;
        padding: 1;
        margin-bottom: 1;
    }

    Input {
        margin-top: 1;
        margin-bottom: 1;
    }

    #actions {
        height: auto;
        margin-top: 1;
    }

    #status {
        height: auto;
        min-height: 4;
        margin-top: 1;
    }

    Button {
        width: 1fr;
    }
    """

    BINDINGS = [("ctrl+c", "quit", "Salir")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="root"):
            yield Static("Reset Documental", classes="title")
            yield Static(
                "Deja el sistema como nuevo en la parte documental: borra PDFs pendientes, PDFs procesados y resetea la base de datos.",
                classes="subtitle",
            )
            yield Static(
                "Conserva secretos locales y vuelve a crear la base vacía con usuarios semilla. "
                "Si la base SQLite está abierta por Streamlit, el reinicio puede fallar.",
                id="warning",
            )
            yield Static("", id="summary")
            yield Static("Escribe RESET para confirmar la operación.", id="confirm_text")
            yield Input(placeholder="RESET", id="confirm_input")
            with Horizontal(id="actions"):
                yield Button("Cancelar", id="cancel", variant="default")
                yield Button("Ejecutar reset documental", id="confirm", variant="error")
                yield Button("Salir", id="exit_after", variant="primary", disabled=True)
            yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#confirm_input", Input).focus()
        self._render_summary()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "cancel":
            self.exit()
            return
        if button_id == "exit_after":
            self.exit()
            return
        if button_id == "confirm":
            self._run_reset()

    def _render_summary(self) -> None:
        summary = self.query_one("#summary", Static)
        try:
            context = inspect_reset_context()
        except Exception as exc:
            summary.update(f"No fue posible preparar el reset documental:\n{exc}")
            return

        summary.update(
            "Resumen previo\n"
            f"- Base de datos: {context['db_path']}\n"
            f"- PDFs en data/por_procesar: {context['por_procesar']}\n"
            f"- PDFs ya procesados: {context['processed_pdfs']}\n"
            f"- Total de PDFs a eliminar: {context['total_pdf_files']}\n"
            f"- Documentos registrados en la base: {context['documents_in_db']}"
        )

    def _run_reset(self) -> None:
        confirmation = self.query_one("#confirm_input", Input).value.strip()
        status = self.query_one("#status", Static)
        if confirmation != "RESET":
            status.update("Confirmación inválida. Debes escribir exactamente RESET.")
            return

        try:
            stats = reset_documents()
        except Exception as exc:
            status.update(f"No fue posible completar el reset documental: {exc}")
            return

        self.query_one("#confirm", Button).disabled = True
        self.query_one("#cancel", Button).disabled = True
        self.query_one("#confirm_input", Input).disabled = True
        self.query_one("#exit_after", Button).disabled = False
        self._render_summary()
        status.update(
            "Reset documental completado.\n"
            f"Archivos eliminados: {stats['deleted_files']}\n"
            f"Directorios vaciados: {stats['deleted_directories']}\n"
            f"Documentos después del reset: {stats['documents_after_reset']}\n"
            f"Usuarios semilla resembrados: {stats['seed_users']}\n"
            "El sistema quedó sin documentos procesados. Puedes salir con el botón 'Salir'."
        )


if __name__ == "__main__":
    RefreshDocumentsApp().run()
