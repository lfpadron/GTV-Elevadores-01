"""Document classification and proximity helpers."""

from __future__ import annotations

import re


def classify_document(text: str) -> str:
    lowered = text.lower()
    if "reporte de fallas" in lowered:
        return "reporte"
    if "reporte de hallazgo" in lowered:
        return "hallazgo"
    if re.search(r"\bcot[-\s]?[a-z0-9./-]+\b", lowered):
        return "estimacion"
    if "cotizacion" in lowered or "cotización" in lowered:
        return "estimacion"
    return "no_reconocido"


def proximity_label(days_difference: int | None) -> str | None:
    if days_difference is None:
        return None
    if 0 <= days_difference <= 3:
        return "muy_cercana"
    if 4 <= days_difference <= 7:
        return "cercana"
    if 8 <= days_difference <= 15:
        return "posible"
    return None


def similarity_label(score: int) -> str:
    if score >= 85:
        return "sugerencia fuerte"
    if score >= 70:
        return "sugerencia media"
    if score >= 50:
        return "sugerencia debil"
    return "sin sugerencia automatica"
