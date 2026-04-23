"""Filesystem helpers for uploaded documents and exports."""

from __future__ import annotations

import hashlib
from pathlib import Path
import re


def sha256_bytes(content: bytes) -> str:
    digest = hashlib.sha256()
    digest.update(content)
    return digest.hexdigest()


def sanitize_filename(filename: str) -> str:
    cleaned = re.sub(r"[^\w.\- ]+", "_", filename.strip(), flags=re.ASCII)
    return cleaned or "archivo.pdf"


def split_filename(filename: str) -> tuple[str, str]:
    path = Path(filename)
    return path.stem, path.suffix.lower()


def next_duplicate_name(base_name: str, extension: str, existing_names: list[str]) -> str:
    stem = base_name
    pattern = re.compile(rf"^{re.escape(stem)}_dup-(\d+){re.escape(extension)}$", re.IGNORECASE)
    max_found = 0
    for current in existing_names:
        match = pattern.match(current)
        if match:
            max_found = max(max_found, int(match.group(1)))
    return f"{stem}_dup-{max_found + 1:02d}{extension}"

