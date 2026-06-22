"""SQLite connection helpers."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from message_evidence_workstation.config.paths import default_db_path


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    try:
        conn.enable_load_extension(True)
    except AttributeError:
        pass
    return conn
