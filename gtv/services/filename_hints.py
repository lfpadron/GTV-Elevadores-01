"""Extract useful hints from uploaded file names without replacing text-based classification."""

from __future__ import annotations

from pathlib import Path
import re

from gtv.utils.text import normalize_whitespace


def parse_filename_hints(file_name: str | None) -> dict[str, str | None]:
    if not file_name:
        return {}

    stem = Path(file_name).stem
    raw = stem.replace("__", "_")
    hints: dict[str, str | None] = {
        "ticket": None,
        "folio": None,
        "tower": None,
        "position": None,
        "equipment_text": None,
        "equipment_code": None,
    }

    report_ticket = re.search(r"Reporte_de_falla_(\d+)", raw, flags=re.IGNORECASE)
    hallazgo_ticket = re.search(r"Hallazgo_ticket(\d+)", raw, flags=re.IGNORECASE)
    folio_match = re.search(r"(COT[-_ ]?\d+)", raw, flags=re.IGNORECASE)
    equipment_code_match = re.search(r"(\d{5}-MEX-ELE-BLT)", raw, flags=re.IGNORECASE)
    tower_match = re.search(r"Torre[_\s-]*([A-Z])", raw, flags=re.IGNORECASE)
    position_match = re.search(r"(Izquierdo|Derecho|Carga|Unico|Único)", raw, flags=re.IGNORECASE)
    service_match = re.search(r"Elev(?:ador)?[_\s-]*Servicio", raw, flags=re.IGNORECASE)

    if report_ticket:
        hints["ticket"] = report_ticket.group(1)
    if hallazgo_ticket:
        hints["ticket"] = hallazgo_ticket.group(1)
    if folio_match:
        hints["folio"] = folio_match.group(1).replace("_", "-").upper()
    if equipment_code_match:
        hints["equipment_code"] = equipment_code_match.group(1).upper()
    if tower_match:
        hints["tower"] = tower_match.group(1).upper()
    if position_match:
        position = position_match.group(1).lower()
        hints["position"] = "unico" if position in {"unico", "único"} else position

    if hints["tower"] and hints["position"]:
        hints["equipment_text"] = f"Torre {hints['tower']} Elev ({hints['position'].capitalize()})"
    elif hints["tower"] and service_match:
        hints["equipment_text"] = f"Torre {hints['tower']} Elev Servicio"
    elif "Elevador_D2" in raw:
        hints["equipment_text"] = "OTRO - Elevador D2"
    elif "Grand_Tower_del_Valle" in raw:
        hints["equipment_text"] = "Grand Tower del Valle (Coyo 4)"

    if hints["equipment_text"]:
        hints["equipment_text"] = normalize_whitespace(hints["equipment_text"])
    return hints
