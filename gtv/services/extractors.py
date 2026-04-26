"""Heuristic extraction for reportes, hallazgos and estimaciones."""

from __future__ import annotations

from datetime import datetime, timedelta
import re

from gtv.constants import ESTIMATE_RULES_EFFECTIVE_DATE
from gtv.models import ExtractedDocument
from gtv.services.classifiers import classify_document
from gtv.services.filename_hints import parse_filename_hints
from gtv.utils.equipment import infer_equipment_code, normalize_equipment_key
from gtv.utils.dates import normalize_time, parse_date, parse_spanish_date
from gtv.utils.text import first_non_empty, normalize_for_match, normalize_whitespace, summarize_text


NUMERIC_DATE_REGEX = re.compile(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})\b")
TIME_REGEX = re.compile(r"\b(\d{1,2}:\d{2}(?::\d{2})?)\b")
TITLE_DATETIME_REGEX = re.compile(
    r"\b(\d{1,2}\s+[A-Za-záéíóúü]+\s+\d{2,4}),\s*(\d{1,2}:\d{2}(?::\d{2})?)\s*(?:hrs?|h)?\b",
    flags=re.IGNORECASE,
)
HEADER_NUMERIC_DATE_REGEX = re.compile(
    r"\ba\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b",
    flags=re.IGNORECASE,
)
TOWER_ONLY_REGEX = re.compile(r"\bTorre\s+([A-Z])\b", flags=re.IGNORECASE)
EQUIPMENT_FIELD_REGEX = re.compile(
    r"Equipo:\s*(.+?)(?=(?:Causa|Soluci[oó]n|Hallazgo|Estatus|FIRMAS|$))",
    flags=re.IGNORECASE | re.DOTALL,
)
HALLAZGO_LINE_REGEX = re.compile(
    r"^Hallazgo\s+(\d+\.\d+)\s*(?:\[[^\]]+\])?\s*(.+)$",
    flags=re.IGNORECASE,
)
ESTIMATE_REPORT_REFERENCE_REGEX = re.compile(r"\bReporte\s*([A-Z0-9.-]*\d[A-Z0-9.-]*)\b", flags=re.IGNORECASE)
ESTIMATE_FINDING_REFERENCE_REGEX = re.compile(r"\bHallazgo\s*([A-Z0-9.-]*\d[A-Z0-9.-]*)\b", flags=re.IGNORECASE)


def extract_document_structured(
    pages: list[str],
    *,
    file_name: str | None = None,
    layout_pages: list[str] | None = None,
    forced_document_type: str | None = None,
) -> ExtractedDocument:
    raw_text = "\n".join(page for page in pages if page).strip()
    layout_text = "\n".join(page for page in (layout_pages or []) if page).strip()
    document_type = forced_document_type or classify_document(raw_text)
    raw_lines = _normalized_lines(pages)
    layout_lines = _normalized_lines(layout_pages or [])
    filename_hints = parse_filename_hints(file_name)
    short_description, summary = summarize_text(raw_text)

    common = _extract_common(
        document_type=document_type,
        text=raw_text,
        raw_lines=raw_lines,
        layout_lines=layout_lines,
        filename_hints=filename_hints,
    )

    if document_type == "reporte":
        payload = _extract_fault_report(raw_text, raw_lines, filename_hints)
        status = _resolve_status(
            {
                "ticket": bool(payload.get("ticket_number")),
                "fecha": bool(common["document_date"]),
                "hora": bool(common["document_time"]),
                "equipo": bool(common["equipment_text"]),
                "descripcion": bool(payload.get("description")),
            }
        )
        primary_identifier = payload.get("ticket_number")
    elif document_type == "hallazgo":
        payload = _extract_finding(raw_text, raw_lines, filename_hints)
        status = _resolve_status(
            {
                "fecha": bool(common["document_date"]),
                "hora": bool(common["document_time"]),
                "hallazgo_ticket": bool(payload.get("finding_folio") or payload.get("base_ticket_number")),
                "descripcion": bool(payload.get("description")),
            }
        )
        primary_identifier = first_non_empty(payload.get("finding_folio"), payload.get("base_ticket_number"))
    elif document_type == "estimacion":
        payload = _extract_estimate(raw_text, raw_lines, layout_text, layout_lines, common["document_date"], filename_hints)
        common = _merge_common_estimate_equipment(common, payload.get("items", []))
        enforce_new_estimate_rules = bool(common["document_date"] and common["document_date"] >= ESTIMATE_RULES_EFFECTIVE_DATE)
        estimate_equipment_ok = (
            bool(payload.get("items"))
            and all(bool(item.get("equipment_code")) for item in payload.get("items", []))
        ) if enforce_new_estimate_rules else bool(payload.get("items"))
        status = _resolve_status(
            {
                "folio": bool(payload.get("original_folio")),
                "fecha": bool(common["document_date"]),
                "equipo": estimate_equipment_ok,
                "partida": len(payload.get("items", [])) > 0,
            }
        )
        primary_identifier = first_non_empty(payload.get("normalized_folio"), payload.get("original_folio"))
    else:
        payload = {}
        status = "requiere_revision"
        primary_identifier = None

    summary_source = first_non_empty(
        payload.get("description") if isinstance(payload, dict) else None,
        payload.get("recommendation_text") if isinstance(payload, dict) else None,
        summary,
    ) or summary
    short_description, summary_ai = summarize_text(summary_source, limit=160)

    return ExtractedDocument(
        document_type=document_type,
        extraction_status=status,
        document_date=common["document_date"],
        document_time=common["document_time"],
        tower=common["tower"],
        position=common["position"],
        equipment_text=common["equipment_text"],
        equipment_code=common["equipment_code"],
        equipment_key=normalize_equipment_key(
            equipment_code=common["equipment_code"],
            tower=common["tower"],
            position=common["position"],
            equipment_text=common["equipment_text"],
        ),
        primary_identifier=primary_identifier,
        summary_ai_original=summary_ai,
        short_description=short_description,
        raw_text=raw_text,
        total_pages=len(pages),
        detail_payload=payload,
    )


def _extract_common(
    *,
    document_type: str,
    text: str,
    raw_lines: list[str],
    layout_lines: list[str],
    filename_hints: dict[str, str | None],
) -> dict[str, str | None]:
    header_date, header_time = _extract_header_datetime(document_type, raw_lines)
    fallback_date, fallback_time = _extract_fallback_datetime(raw_lines)
    equipment_text = _extract_equipment_text(
        document_type=document_type,
        text=text,
        raw_lines=raw_lines,
        layout_lines=layout_lines,
        filename_hints=filename_hints,
    )
    tower = first_non_empty(
        _extract_tower_from_equipment(equipment_text),
        filename_hints.get("tower"),
    )
    position = first_non_empty(
        _extract_position_from_equipment(equipment_text),
        filename_hints.get("position"),
    )
    equipment_code = first_non_empty(
        filename_hints.get("equipment_code"),
        infer_equipment_code(
            raw_text=text,
            equipment_text=equipment_text,
            tower=tower,
            position=position,
        ),
    )
    return {
        "document_date": header_date or fallback_date,
        "document_time": header_time or fallback_time,
        "tower": tower,
        "position": position,
        "equipment_text": equipment_text,
        "equipment_code": equipment_code,
    }


def _extract_fault_report(text: str, raw_lines: list[str], filename_hints: dict[str, str | None]) -> dict:
    ticket_number = _search_first(
        [
            r"Número de Ticket:\s*([A-Z0-9-]+)",
            r"Ticket\s*[:#-]?\s*([A-Z0-9-]+)",
        ],
        text,
    ) or filename_hints.get("ticket")
    cause = _extract_labeled_section(
        text,
        ["causa"],
        ["solución", "solucion", "fotoevidencia", "firmas", "causa falla zona"],
    )
    solution = _extract_labeled_section(
        text,
        ["solución", "solucion"],
        ["fotoevidencia", "firmas", "causa falla zona"],
    )
    description = _compose_report_description(cause, solution)
    return {
        "ticket_number": ticket_number,
        "report_state": "reportado",
        "description": description,
        "cause_text": cause,
        "solution_text": solution,
        "source_pages": _pages_label(raw_lines),
    }


def _extract_finding(text: str, raw_lines: list[str], filename_hints: dict[str, str | None]) -> dict:
    base_ticket_number = (
        _search_first([r"Reporte de Hallazgo\s*[–-]\s*Ticket\s*([A-Z0-9-]+)"], text)
        or filename_hints.get("ticket")
    )
    hallazgo_entries: list[tuple[str, str]] = []
    for line in raw_lines:
        match = HALLAZGO_LINE_REGEX.match(line)
        if match:
            hallazgo_entries.append((match.group(1), normalize_whitespace(match.group(2))))

    finding_folio = hallazgo_entries[0][0] if hallazgo_entries else None
    descriptions = [entry[1] for entry in hallazgo_entries]
    description = " | ".join(descriptions) if descriptions else None
    affected_parts = [_extract_part_phrase(entry) for entry in descriptions]
    affected_parts = [part for part in affected_parts if part]
    recommendation_text = " | ".join(descriptions) if descriptions else _guess_recommendation_from_text(text)

    return {
        "base_ticket_number": base_ticket_number,
        "finding_folio": finding_folio,
        "finding_state": "detectado",
        "description": description,
        "affected_part_text": " | ".join(_dedupe_preserve_order(affected_parts)) if affected_parts else _guess_part_from_text(description or text),
        "recommendation_text": recommendation_text,
        "source_pages": _pages_label(raw_lines),
    }


def _extract_estimate(
    text: str,
    raw_lines: list[str],
    layout_text: str,
    layout_lines: list[str],
    document_date: str | None,
    filename_hints: dict[str, str | None],
) -> dict:
    enforce_new_estimate_rules = bool(document_date and document_date >= ESTIMATE_RULES_EFFECTIVE_DATE)
    original_folio = _search_first(
        [
            r"\b(VA-COT-\d+)\b",
            r"\b(COT-\d+)\b",
            r"(?:folio|cotización|cotizacion)\s*[:#-]?\s*([A-Z0-9./-]+)",
        ],
        text,
    ) or filename_hints.get("folio")
    normalized_folio = _normalize_estimate_folio(original_folio)
    report_reference_text = _search_regex(ESTIMATE_REPORT_REFERENCE_REGEX, text)
    finding_reference_text = _search_regex(ESTIMATE_FINDING_REFERENCE_REGEX, text)
    delivery_days = _search_int(r"Tiempo de Entrega:\s*(\d+)\s+D[ií]as?\s+naturales", text)
    estimated_delivery_date = None
    if delivery_days is not None and document_date:
        estimated_delivery_date = (
            datetime.fromisoformat(document_date) + timedelta(days=delivery_days)
        ).date().isoformat()
    fallback_equipment_text = first_non_empty(
        _search_first(
            [
                r"Equipo(?:\s+de)?\s+(Torre\s+[A-Z].+?)(?:--|$)",
                r"para\s+el\s+Equipo\s+de\s+(Torre\s+[A-Z].+?)(?:--|$)",
            ],
            text,
        ),
        filename_hints.get("equipment_text"),
    )
    items = _extract_estimate_items(
        layout_lines,
        raw_lines,
        document_date=document_date,
        fallback_equipment_text=fallback_equipment_text,
        fallback_delivery_days=delivery_days,
        report_reference_text=report_reference_text,
        finding_reference_text=finding_reference_text,
        enforce_new_rules=enforce_new_estimate_rules,
    )
    subtotal_amount = _search_amount_line("Subtotal", layout_text or text)
    tax_amount = _search_amount_line("Impuesto", layout_text or text)
    total_amount = _search_amount_line("Total", layout_text or text)
    return {
        "original_folio": original_folio,
        "normalized_folio": normalized_folio,
        "report_reference_text": report_reference_text,
        "finding_reference_text": finding_reference_text,
        "missing_supporting_reference": 1 if enforce_new_estimate_rules and not report_reference_text and not finding_reference_text else 0,
        "estimate_state": "abierta",
        "delivery_days": delivery_days,
        "estimated_delivery_date": estimated_delivery_date,
        "subtotal_amount": subtotal_amount,
        "tax_amount": tax_amount,
        "total_amount": total_amount,
        "items": items,
        "source_pages": _pages_label(raw_lines),
    }


def _extract_header_datetime(document_type: str, raw_lines: list[str]) -> tuple[str | None, str | None]:
    if document_type in {"reporte", "hallazgo"}:
        for line in raw_lines[:8]:
            if document_type == "reporte" and "Reporte de Fallas" not in line:
                continue
            if document_type == "hallazgo" and "Reporte de Hallazgo" not in line:
                continue
            match = TITLE_DATETIME_REGEX.search(line)
            if match:
                return parse_spanish_date(match.group(1)), normalize_time(match.group(2))
    if document_type == "estimacion":
        for line in raw_lines[:8]:
            if "México" not in line and "CDMX" not in line:
                continue
            match = HEADER_NUMERIC_DATE_REGEX.search(line)
            if match:
                return parse_date(match.group(1)), None
    return None, None


def _extract_fallback_datetime(raw_lines: list[str]) -> tuple[str | None, str | None]:
    joined_head = " ".join(raw_lines[:6])
    raw_date = _search_regex(NUMERIC_DATE_REGEX, joined_head)
    raw_time = _search_regex(TIME_REGEX, joined_head)
    return parse_date(raw_date), normalize_time(raw_time)


def _extract_equipment_text(
    *,
    document_type: str,
    text: str,
    raw_lines: list[str],
    layout_lines: list[str],
    filename_hints: dict[str, str | None],
) -> str | None:
    if document_type in {"reporte", "hallazgo"}:
        equipment = _search_regex(EQUIPMENT_FIELD_REGEX, text)
        return first_non_empty(_clean_equipment_text(equipment), filename_hints.get("equipment_text"))

    note_equipment = _search_first(
        [
            r"Nota:\s*.+?\bpara\s+la\s+(Torre\s+[A-Z].+?)(?:--|- -|Equipo|$)",
            r"Nota:\s*.+?\bpara\s+(Torre\s+[A-Z].+?)(?:--|- -|Equipo|$)",
        ],
        text,
    )
    table_equipment = _extract_estimate_equipment_from_lines(raw_lines, layout_lines)
    return first_non_empty(
        _clean_equipment_text(note_equipment),
        _clean_equipment_text(table_equipment),
        filename_hints.get("equipment_text"),
    )


def _extract_estimate_equipment_from_lines(raw_lines: list[str], layout_lines: list[str]) -> str | None:
    for index, line in enumerate(raw_lines):
        if re.fullmatch(r"Torre\s+[A-Z]", line, flags=re.IGNORECASE):
            next_line = raw_lines[index + 1] if index + 1 < len(raw_lines) else ""
            if "Elev" in next_line:
                return normalize_whitespace(f"{line} {next_line}")
        if line == "Grand" and index + 3 < len(raw_lines):
            if raw_lines[index + 1].startswith("Tower"):
                return normalize_whitespace(" ".join(raw_lines[index : index + 4]))

    for line in layout_lines:
        match = re.match(r"^(Torre\s+[A-Z])\s+\d+\s+d[ií]as", line, flags=re.IGNORECASE)
        if match:
            return normalize_whitespace(match.group(1))
        match = re.match(r"^(Grand)\s+\d+\s+d[ií]as", line, flags=re.IGNORECASE)
        if match:
            return "Grand Tower del Valle (Coyo 4)"
    return None


def _extract_estimate_items(
    layout_lines: list[str],
    raw_lines: list[str],
    *,
    document_date: str | None,
    fallback_equipment_text: str | None,
    fallback_delivery_days: int | None,
    report_reference_text: str | None,
    finding_reference_text: str | None,
    enforce_new_rules: bool,
) -> list[dict]:
    items: list[dict] = []
    candidate_lines = layout_lines or raw_lines
    current_equipment_text: str | None = fallback_equipment_text

    for line_number, line in enumerate(candidate_lines, start=1):
        cleaned = normalize_whitespace(line)
        if not cleaned:
            continue
        if re.search(r"\b(Subtotal|Impuesto|Total)\b", cleaned, flags=re.IGNORECASE):
            continue
        if cleaned.startswith("Equipo T/E") or cleaned.startswith("Equipo") and "Subtotal" in cleaned:
            continue
        match = re.match(
            r"^(?P<prefix>.+?)\s+(?P<qty>\d+(?:[.,]\d+)?)\s+(?P<unit>\$[\d,]+(?:\.\d{2})?)\s+(?P<subtotal>\$[\d,]+(?:\.\d{2})?)$",
            cleaned,
        )
        if not match:
            continue
        prefix = match.group("prefix").strip()
        days_split = re.search(r"(?P<equipment>.+?)\s+(?P<days>\d+\s+d[ií]as)\s+(?P<concept>.+)$", prefix, flags=re.IGNORECASE)
        if days_split:
            current_equipment_text = _clean_equipment_text(days_split.group("equipment"))
            concept = days_split.group("concept")
            line_delivery_days = _parse_delivery_days(days_split.group("days"))
        else:
            concept = prefix
            line_delivery_days = None
        concept = _clean_estimate_concept(concept)
        if len(concept) < 4:
            continue
        quantity = _parse_number(match.group("qty")) or 0
        unit_price = _parse_number(match.group("unit")) or 0
        subtotal = _parse_number(match.group("subtotal")) or 0
        resolved_equipment_text = current_equipment_text or fallback_equipment_text
        resolved_tower = _extract_tower_from_equipment(resolved_equipment_text)
        resolved_position = _extract_position_from_equipment(resolved_equipment_text)
        resolved_equipment_code = infer_equipment_code(
            equipment_text=resolved_equipment_text,
            tower=resolved_tower,
            position=resolved_position,
        )
        effective_delivery_days = line_delivery_days if line_delivery_days is not None else fallback_delivery_days
        estimated_delivery_date = None
        if effective_delivery_days is not None and document_date:
            estimated_delivery_date = (
                datetime.fromisoformat(document_date) + timedelta(days=effective_delivery_days)
            ).date().isoformat()
        items.append(
            {
                "line_number": line_number,
                "concept_text": concept,
                "equipment_text_original": resolved_equipment_text,
                "equipment_code": resolved_equipment_code,
                "report_reference_text": report_reference_text,
                "finding_reference_text": finding_reference_text,
                "delivery_days": effective_delivery_days,
                "estimated_delivery_date": estimated_delivery_date,
                "missing_catalog_equipment": 1 if enforce_new_rules and not resolved_equipment_code else 0,
                "missing_supporting_reference": 1 if enforce_new_rules and not report_reference_text and not finding_reference_text else 0,
                "quantity": quantity,
                "unit_price": unit_price,
                "subtotal": subtotal or round(quantity * unit_price, 2),
            }
        )
    return items


def _resolve_status(criticals: dict[str, bool]) -> str:
    present = sum(1 for value in criticals.values() if value)
    required = len(criticals)
    if present == required:
        return "ok"
    if present >= max(1, required // 2):
        return "parcial"
    return "requiere_revision"


def _normalized_lines(pages: list[str]) -> list[str]:
    lines: list[str] = []
    for page in pages:
        for line in page.splitlines():
            cleaned = normalize_whitespace(line)
            if cleaned:
                lines.append(cleaned)
    return lines


def _search_regex(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    return normalize_whitespace(match.group(1)) if match else None


def _search_first(patterns: list[str], text: str) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return normalize_whitespace(match.group(1))
    return None


def _extract_labeled_section(text: str, labels: list[str], stops: list[str]) -> str | None:
    label_group = "|".join(re.escape(label) for label in labels)
    stop_group = "|".join(re.escape(stop) for stop in stops) or r"$^"
    pattern = re.compile(
        rf"(?:{label_group})\s*[:#-]?\s*(.+?)(?=(?:{stop_group})\s*[:#-]?|$)",
        flags=re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(text)
    if not match:
        return None
    return normalize_whitespace(match.group(1))


def _compose_report_description(cause: str | None, solution: str | None) -> str | None:
    if cause and solution:
        return normalize_whitespace(f"Causa: {cause}. Solucion: {solution}")
    return first_non_empty(solution, cause)


def _extract_tower_from_equipment(equipment_text: str | None) -> str | None:
    if not equipment_text:
        return None
    match = TOWER_ONLY_REGEX.search(equipment_text)
    return match.group(1).upper() if match else None


def _extract_position_from_equipment(equipment_text: str | None) -> str | None:
    normalized = normalize_for_match(equipment_text)
    for word in ("izquierdo", "derecho", "servicio", "carga", "unico"):
        if f" {word} " in f" {normalized} ":
            return word
    return None


def _merge_common_estimate_equipment(common: dict[str, str | None], items: list[dict]) -> dict[str, str | None]:
    if not items:
        return common

    item_texts = {
        normalize_whitespace(item.get("equipment_text_original"))
        for item in items
        if item.get("equipment_text_original")
    }
    item_codes = {
        str(item.get("equipment_code")).upper()
        for item in items
        if item.get("equipment_code")
    }
    item_towers = {
        _extract_tower_from_equipment(item.get("equipment_text_original"))
        for item in items
        if item.get("equipment_text_original")
    }
    item_towers.discard(None)

    if not common.get("equipment_text"):
        if len(item_texts) == 1:
            common["equipment_text"] = next(iter(item_texts))
        elif len(item_texts) > 1:
            common["equipment_text"] = "Múltiples equipos"

    if not common.get("tower") and len(item_towers) == 1:
        common["tower"] = next(iter(item_towers))

    if len(item_codes) == 1:
        common["equipment_code"] = next(iter(item_codes))
    elif len(item_codes) > 1:
        common["equipment_code"] = None

    return common


def _parse_delivery_days(text: str | None) -> int | None:
    if not text:
        return None
    match = re.search(r"(\d+)", text)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _parse_number(value: str | None) -> float | None:
    if not value:
        return None
    cleaned = value.replace("$", "").replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def _search_amount_line(label: str, text: str) -> float | None:
    patterns = [
        rf"(?mi)^\s*{re.escape(label)}(?:\s*\([^)]+\))?\s+\$?\s*([\d,]+(?:\.\d{{1,2}})?)\s*$",
        rf"(?mi)\b{re.escape(label)}(?:\s*\([^)]+\))?\s+\$?\s*([\d,]+(?:\.\d{{1,2}})?)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
        if match:
            return _parse_number(match.group(1))
    return None


def _search_int(pattern: str, text: str) -> int | None:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _clean_equipment_text(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = normalize_whitespace(value)
    cleaned = cleaned.strip("- ")
    if cleaned == "Equipo T/E Concepto Cant. P/U Subtotal":
        return None
    return cleaned


def _clean_estimate_concept(value: str) -> str:
    cleaned = normalize_whitespace(value)
    cleaned = re.sub(r"^(?:Incluye|Alcances|Notas?)\s*[:.-]*\s*", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip(" -")


def _extract_part_phrase(text: str) -> str | None:
    patterns = [
        r"(?:cambiar|cambio de|realizar cambio de|reemplazo de|sustituci[oó]n de)\s+(.+?)(?:\s+ya que|\s+como ya|\s+porque|\s*$)",
        r"(?:se recomienda)\s+(.+?)(?:\s+ya que|\s+como ya|\s*$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return normalize_whitespace(match.group(1))
    return None


def _guess_part_from_text(text: str) -> str | None:
    if not text:
        return None
    match = re.search(
        r"(motor|polea|botonera|display|puerta|cable|tarjeta|variador|contactor(?:es)?|sensor|rodillo|roller(?:s)?|multirayo)",
        text,
        flags=re.IGNORECASE,
    )
    return normalize_whitespace(match.group(1)) if match else None


def _guess_recommendation_from_text(text: str) -> str | None:
    match = re.search(
        r"(reemplazar|sustituir|ajustar|lubricar|revisar|cambiar|instalar)[^.:\n]+",
        text,
        flags=re.IGNORECASE,
    )
    return normalize_whitespace(match.group(0)) if match else None


def _pages_label(raw_lines: list[str]) -> str:
    return "1" if raw_lines else "0"


def _normalize_estimate_folio(folio: str | None) -> str | None:
    if not folio:
        return None
    cleaned = normalize_whitespace(folio).upper().replace(" ", "-")
    cleaned = cleaned.replace("VA-", "")
    if cleaned.startswith("COT") and not cleaned.startswith("COT-"):
        cleaned = cleaned.replace("COT", "COT-", 1)
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    return cleaned


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = normalize_for_match(value)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result
