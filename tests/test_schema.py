"""Schema initialization tests."""

import sqlite3

import pytest

from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.migrations import get_schema_version, initialize_schema
from message_evidence_workstation.domain.constants import SCHEMA_VERSION
from message_evidence_workstation.logging_ui.process_log import ProcessLogger


@pytest.fixture
def temp_conn(tmp_path):
    conn = connect(tmp_path / "test.db")
    yield conn
    conn.close()


def test_schema_creation_creates_core_tables(temp_conn: sqlite3.Connection) -> None:
    logger = ProcessLogger(temp_conn)
    initialize_schema(temp_conn, logger)
    tables = {
        row[0]
        for row in temp_conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    expected = {
        "schema_version",
        "dataset",
        "source_thread",
        "message",
        "category",
        "prompt_template",
        "model_run",
        "embedding_index_metadata",
        "message_spellfix_term",
        "process_log",
        "workspace_metadata",
        "evidence_block",
        "evidence_block_highlight",
        "printable_artifact_group",
        "printable_artifact",
        "printable_artifact_evidence_block",
    }
    assert expected.issubset(tables)
    assert get_schema_version(temp_conn) == SCHEMA_VERSION


def test_schema_init_is_idempotent(temp_conn: sqlite3.Connection) -> None:
    logger = ProcessLogger(temp_conn)
    initialize_schema(temp_conn, logger)
    initialize_schema(temp_conn, logger)
    assert get_schema_version(temp_conn) == SCHEMA_VERSION


def test_legacy_workstation_tables_absent_after_migrate(temp_conn: sqlite3.Connection) -> None:
    logger = ProcessLogger(temp_conn)
    temp_conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);
        INSERT INTO schema_version (version) VALUES (8);

        CREATE TABLE IF NOT EXISTS workstation_conversation (
            workstation_conversation_id INTEGER PRIMARY KEY AUTOINCREMENT,
            dataset_id INTEGER NOT NULL,
            category_id INTEGER NOT NULL,
            source_thread_id TEXT NOT NULL,
            primary_hit_message_id TEXT NOT NULL,
            title TEXT NOT NULL,
            user_notes TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS conversation_hit (
            conversation_hit_id INTEGER PRIMARY KEY AUTOINCREMENT,
            workstation_conversation_id INTEGER NOT NULL,
            message_id TEXT NOT NULL,
            retrieval_method TEXT NOT NULL,
            query_text TEXT NOT NULL DEFAULT '',
            matched_term TEXT NOT NULL DEFAULT '',
            score REAL,
            rank INTEGER,
            distance REAL,
            explanation TEXT NOT NULL DEFAULT '',
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS conversation_range (
            conversation_range_id INTEGER PRIMARY KEY AUTOINCREMENT,
            workstation_conversation_id INTEGER NOT NULL UNIQUE,
            lead_in_start_message_id TEXT,
            relevant_start_message_id TEXT,
            relevant_end_message_id TEXT,
            lead_out_end_message_id TEXT,
            llm_suggested_json TEXT NOT NULL DEFAULT '{}',
            user_modified INTEGER NOT NULL DEFAULT 0,
            locked INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS message_highlight_override (
            override_id INTEGER PRIMARY KEY AUTOINCREMENT,
            workstation_conversation_id INTEGER NOT NULL,
            message_id TEXT NOT NULL,
            highlight_state TEXT NOT NULL,
            user_modified INTEGER NOT NULL DEFAULT 1,
            UNIQUE (workstation_conversation_id, message_id)
        );
        """
    )
    initialize_schema(temp_conn, logger)
    tables = {
        row[0]
        for row in temp_conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    assert "workstation_conversation" not in tables
    assert "conversation_hit" not in tables
    assert "conversation_range" not in tables
    assert "message_highlight_override" not in tables
    assert get_schema_version(temp_conn) == SCHEMA_VERSION
