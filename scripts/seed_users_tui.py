"""Textual TUI to reseed the two seed administrators."""

from __future__ import annotations

from pathlib import Path
import re
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Header, Input, Label, Static

from gtv.config import SecretsConfigurationError, render_secret_error
from scripts._textual_support import (
    SeedUserInput,
    fetch_seed_users_snapshot,
    reseed_database,
    write_seed_secrets,
)

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SeedUsersApp(App[None]):
    """Three-step wizard to reseed seed users and Gmail credentials."""

    CSS = """
    Screen {
        align: center middle;
    }

    #root {
        width: 96;
        max-width: 110;
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

    .field-label {
        margin-top: 1;
    }

    .page {
        height: auto;
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

    Input {
        margin-bottom: 1;
    }
    """

    BINDINGS = [("ctrl+c", "quit", "Salir")]

    def __init__(self) -> None:
        super().__init__()
        self.current_step = 1
        self.completed = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="root"):
            yield Static("Resiembra de Usuarios", classes="title")
            yield Static("", id="step_title", classes="subtitle")

            yield Vertical(
                Label("Correo del usuario 1", classes="field-label"),
                Input(id="seed1_email", placeholder="usuario1@gmail.com"),
                Label("Nombre completo del usuario 1", classes="field-label"),
                Input(id="seed1_name", placeholder="Nombre completo"),
                Label("Nombre preferido del usuario 1", classes="field-label"),
                Input(id="seed1_preferred", placeholder="Nombre corto visible en la app"),
                id="page_user_1",
                classes="page",
            )

            yield Vertical(
                Label("Correo del usuario 2", classes="field-label"),
                Input(id="seed2_email", placeholder="usuario2@gmail.com"),
                Label("Nombre completo del usuario 2", classes="field-label"),
                Input(id="seed2_name", placeholder="Nombre completo"),
                Label("Nombre preferido del usuario 2", classes="field-label"),
                Input(id="seed2_preferred", placeholder="Nombre corto visible en la app"),
                id="page_user_2",
                classes="page",
            )

            yield Vertical(
                Label("App Password de Gmail", classes="field-label"),
                Input(id="smtp_password", placeholder="16 caracteres", password=True),
                id="page_password",
                classes="page",
            )

            with Horizontal(id="actions"):
                yield Button("Cancelar / Salir", id="cancel", variant="default")
                yield Button("Siguiente", id="next", variant="primary")

            yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self._render_step()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.exit()
            return

        if event.button.id == "next":
            self._handle_next()

    def _handle_next(self) -> None:
        status = self.query_one("#status", Static)
        status.update("")

        try:
            if self.current_step == 1:
                self._validate_user_one()
                self.current_step = 2
                self._render_step()
                return

            if self.current_step == 2:
                self._validate_user_two()
                self.current_step = 3
                self._render_step()
                return

            self._save_and_seed()
        except ValueError as exc:
            status.update(str(exc))

    def _render_step(self) -> None:
        page_user_1 = self.query_one("#page_user_1", Vertical)
        page_user_2 = self.query_one("#page_user_2", Vertical)
        page_password = self.query_one("#page_password", Vertical)
        step_title = self.query_one("#step_title", Static)
        next_button = self.query_one("#next", Button)

        page_user_1.display = self.current_step == 1
        page_user_2.display = self.current_step == 2
        page_password.display = self.current_step == 3

        if self.current_step == 1:
            step_title.update(
                "Pantalla 1 de 3: captura correo, nombre completo y nombre preferido del usuario 1."
            )
            next_button.label = "Siguiente"
            self.query_one("#seed1_email", Input).focus()
            return

        if self.current_step == 2:
            step_title.update(
                "Pantalla 2 de 3: captura correo, nombre completo y nombre preferido del usuario 2."
            )
            next_button.label = "Siguiente"
            self.query_one("#seed2_email", Input).focus()
            return

        step_title.update("Pantalla 3 de 3: captura el App Password de Gmail.")
        next_button.label = "Guardar y sembrar"
        self.query_one("#smtp_password", Input).focus()

    def _save_and_seed(self) -> None:
        status = self.query_one("#status", Static)
        seed_one, seed_two = self._build_seed_inputs()
        app_password = self._read_app_password()

        try:
            write_seed_secrets(seed_one, seed_two, app_password)
            db_path = reseed_database()
            seeded_users = fetch_seed_users_snapshot(db_path)
        except SecretsConfigurationError as exc:
            status.update(render_secret_error(exc))
            return
        except Exception as exc:
            status.update(f"No fue posible completar la resiembra: {exc}")
            return

        self.completed = True
        self._lock_form()

        lines = [
            f"- {row['email']} | {row['full_name']} | {row['preferred_name']}"
            for row in seeded_users
        ]
        summary = "\n".join(lines) if lines else "- No se encontraron usuarios semilla en la base."
        status.update(
            "Resiembra completada correctamente.\n"
            f"Base actualizada en: {db_path}\n"
            "Secrets locales guardados en .streamlit/secrets.toml\n"
            "Usuarios semilla activos:\n"
            f"{summary}"
        )

    def _lock_form(self) -> None:
        for input_id in (
            "#seed1_email",
            "#seed1_name",
            "#seed1_preferred",
            "#seed2_email",
            "#seed2_name",
            "#seed2_preferred",
            "#smtp_password",
        ):
            self.query_one(input_id, Input).disabled = True

        next_button = self.query_one("#next", Button)
        next_button.disabled = True

    def _build_seed_inputs(self) -> tuple[SeedUserInput, SeedUserInput]:
        seed_one = SeedUserInput(
            email=self.query_one("#seed1_email", Input).value.strip().lower(),
            full_name=self.query_one("#seed1_name", Input).value.strip(),
            preferred_name=self.query_one("#seed1_preferred", Input).value.strip(),
        )
        seed_two = SeedUserInput(
            email=self.query_one("#seed2_email", Input).value.strip().lower(),
            full_name=self.query_one("#seed2_name", Input).value.strip(),
            preferred_name=self.query_one("#seed2_preferred", Input).value.strip(),
        )
        return seed_one, seed_two

    def _read_app_password(self) -> str:
        app_password = self.query_one("#smtp_password", Input).value.strip().replace(" ", "")
        if len(app_password) < 16:
            raise ValueError("El App Password parece incompleto.")
        return app_password

    def _validate_user_one(self) -> None:
        seed_one, _ = self._build_seed_inputs()
        self._validate_seed_user(seed_one, user_number=1)

    def _validate_user_two(self) -> None:
        seed_one, seed_two = self._build_seed_inputs()
        self._validate_seed_user(seed_two, user_number=2)
        if seed_one.email and seed_two.email and seed_one.email == seed_two.email:
            raise ValueError("Los usuarios 1 y 2 deben tener correos distintos.")

    def _validate_seed_user(self, seed: SeedUserInput, user_number: int) -> None:
        if not EMAIL_REGEX.fullmatch(seed.email):
            raise ValueError(f"El correo del usuario {user_number} no es valido.")
        if not seed.full_name:
            raise ValueError(f"Falta el nombre completo del usuario {user_number}.")
        if not seed.preferred_name:
            raise ValueError(f"Falta el nombre preferido del usuario {user_number}.")


if __name__ == "__main__":
    SeedUsersApp().run()
