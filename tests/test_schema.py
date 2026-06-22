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
        "workstation_conversation",
        "conversation_hit",
        "conversation_range",
        "message_highlight_override",
        "prompt_template",
        "model_run",
        "embedding_index_metadata",
        "process_log",
        "workspace_metadata",
        "evidence_block",
        "evidence_block_highlight",
    }
    assert expected.issubset(tables)
    assert get_schema_version(temp_conn) == SCHEMA_VERSION


def test_schema_init_is_idempotent(temp_conn: sqlite3.Connection) -> None:
    logger = ProcessLogger(temp_conn)
    initialize_schema(temp_conn, logger)
    initialize_schema(temp_conn, logger)
    assert get_schema_version(temp_conn) == SCHEMA_VERSION
