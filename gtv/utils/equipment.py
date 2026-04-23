"""Equipment code extraction and alias normalization helpers."""

from __future__ import annotations

import re

from gtv.utils.text import normalize_for_match, normalize_whitespace

EQUIPMENT_CODE_REGEX = re.compile(r"\b(\d{5}-MEX-ELE-BLT)\b", flags=re.IGNORECASE)
SHORT_CODE_REGEX = re.compile(r"\b(10\d{3})\b")

_CATALOG = {
    "10258-MEX-ELE-BLT": {
        "tower": "A",
        "position": "derecho",
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
        "aliases": [
            "Torre C Elev Servicio",
            "Torre C Servicio",
            "Elevador C Servicio",
        ],
    },
    "10265-MEX-ELE-BLT": {
        "tower": "D",
        "position": "derecho",
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
        "aliases": [
            "Torre E Elev Servicio",
            "Torre E Servicio",
            "Elevador E Servicio",
        ],
    },
}

EQUIPMENT_OTHER_FILTER_VALUE = "__other__"
TOWER_FILTER_OPTIONS = ["A", "B", "C", "D", "E", "F"]
_POSITION_ORDER = {
    "izquierdo": 1,
    "derecho": 2,
    "servicio": 3,
    "carga": 4,
    "unico": 5,
}


def extract_equipment_code(text: str | None) -> str | None:
    if not text:
        return None
    match = EQUIPMENT_CODE_REGEX.search(text)
    return match.group(1).upper() if match else None


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
        for code in _CATALOG:
            if code.startswith(short_code):
                return code

    best_match: tuple[int, str] | None = None
    for code, metadata in _CATALOG.items():
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


def list_equipment_filter_codes() -> list[str]:
    def sort_key(code: str) -> tuple[str, int, str]:
        metadata = _CATALOG.get(code, {})
        tower = metadata.get("tower") or "Z"
        position = metadata.get("position") or ""
        return (tower, _POSITION_ORDER.get(position, 99), code)

    return sorted(_CATALOG.keys(), key=sort_key)


def catalog_equipment_codes() -> list[str]:
    return list(_CATALOG.keys())


def is_catalog_equipment_code(code: str | None) -> bool:
    if not code:
        return False
    return code.upper() in _CATALOG


def format_equipment_filter_option(code: str) -> str:
    if code == EQUIPMENT_OTHER_FILTER_VALUE:
        return "Otros (fuera de catálogo)"
    metadata = _CATALOG.get(code, {})
    tower = metadata.get("tower") or "?"
    position = metadata.get("position") or "equipo"
    position_label = position.replace("_", " ")
    return f"Torre {tower} - elevador {position_label}"


def _catalog_aliases(code: str, metadata: dict) -> list[str]:
    aliases = list(metadata.get("aliases", []))
    tower = metadata.get("tower")
    position = metadata.get("position")
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
    return [normalize_whitespace(alias) for alias in aliases if alias]


def _compose_alias_text(*, tower: str | None, position: str | None, include_elev: bool = False) -> str | None:
    if not tower or not position:
        return None
    if include_elev:
        return normalize_whitespace(f"Torre {tower} Elev {position}")
    return normalize_whitespace(f"Torre {tower} {position}")
