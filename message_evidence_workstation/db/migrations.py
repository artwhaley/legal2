"""Schema version and migration runner."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from message_evidence_workstation.db.schema import CREATE_TABLES_SQL
from message_evidence_workstation.embeddings.sqlite_vec_backend import ensure_chunk_metadata_schema
from message_evidence_workstation.nim.prompts import seed_default_prompts
from message_evidence_workstation.search.fts import ensure_fts_schema
from message_evidence_workstation.search.spellfix import ensure_spellfix_schema
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
        fts_recreated = ensure_fts_schema(conn)
        ensure_spellfix_schema(conn)
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
        if fts_recreated:
            _rebuild_fts_for_existing_datasets(conn, logger)
        if current is not None and current < 5 <= SCHEMA_VERSION:
            _rebuild_spellfix_for_existing_datasets(conn, logger)
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
    if current < 4 <= target:
        logger.info(
            component="db.migrations",
            operation="schema_migrate_v4",
            message="Applying schema migration to version 4",
            details={"from_version": current},
        )
    if current < 5 <= target:
        logger.info(
            component="db.migrations",
            operation="schema_migrate_v5",
            message="Applying schema migration to version 5",
            details={"from_version": current},
        )
    if current < 6 <= target:
        logger.info(
            component="db.migrations",
            operation="schema_migrate_v6",
            message="Applying schema migration to version 6 (printable artifacts)",
            details={"from_version": current},
        )
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS printable_artifact_group (
                printable_artifact_group_id INTEGER PRIMARY KEY AUTOINCREMENT,
                dataset_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0,
                is_collapsed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (dataset_id) REFERENCES dataset(dataset_id)
            );

            CREATE TABLE IF NOT EXISTS printable_artifact (
                printable_artifact_id INTEGER PRIMARY KEY AUTOINCREMENT,
                dataset_id INTEGER NOT NULL,
                group_id INTEGER NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                exhibit_number TEXT NOT NULL DEFAULT '',
                case_number TEXT NOT NULL DEFAULT '',
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (dataset_id) REFERENCES dataset(dataset_id),
                FOREIGN KEY (group_id) REFERENCES printable_artifact_group(printable_artifact_group_id)
            );

            CREATE TABLE IF NOT EXISTS printable_artifact_evidence_block (
                printable_artifact_evidence_block_id INTEGER PRIMARY KEY AUTOINCREMENT,
                printable_artifact_id INTEGER NOT NULL,
                evidence_block_id INTEGER NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (printable_artifact_id) REFERENCES printable_artifact(printable_artifact_id),
                FOREIGN KEY (evidence_block_id) REFERENCES evidence_block(evidence_block_id)
            );

            CREATE INDEX IF NOT EXISTS idx_printable_artifact_group_dataset
                ON printable_artifact_group(dataset_id, sort_order);

            CREATE INDEX IF NOT EXISTS idx_printable_artifact_group
                ON printable_artifact(group_id, sort_order);

            CREATE INDEX IF NOT EXISTS idx_printable_artifact_evidence_block_artifact
                ON printable_artifact_evidence_block(printable_artifact_id, sort_order);
            """
        )


def _ensure_workspace_metadata(conn: sqlite3.Connection) -> None:
    from message_evidence_workstation.db.workspace import get_workspace_metadata, seed_workspace_metadata

    if not get_workspace_metadata(conn):
        seed_workspace_metadata(conn, display_name="Evidence Workspace")


def _rebuild_fts_for_existing_datasets(conn: sqlite3.Connection, logger: ProcessLogger) -> None:
    from message_evidence_workstation.search.fts import rebuild_message_fts

    rows = conn.execute("SELECT dataset_id FROM dataset ORDER BY dataset_id").fetchall()
    for row in rows:
        dataset_id = int(row["dataset_id"])
        rebuild_message_fts(conn, logger, dataset_id)


def _rebuild_spellfix_for_existing_datasets(conn: sqlite3.Connection, logger: ProcessLogger) -> None:
    from message_evidence_workstation.search.spellfix import rebuild_spellfix_for_dataset

    rows = conn.execute("SELECT dataset_id FROM dataset ORDER BY dataset_id").fetchall()
    for row in rows:
        dataset_id = int(row["dataset_id"])
        rebuild_spellfix_for_dataset(conn, logger, dataset_id)
