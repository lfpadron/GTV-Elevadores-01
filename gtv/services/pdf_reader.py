"""Digital PDF text extraction."""

from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader

from gtv.utils.text import normalize_pdf_text


def extract_pages_from_pdf(file_bytes: bytes, extraction_mode: str | None = None) -> list[str]:
    reader = PdfReader(BytesIO(file_bytes))
    pages: list[str] = []
    for page in reader.pages:
        if extraction_mode == "layout":
            text = page.extract_text(extraction_mode="layout") or ""
        else:
            text = page.extract_text() or ""
        pages.append(normalize_pdf_text(text))
    return pages
