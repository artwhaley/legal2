"""SQLite connection helpers."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from message_evidence_workstation.config.paths import default_db_path

_log = logging.getLogger(__name__)

_extension_load_warning: str | None = None


def extension_load_warning() -> str | None:
    """Return pre-bootstrap warning about extension-loading availability, if any."""
    return _extension_load_warning


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    global _extension_load_warning
    try:
        conn.enable_load_extension(True)
        _extension_load_warning = None
    except AttributeError as exc:
        msg = (
            f"SQLite extension loading is not available: {exc}. "
            "sqlite-vec features will not work."
        )
        _extension_load_warning = msg
        _log.warning(msg)
    return conn
