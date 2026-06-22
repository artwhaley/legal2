"""Repository fetch tests for source threads and messages."""

from pathlib import Path

import pytest

from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.db.repositories import list_messages_for_thread, list_source_threads
from message_evidence_workstation.importers.normalized_loader import load_normalized_dataset
from message_evidence_workstation.logging_ui.process_log import ProcessLogger


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_dataset"


@pytest.fixture
def repo_db(tmp_path):
    conn = connect(tmp_path / "test.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    dataset_id = load_normalized_dataset(conn, logger, FIXTURE_DIR)
    return conn, dataset_id


def test_list_source_threads(repo_db) -> None:
    conn, dataset_id = repo_db
    threads = list_source_threads(conn, dataset_id)
    assert len(threads) == 2
    assert {thread.source_thread_id for thread in threads} == {"thread_001", "thread_002"}


def test_list_messages_for_thread_order(repo_db) -> None:
    conn, dataset_id = repo_db
    messages = list_messages_for_thread(conn, dataset_id, "thread_002")
    assert [message.message_id for message in messages] == ["msg_004", "msg_005"]


def test_long_thread_remains_fetchable(repo_db) -> None:
    conn, dataset_id = repo_db
    for index in range(100):
        conn.execute(
            """
            INSERT INTO message (
                message_id, dataset_id, source_thread_id, source_platform,
                source_message_id, timestamp, sender_id, sender_display, body,
                body_normalized, has_attachment, attachment_summary, sort_index,
                source_metadata_json
            ) VALUES (?, ?, 'thread_001', 'facebook', ?, '2024-02-01T10:00:00+00:00',
                      'art', 'Art', ?, ?, 0, '', ?, '{}')
            """,
            (
                f"msg_bulk_{index}",
                dataset_id,
                f"bulk-{index}",
                f"bulk message {index}",
                f"bulk message {index}",
                100 + index,
            ),
        )
    conn.commit()
    messages = list_messages_for_thread(conn, dataset_id, "thread_001")
    assert len(messages) == 103
