"""Database initialization and seed helpers."""

from __future__ import annotations

from pathlib import Path

from gtv.config import Settings, ensure_app_directories, get_settings
from gtv.constants import POSITION_DEFAULTS
from gtv.db.connection import get_connection
from gtv.utils.equipment import default_catalog_seed_rows, normalize_alias_text


def _load_schema() -> str:
    schema_path = Path(__file__).resolve().with_name("schema.sql")
    return schema_path.read_text(encoding="utf-8")


def initialize_database(settings: Settings | None = None) -> None:
    active_settings = settings or get_settings()
    ensure_app_directories(active_settings)
    with get_connection(active_settings) as connection:
        _run_pre_schema_migrations(connection)
        connection.executescript(_load_schema())
        _run_safe_migrations(connection)
        _seed_positions(connection)
        _seed_equipment_catalog(connection)
        _seed_settings(connection, active_settings)
        _seed_admins(connection, active_settings)
        connection.commit()


def _table_exists(connection, table_name: str) -> bool:
    row = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return bool(row)


def _column_exists(connection, table_name: str, column_name: str) -> bool:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(row["name"] == column_name for row in rows)


def _run_pre_schema_migrations(connection) -> None:
    if _table_exists(connection, "documents") and not _column_exists(connection, "documents", "equipment_code"):
        connection.execute(
            "ALTER TABLE documents ADD COLUMN equipment_code TEXT"
        )
    if _table_exists(connection, "documents") and not _column_exists(connection, "documents", "inclusion_status"):
        connection.execute(
            "ALTER TABLE documents ADD COLUMN inclusion_status TEXT NOT NULL DEFAULT 'incluido'"
        )
        connection.execute(
            """
            UPDATE documents
            SET inclusion_status = CASE
                WHEN COALESCE(duplicate_status, 'original') <> 'original'
                     OR COALESCE(document_status, 'activo') = 'descartado'
                THEN 'ignorado'
                ELSE 'incluido'
            END
            """
        )
    if _table_exists(connection, "estimates") and not _column_exists(connection, "estimates", "report_reference_text"):
        connection.execute("ALTER TABLE estimates ADD COLUMN report_reference_text TEXT")
    if _table_exists(connection, "estimates") and not _column_exists(connection, "estimates", "finding_reference_text"):
        connection.execute("ALTER TABLE estimates ADD COLUMN finding_reference_text TEXT")
    if _table_exists(connection, "estimates") and not _column_exists(connection, "estimates", "missing_supporting_reference"):
        connection.execute("ALTER TABLE estimates ADD COLUMN missing_supporting_reference INTEGER NOT NULL DEFAULT 0")
    if _table_exists(connection, "estimate_items") and not _column_exists(connection, "estimate_items", "equipment_text_original"):
        connection.execute("ALTER TABLE estimate_items ADD COLUMN equipment_text_original TEXT")
    if _table_exists(connection, "estimate_items") and not _column_exists(connection, "estimate_items", "equipment_code"):
        connection.execute("ALTER TABLE estimate_items ADD COLUMN equipment_code TEXT")
    if _table_exists(connection, "estimate_items") and not _column_exists(connection, "estimate_items", "report_reference_text"):
        connection.execute("ALTER TABLE estimate_items ADD COLUMN report_reference_text TEXT")
    if _table_exists(connection, "estimate_items") and not _column_exists(connection, "estimate_items", "finding_reference_text"):
        connection.execute("ALTER TABLE estimate_items ADD COLUMN finding_reference_text TEXT")
    if _table_exists(connection, "estimate_items") and not _column_exists(connection, "estimate_items", "report_document_id"):
        connection.execute("ALTER TABLE estimate_items ADD COLUMN report_document_id INTEGER")
    if _table_exists(connection, "estimate_items") and not _column_exists(connection, "estimate_items", "finding_document_id"):
        connection.execute("ALTER TABLE estimate_items ADD COLUMN finding_document_id INTEGER")
    if _table_exists(connection, "estimate_items") and not _column_exists(connection, "estimate_items", "user_ticket_id"):
        connection.execute("ALTER TABLE estimate_items ADD COLUMN user_ticket_id INTEGER")
    if _table_exists(connection, "estimate_items") and not _column_exists(connection, "estimate_items", "delivery_days"):
        connection.execute("ALTER TABLE estimate_items ADD COLUMN delivery_days INTEGER")
    if _table_exists(connection, "estimate_items") and not _column_exists(connection, "estimate_items", "estimated_delivery_date"):
        connection.execute("ALTER TABLE estimate_items ADD COLUMN estimated_delivery_date TEXT")
    if _table_exists(connection, "estimate_items") and not _column_exists(connection, "estimate_items", "missing_catalog_equipment"):
        connection.execute("ALTER TABLE estimate_items ADD COLUMN missing_catalog_equipment INTEGER NOT NULL DEFAULT 0")
    if _table_exists(connection, "estimate_items") and not _column_exists(connection, "estimate_items", "missing_supporting_reference"):
        connection.execute("ALTER TABLE estimate_items ADD COLUMN missing_supporting_reference INTEGER NOT NULL DEFAULT 0")


def _run_safe_migrations(connection) -> None:
    if not _column_exists(connection, "users", "preferred_name"):
        connection.execute(
            "ALTER TABLE users ADD COLUMN preferred_name TEXT NOT NULL DEFAULT ''"
        )
        connection.execute(
            """
            UPDATE users
            SET preferred_name = CASE
                WHEN trim(full_name) = '' THEN email
                ELSE substr(full_name, 1, instr(full_name || ' ', ' ') - 1)
            END
            WHERE coalesce(preferred_name, '') = ''
            """
        )
    if not _column_exists(connection, "access_requests", "requested_preferred_name"):
        connection.execute(
            "ALTER TABLE access_requests ADD COLUMN requested_preferred_name TEXT"
        )
    if _table_exists(connection, "documents") and not _column_exists(connection, "documents", "equipment_code"):
        connection.execute(
            "ALTER TABLE documents ADD COLUMN equipment_code TEXT"
        )
    if _table_exists(connection, "documents") and not _column_exists(connection, "documents", "inclusion_status"):
        connection.execute(
            "ALTER TABLE documents ADD COLUMN inclusion_status TEXT NOT NULL DEFAULT 'incluido'"
        )
        connection.execute(
            """
            UPDATE documents
            SET inclusion_status = CASE
                WHEN COALESCE(duplicate_status, 'original') <> 'original'
                     OR COALESCE(document_status, 'activo') = 'descartado'
                THEN 'ignorado'
                ELSE 'incluido'
            END
            """
        )
    if _table_exists(connection, "estimates") and not _column_exists(connection, "estimates", "report_reference_text"):
        connection.execute("ALTER TABLE estimates ADD COLUMN report_reference_text TEXT")
    if _table_exists(connection, "estimates") and not _column_exists(connection, "estimates", "finding_reference_text"):
        connection.execute("ALTER TABLE estimates ADD COLUMN finding_reference_text TEXT")
    if _table_exists(connection, "estimates") and not _column_exists(connection, "estimates", "missing_supporting_reference"):
        connection.execute("ALTER TABLE estimates ADD COLUMN missing_supporting_reference INTEGER NOT NULL DEFAULT 0")
    if _table_exists(connection, "estimate_items") and not _column_exists(connection, "estimate_items", "equipment_text_original"):
        connection.execute("ALTER TABLE estimate_items ADD COLUMN equipment_text_original TEXT")
    if _table_exists(connection, "estimate_items") and not _column_exists(connection, "estimate_items", "equipment_code"):
        connection.execute("ALTER TABLE estimate_items ADD COLUMN equipment_code TEXT")
    if _table_exists(connection, "estimate_items") and not _column_exists(connection, "estimate_items", "report_reference_text"):
        connection.execute("ALTER TABLE estimate_items ADD COLUMN report_reference_text TEXT")
    if _table_exists(connection, "estimate_items") and not _column_exists(connection, "estimate_items", "finding_reference_text"):
        connection.execute("ALTER TABLE estimate_items ADD COLUMN finding_reference_text TEXT")
    if _table_exists(connection, "estimate_items") and not _column_exists(connection, "estimate_items", "report_document_id"):
        connection.execute("ALTER TABLE estimate_items ADD COLUMN report_document_id INTEGER")
    if _table_exists(connection, "estimate_items") and not _column_exists(connection, "estimate_items", "finding_document_id"):
        connection.execute("ALTER TABLE estimate_items ADD COLUMN finding_document_id INTEGER")
    if _table_exists(connection, "estimate_items") and not _column_exists(connection, "estimate_items", "user_ticket_id"):
        connection.execute("ALTER TABLE estimate_items ADD COLUMN user_ticket_id INTEGER")
    if _table_exists(connection, "estimate_items") and not _column_exists(connection, "estimate_items", "delivery_days"):
        connection.execute("ALTER TABLE estimate_items ADD COLUMN delivery_days INTEGER")
    if _table_exists(connection, "estimate_items") and not _column_exists(connection, "estimate_items", "estimated_delivery_date"):
        connection.execute("ALTER TABLE estimate_items ADD COLUMN estimated_delivery_date TEXT")
    if _table_exists(connection, "estimate_items") and not _column_exists(connection, "estimate_items", "missing_catalog_equipment"):
        connection.execute("ALTER TABLE estimate_items ADD COLUMN missing_catalog_equipment INTEGER NOT NULL DEFAULT 0")
    if _table_exists(connection, "estimate_items") and not _column_exists(connection, "estimate_items", "missing_supporting_reference"):
        connection.execute("ALTER TABLE estimate_items ADD COLUMN missing_supporting_reference INTEGER NOT NULL DEFAULT 0")


def _seed_positions(connection) -> None:
    for name in POSITION_DEFAULTS:
        connection.execute(
            """
            INSERT INTO positions (name)
            VALUES (?)
            ON CONFLICT(name) DO NOTHING
            """,
            (name,),
        )


def _seed_equipment_catalog(connection) -> None:
    if not _table_exists(connection, "equipment_catalog"):
        return
    for row in default_catalog_seed_rows():
        connection.execute(
            """
            INSERT INTO equipment_catalog (
                equipment_code,
                tower,
                position_name,
                display_name,
                is_active
            )
            VALUES (?, ?, ?, ?, 1)
            ON CONFLICT(equipment_code) DO UPDATE SET
                tower = excluded.tower,
                position_name = COALESCE(equipment_catalog.position_name, excluded.position_name),
                display_name = COALESCE(equipment_catalog.display_name, excluded.display_name),
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                row["equipment_code"],
                row["tower"],
                row["position_name"],
                row["display_name"],
            ),
        )
        for alias in row.get("aliases", []):
            connection.execute(
                """
                INSERT INTO equipment_aliases (
                    alias_text,
                    normalized_alias,
                    equipment_code,
                    source
                )
                VALUES (?, ?, ?, 'seed')
                ON CONFLICT(normalized_alias) DO UPDATE SET
                    equipment_code = excluded.equipment_code,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    alias,
                    normalize_alias_text(alias),
                    row["equipment_code"],
                ),
            )


def _seed_settings(connection, settings: Settings) -> None:
    row = connection.execute(
        """
        SELECT setting_value
        FROM app_settings
        WHERE setting_key = 'session_timeout_minutes'
        """
    ).fetchone()
    if not row:
        connection.execute(
            """
            INSERT INTO app_settings (setting_key, setting_value)
            VALUES ('session_timeout_minutes', ?)
            """,
            (str(settings.session_timeout_minutes),),
        )
        return

    if str(row["setting_value"]).strip() == "15":
        connection.execute(
            """
            UPDATE app_settings
            SET setting_value = '30',
                updated_at = CURRENT_TIMESTAMP
            WHERE setting_key = 'session_timeout_minutes'
            """
        )


def _seed_admins(connection, settings: Settings) -> None:
    for admin in settings.seed_admins:
        connection.execute(
            """
            INSERT INTO users (
                email,
                full_name,
                preferred_name,
                role,
                status,
                is_seed,
                approved_at
            )
            VALUES (?, ?, ?, 'semilla_admin', 'activo', 1, CURRENT_TIMESTAMP)
            ON CONFLICT(email) DO UPDATE SET
                full_name = excluded.full_name,
                preferred_name = excluded.preferred_name,
                role = 'semilla_admin',
                status = CASE
                    WHEN users.status = 'deshabilitado' THEN users.status
                    ELSE 'activo'
                END,
                is_seed = 1,
                updated_at = CURRENT_TIMESTAMP
            """,
            (admin.email.lower(), admin.full_name, admin.preferred_name),
        )
