"""Equipment catalog extraction, persistence-aware lookup and alias normalization helpers."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from gtv.utils.text import normalize_for_match, normalize_whitespace

EQUIPMENT_CODE_REGEX = re.compile(r"\b(\d{5}-MEX-ELE-BLT)\b", flags=re.IGNORECASE)
SHORT_CODE_REGEX = re.compile(r"\b(10\d{3})\b")
EQUIPMENT_OTHER_FILTER_VALUE = "__other__"
TOWER_FILTER_OPTIONS = ["A", "B", "C", "D", "E", "F"]
_POSITION_ORDER = {
    "izquierdo": 1,
    "derecho": 2,
    "servicio": 3,
    "carga": 4,
    "unico": 5,
}

DEFAULT_EQUIPMENT_CATALOG: dict[str, dict[str, object]] = {
    "10258-MEX-ELE-BLT": {
        "tower": "A",
        "position": "derecho",
        "display_name": "Torre A Elevador Derecho",
        "aliases": [
            "Torre A Elev (Derecho)",
            "Torre A Derecho",
            "Torre A Elev Derecho",
            "Elevador A Derecho",
        ],
    },
    "10261-MEX-ELE-BLT": {
        "tower": "B",
        "position": "izquierdo",
        "display_name": "Torre B Elevador Izquierdo",
        "aliases": [
            "Torre B Elev (Izquierdo)",
            "Torre B Izquierdo",
            "Torre B Elev Izquierdo",
            "Elevador B Izquierdo",
        ],
    },
    "10262-MEX-ELE-BLT": {
        "tower": "C",
        "position": "derecho",
        "display_name": "Torre C Elevador Derecho",
        "aliases": [
            "Torre C Elev (Derecho)",
            "Torre C Derecho",
            "Torre C Elev Derecho",
            "Elevador C Derecho",
        ],
    },
    "10263-MEX-ELE-BLT": {
        "tower": "C",
        "position": "izquierdo",
        "display_name": "Torre C Elevador Izquierdo",
        "aliases": [
            "Torre C Elev (Izquierdo)",
            "Torre C Izquierdo",
            "Torre C Elev Izquierdo",
            "Elevador C Izquierdo",
        ],
    },
    "10264-MEX-ELE-BLT": {
        "tower": "C",
        "position": "servicio",
        "display_name": "Torre C Elevador Servicio",
        "aliases": [
            "Torre C Elev Servicio",
            "Torre C Servicio",
            "Elevador C Servicio",
        ],
    },
    "10265-MEX-ELE-BLT": {
        "tower": "D",
        "position": "derecho",
        "display_name": "Torre D Elevador Derecho",
        "aliases": [
            "Torre D Elev (Derecho)",
            "Torre D Derecho",
            "Torre D Elev Derecho",
            "Elevador D Derecho",
            "Elevador D2",
        ],
    },
    "10268-MEX-ELE-BLT": {
        "tower": "E",
        "position": "izquierdo",
        "display_name": "Torre E Elevador Izquierdo",
        "aliases": [
            "Torre E Elev (Izquierdo)",
            "Torre E Izquierdo",
            "Torre E Elev Izquierdo",
            "Elevador E Izquierdo",
        ],
    },
    "10269-MEX-ELE-BLT": {
        "tower": "E",
        "position": "servicio",
        "display_name": "Torre E Elevador Servicio",
        "aliases": [
            "Torre E Elev Servicio",
            "Torre E Servicio",
            "Elevador E Servicio",
        ],
    },
}


def extract_equipment_code(text: str | None) -> str | None:
    if not text:
        return None
    match = EQUIPMENT_CODE_REGEX.search(text)
    return match.group(1).upper() if match else None


def normalize_alias_text(text: str | None) -> str:
    return normalize_for_match(text)


def default_catalog_seed_rows() -> list[dict]:
    rows: list[dict] = []
    for code, metadata in DEFAULT_EQUIPMENT_CATALOG.items():
        rows.append(
            {
                "equipment_code": code,
                "tower": str(metadata.get("tower") or "").upper(),
                "position_name": str(metadata.get("position") or "").lower() or None,
                "display_name": str(metadata.get("display_name") or _fallback_display_name(code, metadata)),
                "aliases": [normalize_whitespace(alias) for alias in metadata.get("aliases", []) if alias],
            }
        )
    return rows


def resolve_equipment_code_alias(user_text: str | None) -> str | None:
    if not user_text:
        return None

    direct_code = extract_equipment_code(user_text)
    if direct_code:
        return direct_code

    normalized = normalize_for_match(user_text)
    if not normalized:
        return None

    short_match = SHORT_CODE_REGEX.search(normalized)
    if short_match:
        short_code = short_match.group(1)
        for code in catalog_equipment_codes():
            if code.startswith(short_code):
                return code

    best_match: tuple[int, str] | None = None
    for code, metadata in _load_catalog().items():
        aliases = _catalog_aliases(code, metadata)
        for alias in aliases:
            normalized_alias = normalize_for_match(alias)
            if normalized == normalized_alias or normalized in normalized_alias or normalized_alias in normalized:
                score = len(normalized_alias)
                if not best_match or score > best_match[0]:
                    best_match = (score, code)
    return best_match[1] if best_match else None


def infer_equipment_code(
    *,
    raw_text: str | None = None,
    file_name: str | None = None,
    equipment_text: str | None = None,
    tower: str | None = None,
    position: str | None = None,
) -> str | None:
    for candidate in (raw_text, file_name):
        direct_code = extract_equipment_code(candidate)
        if direct_code:
            return direct_code

    alias_inputs = [
        equipment_text,
        _compose_alias_text(tower=tower, position=position),
        _compose_alias_text(tower=tower, position=position, include_elev=True),
    ]
    for alias_text in alias_inputs:
        resolved = resolve_equipment_code_alias(alias_text)
        if resolved:
            return resolved
    return None


def normalize_equipment_key(
    *,
    equipment_code: str | None,
    tower: str | None,
    position: str | None,
    equipment_text: str | None,
) -> str | None:
    if equipment_code:
        return equipment_code.upper()
    parts = [normalize_for_match(piece) for piece in [tower, position, equipment_text] if piece]
    if not parts:
        return None
    return "|".join(parts)


def equipment_display_label(
    *,
    equipment_code: str | None,
    tower: str | None,
    position: str | None,
    equipment_text: str | None,
) -> str:
    pieces = [equipment_code or "", tower or "", position or "", equipment_text or ""]
    return " | ".join(piece for piece in pieces if piece)


def list_tower_filter_options() -> list[str]:
    return list(TOWER_FILTER_OPTIONS)


def list_equipment_filter_codes(tower: str | None = None) -> list[str]:
    catalog = _load_catalog()

    def sort_key(code: str) -> tuple[str, int, str]:
        metadata = catalog.get(code, {})
        tower_value = str(metadata.get("tower") or "Z")
        position = str(metadata.get("position") or "")
        return (tower_value, _POSITION_ORDER.get(position, 99), code)

    filtered_codes = [
        code
        for code, metadata in catalog.items()
        if not tower or str(metadata.get("tower") or "").upper() == tower.upper()
    ]
    return sorted(filtered_codes, key=sort_key)


def catalog_equipment_codes(tower: str | None = None) -> list[str]:
    return list_equipment_filter_codes(tower=tower)


def is_catalog_equipment_code(code: str | None) -> bool:
    if not code:
        return False
    return code.upper() in _load_catalog()


def equipment_display_name(code: str | None) -> str | None:
    if not code:
        return None
    metadata = _load_catalog().get(code.upper())
    if not metadata:
        return None
    return str(metadata.get("display_name") or "")


def format_equipment_filter_option(code: str) -> str:
    if code == EQUIPMENT_OTHER_FILTER_VALUE:
        return "Sin catálogo"
    metadata = _load_catalog().get(code.upper())
    if metadata:
        return str(metadata.get("display_name") or code)
    return code


def list_catalog_entries(tower: str | None = None) -> list[dict]:
    catalog = _load_catalog()
    rows: list[dict] = []
    for code in list_equipment_filter_codes(tower=tower):
        metadata = catalog.get(code, {})
        rows.append(
            {
                "equipment_code": code,
                "tower": metadata.get("tower"),
                "position_name": metadata.get("position"),
                "display_name": metadata.get("display_name"),
                "aliases": list(_catalog_aliases(code, metadata)),
            }
        )
    return rows


def _load_catalog() -> dict[str, dict[str, object]]:
    catalog_from_db = _load_catalog_from_database()
    if catalog_from_db:
        return catalog_from_db
    return _build_default_catalog()


def _load_catalog_from_database() -> dict[str, dict[str, object]]:
    database_path = _resolve_database_path()
    if not database_path or not database_path.exists():
        return {}

    try:
        connection = sqlite3.connect(database_path)
        connection.row_factory = sqlite3.Row
        if not _table_exists(connection, "equipment_catalog"):
            return {}

        rows = connection.execute(
            """
            SELECT equipment_code, tower, position_name, display_name
            FROM equipment_catalog
            WHERE is_active = 1
            ORDER BY tower, display_name
            """
        ).fetchall()
        if not rows:
            return {}

        alias_rows = []
        if _table_exists(connection, "equipment_aliases"):
            alias_rows = connection.execute(
                """
                SELECT equipment_code, alias_text
                FROM equipment_aliases
                ORDER BY equipment_code, alias_text
                """
            ).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        try:
            connection.close()
        except Exception:
            pass

    alias_map: dict[str, list[str]] = {}
    for row in alias_rows:
        alias_map.setdefault(str(row["equipment_code"]).upper(), []).append(str(row["alias_text"]))

    catalog: dict[str, dict[str, object]] = {}
    for row in rows:
        code = str(row["equipment_code"]).upper()
        display_name = str(row["display_name"])
        catalog[code] = {
            "tower": str(row["tower"]).upper() if row["tower"] else None,
            "position": str(row["position_name"]).lower() if row["position_name"] else None,
            "display_name": display_name,
            "aliases": [display_name, *alias_map.get(code, [])],
        }
    return catalog


def _resolve_database_path() -> Path | None:
    try:
        from gtv.config import get_settings

        settings = get_settings()
        return settings.database_path
    except Exception:
        return None


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return bool(row)


def _build_default_catalog() -> dict[str, dict[str, object]]:
    catalog: dict[str, dict[str, object]] = {}
    for row in default_catalog_seed_rows():
        catalog[row["equipment_code"]] = {
            "tower": row["tower"],
            "position": row["position_name"],
            "display_name": row["display_name"],
            "aliases": [row["display_name"], *row["aliases"]],
        }
    return catalog


def _catalog_aliases(code: str, metadata: dict[str, object]) -> list[str]:
    aliases = list(metadata.get("aliases", []) or [])
    display_name = str(metadata.get("display_name") or "")
    tower = metadata.get("tower")
    position = metadata.get("position")
    if display_name:
        aliases.append(display_name)
    if tower and position:
        aliases.extend(
            [
                f"Torre {tower} {position}",
                f"Torre {tower} Elev {position}",
                f"Torre {tower} Elevador {position}",
                f"{tower} {position}",
                f"{code} Torre {tower} {position}",
            ]
        )
    deduped: list[str] = []
    seen: set[str] = set()
    for alias in aliases:
        normalized = normalize_alias_text(alias)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalize_whitespace(alias))
    return deduped


def _compose_alias_text(*, tower: str | None, position: str | None, include_elev: bool = False) -> str | None:
    if not tower or not position:
        return None
    if include_elev:
        return normalize_whitespace(f"Torre {tower} Elev {position}")
    return normalize_whitespace(f"Torre {tower} {position}")


def _fallback_display_name(code: str, metadata: dict[str, object]) -> str:
    tower = str(metadata.get("tower") or "?").upper()
    position = str(metadata.get("position") or "equipo").replace("_", " ")
    return f"Torre {tower} Elevador {position.title()}"
