"""Textual TUI to reset operational data and seed configuration."""

from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Header, Input, Label, Static

from scripts._textual_support import execute_full_reset


class ResetSystemApp(App[None]):
    """Interactive reset utility."""

    CSS = """
    Screen {
        align: center middle;
    }

    #root {
        width: 88;
        max-width: 96;
        border: round $primary;
        padding: 1 2;
        background: $surface;
    }

    #title {
        text-style: bold;
        margin-bottom: 1;
    }

    #warning {
        color: $warning;
        margin-bottom: 1;
    }

    #status {
        min-height: 3;
        margin-top: 1;
    }

    Input {
        margin-top: 1;
        margin-bottom: 1;
    }

    Button {
        width: 1fr;
    }
    """

    BINDINGS = [("ctrl+c", "quit", "Salir")]

    def compose(self) -> ComposeResult:
        with Vertical(id="root"):
            yield Header(show_clock=True)
            yield Static("Puesta Cero Operativa", id="title")
            yield Static(
                "Esto borrara la base SQLite, documentos procesados, duplicados, exportes, "
                "pendientes en por_procesar y limpiara semillas/credenciales Gmail del archivo Streamlit secrets local.",
            )
            yield Static("Escribe RESET para confirmar la puesta cero.", id="warning")
            yield Input(placeholder="RESET", id="confirm_input")
            with Horizontal():
                yield Button("Cancelar", id="cancel", variant="default")
                yield Button("Ejecutar puesta cero", id="confirm", variant="error")
                yield Button("Salir", id="exit_after", variant="primary", disabled=True)
            yield Static("", id="status")
            yield Footer()

    def on_mount(self) -> None:
        self.query_one("#confirm_input", Input).focus()

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

    def _run_reset(self) -> None:
        confirmation = self.query_one("#confirm_input", Input).value.strip()
        status = self.query_one("#status", Static)
        if confirmation != "RESET":
            status.update("Confirmacion invalida. Debes escribir exactamente RESET.")
            return
        try:
            result = execute_full_reset()
        except Exception as exc:
            status.update(f"Fallo la puesta cero: {exc}")
            return
        self.query_one("#confirm", Button).disabled = True
        self.query_one("#cancel", Button).disabled = True
        self.query_one("#confirm_input", Input).disabled = True
        self.query_one("#exit_after", Button).disabled = False
        status.update(
            "Puesta cero completada.\n"
            f"Archivos borrados: {result['deleted_files']} | "
            f"Directorios borrados: {result['deleted_directories']}\n"
            "Semillas y credenciales Gmail removidas de .streamlit/secrets.toml.\n"
            "Puedes salir con el boton 'Salir'."
        )


if __name__ == "__main__":
    ResetSystemApp().run()
