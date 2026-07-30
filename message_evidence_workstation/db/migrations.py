"""Strict EVW v15 runtime schema verification.

Runtime never mutates an existing EVW schema. Older files are handled only by
the explicit compact-copy migration tool.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from message_evidence_workstation.db.schema import CREATE_TABLES_SQL
from message_evidence_workstation.domain.constants import SCHEMA_VERSION

if TYPE_CHECKING:
    from message_evidence_workstation.logging_ui.diagnostic_logger import DiagnosticLogger


class CompactMigrationRequired(RuntimeError):
    """An old or malformed EVW must be passed through explicit migration."""


REQUIRED_COLUMNS: dict[str, set[str]] = {
    "dataset": {"content_revision", "schema_version"},
    "message": {"embedding_input_hash"},
    "working_corpus": {"current_revision_id"},
    "working_corpus_revision": {"working_corpus_revision_id", "scope_hash", "status"},
    "working_corpus_revision_message": {"embedding_input_hash"},
    "working_corpus_revision_index": {"message_embedding_status", "chunk_embedding_status"},
    "embedding_cache_state": {"dimensions", "normalization"},
    "embedding_artifact": {"input_hash", "vector", "dimensions"},
    "evidence_block": {"context_start_message_id", "origin_kind"},
    "evidence_block_message": {"message_content_hash", "section"},
    "message_fts": {"working_corpus_revision_id", "index_generation"},
}

FORBIDDEN_OBJECTS = {
    "working_corpus_message",
    "working_corpus_index",
    "working_corpus_source",
    "working_corpus_thread",
    "vector_store_metadata",
    "message_embedding_vec",
    "chunk_embedding_vec",
    "embedding_profile",
}


def _objects(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','index','trigger','view')"
        )
    }


def validate_v15_shape(conn: sqlite3.Connection) -> None:
    objects = _objects(conn)
    forbidden = sorted(objects & FORBIDDEN_OBJECTS)
    if forbidden:
        raise CompactMigrationRequired(f"EVW v15 contains forbidden legacy objects: {forbidden}")
    for table, columns in REQUIRED_COLUMNS.items():
        actual = {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}
        missing = sorted(columns - actual)
        if missing:
            raise CompactMigrationRequired(f"EVW v15 is missing {table} columns {missing}")
    if conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='schema_version'").fetchone()[0] != 1:
        raise CompactMigrationRequired("EVW v15 has no schema_version table")


def get_schema_version(conn: sqlite3.Connection) -> int | None:
    try:
        row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
    except sqlite3.OperationalError:
        return None
    return int(row[0]) if row is not None else None


def initialize_schema(conn: sqlite3.Connection, logger: DiagnosticLogger | None = None) -> None:
    current = get_schema_version(conn)
    if current is not None and current != SCHEMA_VERSION:
        raise CompactMigrationRequired(
            f"Runtime requires EVW schema v{SCHEMA_VERSION}; found v{current}. "
            "Run the explicit EVW migration tool."
        )
    if current is None:
        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
        ).fetchone()
        if table is not None:
            raise CompactMigrationRequired("EVW schema_version exists but has no valid v15 version row")
        conn.executescript(CREATE_TABLES_SQL)
        conn.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))
        conn.commit()
        return
    validate_v15_shape(conn)
    if logger is not None:
        logger.info(
            component="db.migrations",
            operation="schema_verified",
            message="EVW v15 schema verified; no runtime migration performed",
            details={"version": SCHEMA_VERSION},
        )
