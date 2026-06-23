"""Schema version and migration runner."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from message_evidence_workstation.db.fts_schema import MESSAGE_FTS_DDL
from message_evidence_workstation.db.schema import CREATE_TABLES_SQL
from message_evidence_workstation.embeddings.sqlite_vec_backend import ensure_chunk_metadata_schema
from message_evidence_workstation.nim.prompts import seed_default_prompts
from message_evidence_workstation.domain.constants import SCHEMA_VERSION

if TYPE_CHECKING:
    from message_evidence_workstation.logging_ui.process_log import ProcessLogger


def get_schema_version(conn: sqlite3.Connection) -> int | None:
    try:
        row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
    except sqlite3.OperationalError:
        return None
    if row is None:
        return None
    return int(row[0])


def initialize_schema(conn: sqlite3.Connection, logger: ProcessLogger) -> None:
    logger.info(
        component="db.migrations",
        operation="schema_init_start",
        message="Starting schema initialization",
        details={"target_version": SCHEMA_VERSION},
    )
    try:
        conn.executescript(CREATE_TABLES_SQL)
        conn.executescript(MESSAGE_FTS_DDL)
        ensure_chunk_metadata_schema(conn)
        current = get_schema_version(conn)
        if current is None:
            conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)",
                (SCHEMA_VERSION,),
            )
        elif current < SCHEMA_VERSION:
            _migrate_to_version(conn, logger, current, SCHEMA_VERSION)
            conn.execute(
                "UPDATE schema_version SET version = ?",
                (SCHEMA_VERSION,),
            )
        conn.commit()
        _ensure_workspace_metadata(conn)
        seed_default_prompts(conn, logger)
        logger.info(
            component="db.migrations",
            operation="schema_init_complete",
            message="Schema initialization completed",
            details={"version": SCHEMA_VERSION},
        )
    except Exception as exc:
        conn.rollback()
        logger.error(
            component="db.migrations",
            operation="schema_init_failed",
            message="Schema initialization failed",
            exc=exc,
        )
        raise


def _migrate_to_version(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    current: int,
    target: int,
) -> None:
    if current < 2 <= target:
        logger.info(
            component="db.migrations",
            operation="schema_migrate_v2",
            message="Applying schema migration to version 2",
            details={"from_version": current},
        )
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS workspace_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS evidence_block (
                evidence_block_id INTEGER PRIMARY KEY AUTOINCREMENT,
                dataset_id INTEGER NOT NULL,
                category_id INTEGER NOT NULL,
                source_thread_id TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                core_hit_message_id TEXT NOT NULL,
                context_start_slot INTEGER NOT NULL,
                relevant_start_slot INTEGER NOT NULL,
                relevant_end_slot INTEGER NOT NULL,
                context_end_slot INTEGER NOT NULL,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (dataset_id) REFERENCES dataset(dataset_id),
                FOREIGN KEY (category_id) REFERENCES category(category_id)
            );

            CREATE TABLE IF NOT EXISTS evidence_block_highlight (
                evidence_block_id INTEGER NOT NULL,
                message_id TEXT NOT NULL,
                PRIMARY KEY (evidence_block_id, message_id),
                FOREIGN KEY (evidence_block_id) REFERENCES evidence_block(evidence_block_id)
            );

            CREATE INDEX IF NOT EXISTS idx_evidence_block_dataset_thread
                ON evidence_block(dataset_id, source_thread_id);

            CREATE INDEX IF NOT EXISTS idx_evidence_block_category
                ON evidence_block(category_id);
            """
        )
    if current < 3 <= target:
        logger.info(
            component="db.migrations",
            operation="schema_migrate_v3",
            message="Applying schema migration to version 3",
            details={"from_version": current},
        )
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS transcript_session (
                session_id TEXT NOT NULL,
                dataset_id INTEGER NOT NULL,
                source_thread_id TEXT NOT NULL,
                session_index INTEGER NOT NULL,
                calendar_date TEXT NOT NULL,
                start_message_id TEXT NOT NULL,
                end_message_id TEXT NOT NULL,
                start_timestamp TEXT NOT NULL,
                end_timestamp TEXT NOT NULL,
                participants_json TEXT NOT NULL DEFAULT '[]',
                message_count INTEGER NOT NULL DEFAULT 0,
                title TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'built',
                summary_json TEXT NOT NULL DEFAULT '{}',
                summary_status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (dataset_id, session_id),
                FOREIGN KEY (dataset_id) REFERENCES dataset(dataset_id)
            );

            CREATE INDEX IF NOT EXISTS idx_transcript_session_dataset_thread
                ON transcript_session(dataset_id, source_thread_id, session_index);
            """
        )


def _ensure_workspace_metadata(conn: sqlite3.Connection) -> None:
    from message_evidence_workstation.db.workspace import get_workspace_metadata, seed_workspace_metadata

    if not get_workspace_metadata(conn):
        seed_workspace_metadata(conn, display_name="Evidence Workspace")
