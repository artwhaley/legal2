"""Portable evidence workspace (.evw) file helpers."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

from message_evidence_workstation.config.paths import default_workspace_path
from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.domain.constants import (
    WORKSPACE_FORMAT_ID,
    WORKSPACE_FORMAT_VERSION,
)
from message_evidence_workstation.logging_ui.process_log import ProcessLogger, utc_now_iso

if TYPE_CHECKING:
    pass

EVW_EXTENSION = ".evw"
_METADATA_KEYS = (
    "format_id",
    "format_version",
    "created_at",
    "updated_at",
    "display_name",
)


class WorkspaceError(Exception):
    """Raised when a file is not a valid evidence workspace."""


def ensure_evw_path(path: Path) -> Path:
    if path.suffix.lower() != EVW_EXTENSION:
        return path.with_suffix(EVW_EXTENSION)
    return path


def _read_metadata(conn: sqlite3.Connection) -> dict[str, str]:
    try:
        rows = conn.execute("SELECT key, value FROM workspace_metadata").fetchall()
    except sqlite3.OperationalError:
        return {}
    return {str(row["key"]): str(row["value"]) for row in rows}


def _write_metadata(conn: sqlite3.Connection, metadata: dict[str, str]) -> None:
    for key, value in metadata.items():
        conn.execute(
            """
            INSERT INTO workspace_metadata (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
    conn.commit()


def seed_workspace_metadata(
    conn: sqlite3.Connection,
    *,
    display_name: str,
    created_at: str | None = None,
) -> dict[str, str]:
    now = created_at or utc_now_iso()
    metadata = {
        "format_id": WORKSPACE_FORMAT_ID,
        "format_version": str(WORKSPACE_FORMAT_VERSION),
        "created_at": now,
        "updated_at": now,
        "display_name": display_name,
    }
    _write_metadata(conn, metadata)
    return metadata


def touch_workspace_updated(conn: sqlite3.Connection) -> None:
    metadata = get_workspace_metadata(conn)
    metadata["updated_at"] = utc_now_iso()
    _write_metadata(conn, metadata)


def get_workspace_metadata(conn: sqlite3.Connection) -> dict[str, str]:
    return _read_metadata(conn)


def validate_workspace(conn: sqlite3.Connection) -> dict[str, str]:
    metadata = get_workspace_metadata(conn)
    if metadata.get("format_id") != WORKSPACE_FORMAT_ID:
        raise WorkspaceError(
            f"Not an evidence workspace file (expected format_id={WORKSPACE_FORMAT_ID!r})"
        )
    return metadata


def create_workspace(
    path: Path,
    logger: ProcessLogger,
    *,
    display_name: str | None = None,
) -> sqlite3.Connection:
    evw_path = ensure_evw_path(path)
    evw_path.parent.mkdir(parents=True, exist_ok=True)
    if evw_path.exists():
        raise WorkspaceError(f"Workspace already exists: {evw_path}")
    conn = connect(evw_path)
    initialize_schema(conn, logger)
    seed_workspace_metadata(conn, display_name=display_name or evw_path.stem)
    logger.info(
        component="db.workspace",
        operation="workspace_create",
        message=f"Created evidence workspace '{evw_path.name}'",
        details={"path": str(evw_path)},
    )
    return conn


def open_workspace(path: Path, logger: ProcessLogger) -> sqlite3.Connection:
    evw_path = ensure_evw_path(path)
    if not evw_path.exists():
        raise WorkspaceError(f"Workspace file not found: {evw_path}")
    conn = connect(evw_path)
    initialize_schema(conn, logger)
    metadata = get_workspace_metadata(conn)
    if not metadata:
        seed_workspace_metadata(conn, display_name=evw_path.stem)
        metadata = get_workspace_metadata(conn)
    validate_workspace(conn)
    logger.info(
        component="db.workspace",
        operation="workspace_open",
        message=f"Opened evidence workspace '{evw_path.name}'",
        details={"path": str(evw_path), "display_name": metadata.get("display_name", "")},
    )
    return conn


def open_or_create_workspace(path: Path, logger: ProcessLogger) -> sqlite3.Connection:
    if path.exists():
        return open_workspace(path, logger)
    return create_workspace(path, logger)


def open_or_create_default_workspace(logger: ProcessLogger) -> tuple[sqlite3.Connection, Path]:
    path = default_workspace_path()
    return open_or_create_workspace(path, logger), path


def import_into_workspace(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    dataset_dir: Path,
    *,
    reload: bool = False,
) -> int:
    from message_evidence_workstation.db.evidence_blocks import ensure_uncategorized_category
    from message_evidence_workstation.importers.normalized_loader import load_normalized_dataset

    dataset_id = load_normalized_dataset(conn, logger, dataset_dir, reload=reload)
    ensure_uncategorized_category(conn, logger, dataset_id)
    touch_workspace_updated(conn)
    return dataset_id
