"""CLI entry point to initialize the SQLite database."""

from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from gtv.config import SecretsConfigurationError, render_secret_error
from gtv.db.init_db import initialize_database


if __name__ == "__main__":
    try:
        initialize_database()
    except SecretsConfigurationError as exc:
        print(render_secret_error(exc))
        raise SystemExit(1) from exc
