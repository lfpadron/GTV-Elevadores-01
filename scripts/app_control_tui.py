"""Textual TUI to manage the local Streamlit application."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.error import URLError
from urllib.request import urlopen
import webbrowser

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Header, Static

STREAMLIT_PORT = 8501
STREAMLIT_URL = f"http://localhost:{STREAMLIT_PORT}"


@dataclass(slots=True)
class AppStatus:
    state_label: str
    is_running: bool
    pids: list[int]
    http_ok: bool
    detail: str


def _powershell(command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _find_streamlit_processes() -> list[int]:
    command = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.Name -like 'python*' -and $_.CommandLine -like '*streamlit run*app.py*' } | "
        "Select-Object -ExpandProperty ProcessId | ConvertTo-Json -Compress"
    )
    result = _powershell(command)
    output = (result.stdout or "").strip()
    if result.returncode != 0 or not output:
        return []
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return []
    if isinstance(data, int):
        return [data]
    if isinstance(data, list):
        return [int(item) for item in data]
    return []


def _http_ready() -> bool:
    try:
        with urlopen(STREAMLIT_URL, timeout=2) as response:
            return response.status == 200
    except (URLError, TimeoutError, OSError):
        return False


def get_app_status() -> AppStatus:
    pids = _find_streamlit_processes()
    http_ok = _http_ready()
    if pids and http_ok:
        return AppStatus(
            state_label="En ejecución",
            is_running=True,
            pids=pids,
            http_ok=True,
            detail=f"URL activa en {STREAMLIT_URL}. PID(s): {', '.join(str(pid) for pid in pids)}",
        )
    if pids and not http_ok:
        return AppStatus(
            state_label="Iniciando / sin respuesta HTTP",
            is_running=True,
            pids=pids,
            http_ok=False,
            detail=f"Proceso detectado, pero la URL aún no responde. PID(s): {', '.join(str(pid) for pid in pids)}",
        )
    return AppStatus(
        state_label="Detenida",
        is_running=False,
        pids=[],
        http_ok=False,
        detail="No se detectó proceso activo de Streamlit para app.py.",
    )


def start_app() -> str:
    if _find_streamlit_processes():
        return "La aplicación ya está en ejecución."
    creation_flags = 0
    if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        creation_flags |= subprocess.CREATE_NEW_PROCESS_GROUP
    if hasattr(subprocess, "DETACHED_PROCESS"):
        creation_flags |= subprocess.DETACHED_PROCESS
    subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(PROJECT_ROOT / "app.py"),
            "--server.headless",
            "true",
            "--server.port",
            str(STREAMLIT_PORT),
        ],
        cwd=PROJECT_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        creationflags=creation_flags,
    )
    return "Solicitud de arranque enviada. Espera unos segundos y el estado se actualizará."


def stop_app() -> str:
    pids = _find_streamlit_processes()
    if not pids:
        return "La aplicación ya está detenida."
    command = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.Name -like 'python*' -and $_.CommandLine -like '*streamlit run*app.py*' } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
    )
    result = _powershell(command)
    if result.returncode != 0:
        error_text = (result.stderr or result.stdout or "").strip()
        return f"No fue posible detener la aplicación: {error_text or 'error desconocido'}"
    return f"Aplicación detenida. PID(s) cerrados: {', '.join(str(pid) for pid in pids)}"


def open_app_in_browser() -> str:
    try:
        if hasattr(os, "startfile"):
            os.startfile(STREAMLIT_URL)
        else:
            webbrowser.open(STREAMLIT_URL, new=2)
        return f"Abriendo navegador en {STREAMLIT_URL}"
    except OSError as exc:
        return f"No fue posible abrir el navegador: {exc}"


class AppControlTUI(App[None]):
    """TUI to view, start and stop the Streamlit app."""

    CSS = """
    Screen {
        align: center middle;
    }

    #root {
        width: 94;
        max-width: 108;
        height: auto;
        border: round $primary;
        padding: 1 2;
        background: $surface;
    }

    .title {
        text-style: bold;
        margin-bottom: 1;
    }

    .muted {
        color: $text-muted;
        margin-bottom: 1;
    }

    #status_box {
        height: auto;
        min-height: 6;
        border: round $panel;
        padding: 1;
        margin-top: 1;
    }

    #message_box {
        height: auto;
        min-height: 4;
        margin-top: 1;
    }

    #actions {
        height: auto;
        margin-top: 1;
    }

    Button {
        width: 1fr;
    }
    """

    BINDINGS = [("ctrl+c", "quit", "Salir"), ("r", "manual_refresh", "Actualizar")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="root"):
            yield Static("Control Local de la Aplicación", classes="title")
            yield Static(
                "Monitorea el estado de Streamlit y controla arranque/detención de la app local.",
                classes="muted",
            )
            yield Static("", id="status_box")
            with Horizontal(id="actions"):
                yield Button("Arrancar", id="start", variant="success")
                yield Button("Detener", id="stop", variant="warning")
                yield Button("Refrescar", id="refresh", variant="default")
                yield Button("Abrir navegador", id="open_browser", variant="primary")
                yield Button("Salir", id="exit", variant="primary")
            yield Static("", id="message_box")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_status()
        self.set_interval(2.0, self._refresh_status)

    def action_manual_refresh(self) -> None:
        self._refresh_status()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "exit":
            self.exit()
            return
        if event.button.id == "start":
            self.query_one("#message_box", Static).update(start_app())
            self._refresh_status()
            return
        if event.button.id == "stop":
            self.query_one("#message_box", Static).update(stop_app())
            self._refresh_status()
            return
        if event.button.id == "refresh":
            self.query_one("#message_box", Static).update("Estado actualizado.")
            self._refresh_status()
            return
        if event.button.id == "open_browser":
            self.query_one("#message_box", Static).update(open_app_in_browser())

    def _refresh_status(self) -> None:
        status = get_app_status()
        self.query_one("#status_box", Static).update(
            "\n".join(
                [
                    f"Estado: {status.state_label}",
                    f"URL: {STREAMLIT_URL}",
                    f"HTTP activo: {'Sí' if status.http_ok else 'No'}",
                    status.detail,
                ]
            )
        )
        self.query_one("#start", Button).disabled = status.is_running
        self.query_one("#stop", Button).disabled = not status.is_running


if __name__ == "__main__":
    AppControlTUI().run()
