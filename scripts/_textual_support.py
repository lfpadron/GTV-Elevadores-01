"""Shared helpers for Textual-based maintenance scripts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import sqlite3
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from gtv.config import (
    get_settings,
    get_local_settings,
    load_local_secrets_data,
    secrets_example_path,
    write_local_secrets_data,
)
from gtv.db.init_db import initialize_database

RESET_DATA_FOLDERS = [
    "reportes",
    "hallazgos",
    "estimaciones",
    "no_reconocidos",
    "duplicados",
    "exportes",
    "por_procesar",
]


@dataclass(slots=True)
class SeedUserInput:
    email: str
    full_name: str
    preferred_name: str


def reset_seed_and_smtp_secrets() -> None:
    data = load_local_secrets_data()
    data["seed_users"] = {}
    data["gmail"] = {}
    write_local_secrets_data(data)
    get_settings.cache_clear()
    get_local_settings.cache_clear()


def write_seed_secrets(seed_one: SeedUserInput, seed_two: SeedUserInput, app_password: str) -> None:
    data = load_local_secrets_data()
    app_section = data.get("app") or {
        "title": "Grand Tower del Valle - Analizador Documental",
        "db_path": "data/grand_tower_v1.sqlite3",
        "base_url": "http://localhost:8501",
        "session_timeout_minutes": 30,
    }
    data["app"] = app_section
    data["seed_users"] = {
        "admin1": {
            "full_name": seed_one.full_name.strip(),
            "preferred_name": seed_one.preferred_name.strip(),
            "email": seed_one.email.strip().lower(),
        },
        "admin2": {
            "full_name": seed_two.full_name.strip(),
            "preferred_name": seed_two.preferred_name.strip(),
            "email": seed_two.email.strip().lower(),
        },
    }
    data["gmail"] = {
        "sender_email": seed_one.email.strip().lower(),
        "app_password": app_password.strip().replace(" ", ""),
        "smtp_server": "smtp.gmail.com",
        "smtp_port": 587,
        "use_tls": True,
    }
    write_local_secrets_data(data)
    get_settings.cache_clear()
    get_local_settings.cache_clear()


def reseed_database() -> Path:
    settings = get_local_settings()
    initialize_database(settings)
    return settings.db_path


def collect_reset_targets() -> tuple[Path | None, list[Path]]:
    get_settings.cache_clear()
    get_local_settings.cache_clear()
    settings = get_local_settings(validate_secrets=False)
    db_path = settings.db_path
    data_roots = [settings.data_dir / folder for folder in RESET_DATA_FOLDERS]
    return db_path, data_roots


def execute_full_reset() -> dict[str, int | str]:
    db_path, data_roots = collect_reset_targets()
    deleted_files = 0
    deleted_directories = 0

    for root in data_roots:
        root.mkdir(parents=True, exist_ok=True)
        for child in sorted(root.iterdir(), key=lambda path: (path.is_file(), str(path).lower()), reverse=True):
            if child.is_file():
                child.unlink(missing_ok=True)
                deleted_files += 1
            elif child.is_dir():
                removed_files, removed_dirs = _delete_tree(child)
                deleted_files += removed_files
                deleted_directories += removed_dirs

    if db_path and db_path.exists():
        try:
            db_path.unlink()
            deleted_files += 1
        except PermissionError as exc:
            raise RuntimeError(
                f"No se pudo borrar la base de datos porque esta en uso: {db_path}"
            ) from exc

    reset_seed_and_smtp_secrets()

    return {
        "deleted_files": deleted_files,
        "deleted_directories": deleted_directories,
        "db_path": str(db_path) if db_path else "",
    }


def ensure_secrets_example_available() -> None:
    example_path = secrets_example_path()
    example_path.parent.mkdir(parents=True, exist_ok=True)
    if not example_path.exists():
        example_path.write_text("", encoding="utf-8")


def copy_secrets_example_to_local() -> None:
    example_path = secrets_example_path()
    if not example_path.exists():
        return
    target_path = example_path.with_name("secrets.toml")
    if not target_path.exists():
        shutil.copy2(example_path, target_path)


def _delete_tree(root: Path) -> tuple[int, int]:
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
    try:
        root.rmdir()
        deleted_directories += 1
    except OSError:
        pass
    return deleted_files, deleted_directories


def fetch_seed_users_snapshot(db_path: Path | None = None) -> list[dict[str, str]]:
    get_settings.cache_clear()
    get_local_settings.cache_clear()
    settings = get_local_settings(validate_secrets=False)
    target_db = db_path or settings.db_path
    if not target_db.exists():
        return []
    with sqlite3.connect(target_db) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT email, full_name, preferred_name, role, status
            FROM users
            WHERE is_seed = 1
            ORDER BY id
            """
        ).fetchall()
    return [dict(row) for row in rows]
