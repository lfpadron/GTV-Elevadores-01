"""Application settings and Streamlit secrets helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import tomllib
from typing import Any

import streamlit as st

from gtv.constants import DOCUMENT_FOLDERS


@dataclass(slots=True)
class SeedAdmin:
    full_name: str
    preferred_name: str
    email: str


@dataclass(slots=True)
class Settings:
    base_dir: Path
    data_dir: Path
    db_path: Path
    app_title: str
    base_url: str
    session_timeout_minutes: int
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    smtp_from: str
    smtp_use_tls: bool
    seed_admins: list[SeedAdmin]
    secrets_source: str

    @property
    def smtp_enabled(self) -> bool:
        return all(
            [
                self.smtp_host,
                self.smtp_port,
                self.smtp_username,
                self.smtp_password,
                self.smtp_from,
            ]
        )


class SecretsConfigurationError(RuntimeError):
    """Raised when required Streamlit secrets are missing or invalid."""

    def __init__(self, issues: list[str], *, local_path: Path) -> None:
        self.issues = issues
        self.local_path = local_path
        super().__init__("Configuración de secretos incompleta o inválida.")

    @property
    def missing_keys(self) -> list[str]:
        return [issue.removeprefix("missing:") for issue in self.issues if issue.startswith("missing:")]

    def render_lines(self) -> list[str]:
        lines = ["Configuración de secretos incompleta o inválida."]
        for issue in self.issues:
            if issue.startswith("missing:"):
                key = issue.removeprefix("missing:")
                lines.append(f"- Falta la clave `{key}`")
            elif issue.startswith("invalid:"):
                detail = issue.removeprefix("invalid:")
                lines.append(f"- Valor inválido para `{detail}`")
            else:
                lines.append(f"- {issue}")
        lines.append(f"- Desarrollo local: crea `{self.local_path}` a partir del ejemplo versionado")
        lines.append("- Streamlit Community Cloud: carga las mismas claves en el panel Secrets")
        return lines


def project_base_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def local_secrets_path(base_dir: Path | None = None) -> Path:
    return (base_dir or project_base_dir()) / ".streamlit" / "secrets.toml"


def secrets_example_path(base_dir: Path | None = None) -> Path:
    return (base_dir or project_base_dir()) / ".streamlit" / "secrets.toml.example"


def load_local_secrets_data(base_dir: Path | None = None) -> dict[str, Any]:
    path = local_secrets_path(base_dir)
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        return tomllib.load(handle)


def write_local_secrets_data(data: Mapping[str, Any], *, base_dir: Path | None = None) -> Path:
    path = local_secrets_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_render_toml_document(_to_plain_mapping(data)), encoding="utf-8")
    return path


def render_secret_error(error: SecretsConfigurationError) -> str:
    return "\n".join(error.render_lines())


def ensure_app_directories(settings: Settings) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    for folder in DOCUMENT_FOLDERS.values():
        (settings.data_dir / folder).mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=2)
def get_settings(validate_secrets: bool = True) -> Settings:
    base_dir = project_base_dir()
    secrets_data, source_label = _load_secret_source(base_dir)
    return _build_settings_from_mapping(
        secrets_data,
        source_label=source_label,
        base_dir=base_dir,
        validate_secrets=validate_secrets,
    )


@lru_cache(maxsize=2)
def get_local_settings(validate_secrets: bool = True) -> Settings:
    base_dir = project_base_dir()
    secrets_data = load_local_secrets_data(base_dir)
    return _build_settings_from_mapping(
        secrets_data,
        source_label=".streamlit/secrets.toml",
        base_dir=base_dir,
        validate_secrets=validate_secrets,
    )


def _build_settings_from_mapping(
    secrets_data: Mapping[str, Any],
    *,
    source_label: str,
    base_dir: Path,
    validate_secrets: bool,
) -> Settings:
    issues: list[str] = []

    app_section = _mapping_value(secrets_data, "app")
    title = _string_or_default(_value_at(app_section, "title"), "Grand Tower del Valle - Analizador Documental")
    db_path_raw = _string_or_default(_value_at(app_section, "db_path"), "data/grand_tower_v1.sqlite3")
    base_url = _string_or_default(_value_at(app_section, "base_url"), "http://localhost:8501")
    session_timeout_minutes = _int_or_default(
        _value_at(app_section, "session_timeout_minutes"),
        default=30,
        issues=issues,
        issue_key="app.session_timeout_minutes",
    )

    seed_admins = _load_seed_admins(secrets_data, issues)
    gmail_config = _load_gmail_config(secrets_data, issues)

    if validate_secrets and issues:
        raise SecretsConfigurationError(issues, local_path=local_secrets_path(base_dir))

    return Settings(
        base_dir=base_dir,
        data_dir=base_dir / "data",
        db_path=base_dir / db_path_raw,
        app_title=title,
        base_url=base_url,
        session_timeout_minutes=session_timeout_minutes,
        smtp_host=gmail_config["smtp_host"],
        smtp_port=gmail_config["smtp_port"],
        smtp_username=gmail_config["smtp_username"],
        smtp_password=gmail_config["smtp_password"],
        smtp_from=gmail_config["smtp_from"],
        smtp_use_tls=gmail_config["smtp_use_tls"],
        seed_admins=seed_admins,
        secrets_source=source_label,
    )


def _load_secret_source(_base_dir: Path) -> tuple[dict[str, Any], str]:
    streamlit_data = _load_streamlit_secrets()
    if streamlit_data:
        return streamlit_data, "st.secrets"

    return {}, "missing"


def _load_streamlit_secrets() -> dict[str, Any]:
    try:
        if hasattr(st.secrets, "to_dict"):
            data = st.secrets.to_dict()
        else:
            data = dict(st.secrets)
        return _to_plain_mapping(data)
    except Exception:
        return {}


def _load_seed_admins(secrets_data: Mapping[str, Any], issues: list[str]) -> list[SeedAdmin]:
    seed_users = _mapping_value(secrets_data, "seed_users")
    admins: list[SeedAdmin] = []

    for admin_key in ("admin1", "admin2"):
        admin_section = _mapping_value(seed_users, admin_key)
        full_name = _string_or_none(_value_at(admin_section, "full_name")) or _string_or_none(_value_at(admin_section, "name"))
        preferred_name = _string_or_none(_value_at(admin_section, "preferred_name"))
        email = _normalize_email(_value_at(admin_section, "email"))

        if not full_name:
            issues.append(f"missing:seed_users.{admin_key}.full_name")
        if not preferred_name:
            issues.append(f"missing:seed_users.{admin_key}.preferred_name")
        if not email:
            issues.append(f"missing:seed_users.{admin_key}.email")

        if full_name and preferred_name and email:
            admins.append(
                SeedAdmin(
                    full_name=full_name,
                    preferred_name=preferred_name,
                    email=email,
                )
            )

    return admins


def _load_gmail_config(secrets_data: Mapping[str, Any], issues: list[str]) -> dict[str, Any]:
    gmail_section = _mapping_value(secrets_data, "gmail")

    sender_email = _normalize_email(_value_at(gmail_section, "sender_email"))
    app_password = _string_or_none(_value_at(gmail_section, "app_password"))
    smtp_server = _string_or_default(_value_at(gmail_section, "smtp_server"), "smtp.gmail.com")
    smtp_port = _int_or_default(_value_at(gmail_section, "smtp_port"), 587, issues, "gmail.smtp_port")
    use_tls = _bool_or_default(_value_at(gmail_section, "use_tls"), True)

    if not sender_email:
        issues.append("missing:gmail.sender_email")
    if not app_password:
        issues.append("missing:gmail.app_password")

    return {
        "smtp_host": smtp_server,
        "smtp_port": smtp_port,
        "smtp_username": sender_email or "",
        "smtp_password": app_password or "",
        "smtp_from": sender_email or "",
        "smtp_use_tls": use_tls,
    }


def _mapping_value(mapping: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = mapping.get(key, {})
    return value if isinstance(value, Mapping) else {}


def _value_at(mapping: Mapping[str, Any], key: str) -> Any:
    if not isinstance(mapping, Mapping):
        return None
    return mapping.get(key)


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _string_or_default(value: Any, default: str) -> str:
    return _string_or_none(value) or default


def _normalize_email(value: Any) -> str | None:
    email = _string_or_none(value)
    return email.lower() if email else None


def _bool_or_default(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _int_or_default(value: Any, default: int, issues: list[str], issue_key: str) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        issues.append(f"invalid:{issue_key}")
        return default


def _to_plain_mapping(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _to_plain_mapping(item) for key, item in value.items()}
    return value


def _render_toml_document(data: Mapping[str, Any]) -> str:
    lines: list[str] = []
    _append_toml_sections(lines, tuple(), data)
    return "\n".join(line for line in lines if line is not None).strip() + "\n"


def _append_toml_sections(lines: list[str], prefix: tuple[str, ...], mapping: Mapping[str, Any]) -> None:
    scalar_items = [(key, value) for key, value in mapping.items() if not isinstance(value, Mapping)]
    nested_items = [(key, value) for key, value in mapping.items() if isinstance(value, Mapping)]

    if prefix:
        lines.append(f"[{'.'.join(prefix)}]")
    for key, value in scalar_items:
        lines.append(f"{key} = {_toml_literal(value)}")
    if prefix or scalar_items:
        lines.append("")
    for key, value in nested_items:
        _append_toml_sections(lines, (*prefix, str(key)), value)


def _toml_literal(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if value is None:
        return '""'
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'
