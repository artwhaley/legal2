"""Thread ordinal schema, backfill, and indexed transcript access (T64)."""

from pathlib import Path

import pytest

from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.migrations import get_schema_version, initialize_schema
from message_evidence_workstation.db.repositories import (
    backfill_thread_ordinals,
    fetch_messages_for_slot_range,
    message_ids_for_ordinal_range,
    message_index_in_thread,
    message_ordinal,
)
from message_evidence_workstation.db.workspace import import_into_workspace
from message_evidence_workstation.domain.constants import SCHEMA_VERSION
from message_evidence_workstation.logging_ui.process_log import ProcessLogger

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_dataset"


@pytest.fixture
def workspace_db(tmp_path):
    evw_path = tmp_path / "thread_ordinals.evw"
    conn = connect(evw_path)
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    dataset_id = import_into_workspace(conn, logger, FIXTURE_DIR)
    return conn, logger, dataset_id


def test_schema_includes_thread_ordinal_column(tmp_path) -> None:
    conn = connect(tmp_path / "schema.evw")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(message)").fetchall()}
    assert "thread_ordinal" in columns
    assert get_schema_version(conn) == SCHEMA_VERSION


def test_migration_from_v9_backfills_ordinals(tmp_path) -> None:
    conn = connect(tmp_path / "migrate_v9.evw")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);
        INSERT INTO schema_version (version) VALUES (9);

        CREATE TABLE IF NOT EXISTS dataset (
            dataset_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            schema_version INTEGER NOT NULL,
            notes TEXT NOT NULL DEFAULT '',
            import_validity TEXT NOT NULL DEFAULT 'ready',
            import_error TEXT NOT NULL DEFAULT '',
            normalized_format_version INTEGER
        );

        CREATE TABLE IF NOT EXISTS source_thread (
            source_thread_id TEXT NOT NULL,
            dataset_id INTEGER NOT NULL,
            source_platform TEXT NOT NULL,
            platform_thread_id TEXT NOT NULL,
            display_title TEXT NOT NULL,
            participant_summary TEXT NOT NULL DEFAULT '',
            start_ts TEXT NOT NULL,
            end_ts TEXT NOT NULL,
            message_count INTEGER NOT NULL DEFAULT 0,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            PRIMARY KEY (dataset_id, source_thread_id)
        );

        CREATE TABLE IF NOT EXISTS message (
            message_id TEXT NOT NULL,
            dataset_id INTEGER NOT NULL,
            source_thread_id TEXT NOT NULL,
            source_platform TEXT NOT NULL,
            source_message_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            sender_id TEXT NOT NULL,
            sender_display TEXT NOT NULL,
            body TEXT NOT NULL,
            body_normalized TEXT NOT NULL,
            has_attachment INTEGER NOT NULL DEFAULT 0,
            attachment_summary TEXT NOT NULL DEFAULT '',
            sort_index INTEGER NOT NULL,
            source_metadata_json TEXT NOT NULL DEFAULT '{}',
            PRIMARY KEY (dataset_id, message_id)
        );

        CREATE TABLE IF NOT EXISTS process_log (
            process_log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            dataset_id INTEGER,
            timestamp TEXT NOT NULL,
            severity TEXT NOT NULL,
            component TEXT NOT NULL,
            operation TEXT NOT NULL,
            message TEXT NOT NULL,
            details_json TEXT NOT NULL DEFAULT '{}',
            exception_type TEXT,
            stack_trace TEXT
        );

        INSERT INTO dataset (name, created_at, schema_version)
        VALUES ('legacy', '2024-01-01T00:00:00+00:00', 9);

        INSERT INTO source_thread (
            source_thread_id, dataset_id, source_platform, platform_thread_id,
            display_title, start_ts, end_ts, message_count
        ) VALUES ('thread_a', 1, 'facebook', 'p1', 'Thread A', '2024-01-01', '2024-01-02', 3);

        INSERT INTO message (
            message_id, dataset_id, source_thread_id, source_platform, source_message_id,
            timestamp, sender_id, sender_display, body, body_normalized, sort_index
        ) VALUES
            ('m1', 1, 'thread_a', 'facebook', 's1', '2024-01-01T10:00:00+00:00', 'a', 'A', 'one', 'one', 0),
            ('m2', 1, 'thread_a', 'facebook', 's2', '2024-01-01T10:01:00+00:00', 'a', 'A', 'two', 'two', 1),
            ('m3', 1, 'thread_a', 'facebook', 's3', '2024-01-01T10:02:00+00:00', 'a', 'A', 'three', 'three', 2);
        """
    )
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    assert get_schema_version(conn) == SCHEMA_VERSION
    rows = conn.execute(
        "SELECT message_id, thread_ordinal FROM message ORDER BY thread_ordinal"
    ).fetchall()
    assert [(row["message_id"], row["thread_ordinal"]) for row in rows] == [
        ("m1", 0),
        ("m2", 1),
        ("m3", 2),
    ]


def test_backfill_is_idempotent(workspace_db) -> None:
    conn, _logger, dataset_id = workspace_db
    first = backfill_thread_ordinals(conn, dataset_id)
    second = backfill_thread_ordinals(conn, dataset_id)
    assert first == 100
    assert second == 100
    rows = conn.execute(
        """
        SELECT message_id, thread_ordinal
        FROM message
        WHERE dataset_id = ? AND source_thread_id = 'thread_001'
        ORDER BY thread_ordinal
        """,
        (dataset_id,),
    ).fetchall()
    assert rows[0]["thread_ordinal"] == 0
    assert rows[-1]["thread_ordinal"] == 99


def test_indexed_slot_range_fetch(workspace_db) -> None:
    conn, _logger, dataset_id = workspace_db
    page = fetch_messages_for_slot_range(conn, dataset_id, "thread_001", 10, 15)
    assert [message.message_id for message in page] == [f"msg_{index:03d}" for index in range(11, 16)]
    assert all(message.thread_ordinal is not None for message in page)
    assert [message.thread_ordinal for message in page] == list(range(10, 15))


def test_message_ordinal_lookup_is_direct(workspace_db) -> None:
    conn, _logger, dataset_id = workspace_db
    assert message_ordinal(conn, dataset_id, "thread_001", "msg_010") == 9
    assert message_index_in_thread(conn, dataset_id, "thread_001", "msg_050") == 49
    assert message_ordinal(conn, dataset_id, "thread_001", "missing") is None


def test_message_ids_for_ordinal_range(workspace_db) -> None:
    conn, _logger, dataset_id = workspace_db
    ids = message_ids_for_ordinal_range(conn, dataset_id, "thread_001", 5, 8)
    assert ids == ["msg_006", "msg_007", "msg_008"]
