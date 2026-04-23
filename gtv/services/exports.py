"""Excel and PDF exports for v1."""

from __future__ import annotations

from datetime import datetime
from io import BytesIO

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def dataframe_to_excel_bytes(dataframe: pd.DataFrame, sheet_name: str = "Datos") -> bytes:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        dataframe.to_excel(writer, sheet_name=sheet_name, index=False)
    buffer.seek(0)
    return buffer.read()


def export_filename(base_name: str, extension: str) -> str:
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    safe_base = base_name.replace(" ", "_")
    safe_extension = extension.lstrip(".")
    return f"{safe_base}_{timestamp}.{safe_extension}"


def format_filter_criteria(filters: dict[str, object], labels: dict[str, str]) -> list[str]:
    lines: list[str] = []
    for key, label in labels.items():
        value = filters.get(key)
        if value in (None, "", [], (), {}):
            continue
        if isinstance(value, (list, tuple)):
            rendered = ", ".join(str(item) for item in value if item not in (None, ""))
        else:
            rendered = str(value)
        if rendered:
            lines.append(f"{label}: {rendered}")
    return lines


def simple_pdf_table_bytes(
    title: str,
    columns: list[str],
    rows: list[list[object]],
    *,
    criteria_lines: list[str] | None = None,
) -> bytes:
    buffer = BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=landscape(A4), leftMargin=24, rightMargin=24)
    styles = getSampleStyleSheet()
    story = [Paragraph(title, styles["Title"]), Spacer(1, 12)]
    if criteria_lines:
        story.append(Paragraph("Criterios de búsqueda", styles["Heading3"]))
        for line in criteria_lines:
            story.append(Paragraph(line, styles["BodyText"]))
        story.append(Spacer(1, 10))
    table = Table([columns, *rows], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#16324f")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.lightgrey]),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story.append(table)
    document.build(story)
    buffer.seek(0)
    return buffer.read()


def export_search_rows(rows: list[dict], *, criteria_lines: list[str] | None = None) -> tuple[bytes, bytes]:
    dataframe = pd.DataFrame(rows)
    excel_bytes = dataframe_to_excel_bytes(dataframe, "Tickets")
    pdf_columns = list(dataframe.columns)
    pdf_rows = dataframe.fillna("").astype(str).values.tolist()
    pdf_bytes = simple_pdf_table_bytes("Tickets filtrados", pdf_columns, pdf_rows[:200], criteria_lines=criteria_lines)
    return excel_bytes, pdf_bytes


def export_case_bundle(case_bundle: dict) -> tuple[bytes, bytes]:
    rows = []
    for item in case_bundle["estimate_items"]:
        rows.append(
            {
                "folio_estimacion": item.get("normalized_folio") or item.get("original_folio"),
                "concepto": item.get("concept_text"),
                "cantidad": item.get("quantity"),
                "precio_unitario": item.get("unit_price"),
                "subtotal": item.get("subtotal"),
                "fecha_entrega_estimada": item.get("estimated_delivery_date"),
                "recepcion": item.get("receipt_status"),
                "pago": item.get("payment_status"),
                "factura": item.get("invoice_number"),
            }
        )
    dataframe = pd.DataFrame(rows or [{"detalle": "Sin partidas registradas"}])
    excel_bytes = dataframe_to_excel_bytes(dataframe, "DetalleCaso")
    pdf_columns = list(dataframe.columns)
    pdf_rows = dataframe.fillna("").astype(str).values.tolist()
    case_folio = case_bundle["case"]["case_folio"]
    pdf_bytes = simple_pdf_table_bytes(f"Detalle de caso {case_folio}", pdf_columns, pdf_rows[:200])
    return excel_bytes, pdf_bytes


def export_matches(rows: list[dict]) -> bytes:
    dataframe = pd.DataFrame(rows)
    return dataframe_to_excel_bytes(dataframe, "Conciliacion")


def export_procurement_rows(rows: list[dict]) -> bytes:
    dataframe = pd.DataFrame(rows)
    return dataframe_to_excel_bytes(dataframe, "ComprasPagosFacturas")


def export_report_ticket_report(rows: list[dict], *, criteria_lines: list[str] | None = None) -> tuple[bytes, bytes]:
    dataframe = pd.DataFrame(rows or [{"detalle": "Sin resultados"}])
    excel_bytes = dataframe_to_excel_bytes(dataframe, "TicketsHallazgos")
    pdf_bytes = simple_pdf_table_bytes(
        "Reporte de reportes, tickets y hallazgos",
        list(dataframe.columns),
        dataframe.fillna("").astype(str).values.tolist()[:250],
        criteria_lines=criteria_lines,
    )
    return excel_bytes, pdf_bytes


def export_item_tracking_report(
    rows: list[dict],
    *,
    title: str = "Reporte de partidas",
    criteria_lines: list[str] | None = None,
) -> tuple[bytes, bytes]:
    dataframe = pd.DataFrame(rows or [{"detalle": "Sin resultados"}])
    excel_bytes = dataframe_to_excel_bytes(dataframe, "Partidas")
    pdf_bytes = simple_pdf_table_bytes(
        title,
        list(dataframe.columns),
        dataframe.fillna("").astype(str).values.tolist()[:250],
        criteria_lines=criteria_lines,
    )
    return excel_bytes, pdf_bytes
