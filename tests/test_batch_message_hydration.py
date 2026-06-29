"""Batch message hydration repository tests (T52)."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.evidence_blocks import (
    create_evidence_block,
    ensure_uncategorized_category,
    fetch_highlights_for_blocks,
    list_evidence_blocks,
)
from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.db.repositories import fetch_messages_by_ids, list_messages_for_thread
from message_evidence_workstation.db.workspace import import_into_workspace
from message_evidence_workstation.logging_ui.process_log import ProcessLogger

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_dataset"


@pytest.fixture
def workspace_db(tmp_path):
    evw_path = tmp_path / "batch_hydration.evw"
    conn = connect(evw_path)
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    dataset_id = import_into_workspace(conn, logger, FIXTURE_DIR)
    return conn, logger, dataset_id


def test_fetch_messages_by_ids_empty_list(workspace_db) -> None:
    conn, _logger, dataset_id = workspace_db
    assert fetch_messages_by_ids(conn, dataset_id, []) == {}


def test_fetch_messages_by_ids_returns_map_with_metadata(workspace_db) -> None:
    conn, _logger, dataset_id = workspace_db
    metadata = {"thread_role": "parent", "import_tag": "t52"}
    conn.execute(
        """
        UPDATE message
        SET source_metadata_json = ?
        WHERE dataset_id = ? AND message_id = ?
        """,
        (json.dumps(metadata), dataset_id, "msg_003"),
    )
    conn.commit()

    messages = fetch_messages_by_ids(conn, dataset_id, ["msg_001", "msg_003", "missing"])
    assert set(messages) == {"msg_001", "msg_003"}
    assert messages["msg_001"].sender_display == "Art"
    assert messages["msg_003"].source_metadata_json == metadata


def test_fetch_messages_by_ids_chunks_in_clause(workspace_db) -> None:
    conn, _logger, dataset_id = workspace_db
    ordered_ids = [message.message_id for message in list_messages_for_thread(conn, dataset_id, "thread_001")]
    query_log: list[str] = []

    def trace(statement: str) -> None:
        if "FROM message" in statement and "message_id IN" in statement:
            query_log.append(statement)

    conn.set_trace_callback(trace)
    with patch("message_evidence_workstation.db.repositories._MESSAGE_IN_CHUNK_SIZE", 2):
        messages = fetch_messages_by_ids(conn, dataset_id, ordered_ids[:5])
    conn.set_trace_callback(None)

    assert len(messages) == 5
    assert len(query_log) == 3


def test_fetch_highlights_for_blocks_empty_list(workspace_db) -> None:
    conn, _logger, _dataset_id = workspace_db
    assert fetch_highlights_for_blocks(conn, []) == {}


def test_fetch_highlights_for_blocks_returns_map(workspace_db) -> None:
    conn, logger, dataset_id = workspace_db
    category = ensure_uncategorized_category(conn, logger, dataset_id)
    ordered_ids = [message.message_id for message in list_messages_for_thread(conn, dataset_id, "thread_001")]
    block_a = create_evidence_block(
        conn,
        logger,
        dataset_id=dataset_id,
        category_id=category.category_id,
        source_thread_id="thread_001",
        title="Block A",
        core_hit_message_id="msg_002",
        ordered_message_ids=ordered_ids,
        highlighted_message_ids=["msg_002"],
    )
    block_b = create_evidence_block(
        conn,
        logger,
        dataset_id=dataset_id,
        category_id=category.category_id,
        source_thread_id="thread_001",
        title="Block B",
        core_hit_message_id="msg_004",
        ordered_message_ids=ordered_ids,
        highlighted_message_ids=["msg_003", "msg_004"],
    )

    highlights = fetch_highlights_for_blocks(
        conn,
        [block_a.evidence_block_id, block_b.evidence_block_id, 99999],
    )
    assert highlights[block_a.evidence_block_id] == frozenset({"msg_002"})
    assert highlights[block_b.evidence_block_id] == frozenset({"msg_003", "msg_004"})
    assert highlights[99999] == frozenset()


def test_list_evidence_blocks_uses_single_highlight_query(workspace_db) -> None:
    conn, logger, dataset_id = workspace_db
    category = ensure_uncategorized_category(conn, logger, dataset_id)
    ordered_ids = [message.message_id for message in list_messages_for_thread(conn, dataset_id, "thread_001")]
    for index in range(3):
        create_evidence_block(
            conn,
            logger,
            dataset_id=dataset_id,
            category_id=category.category_id,
            source_thread_id="thread_001",
            title=f"Block {index}",
            core_hit_message_id=f"msg_00{index + 1}",
            ordered_message_ids=ordered_ids,
            highlighted_message_ids=[f"msg_00{index + 1}"],
        )

    query_log: list[str] = []

    def trace(statement: str) -> None:
        if "FROM evidence_block_highlight" in statement:
            query_log.append(statement)

    conn.set_trace_callback(trace)
    blocks = list_evidence_blocks(conn, dataset_id, source_thread_id="thread_001")
    conn.set_trace_callback(None)

    assert len(blocks) == 3
    assert len(query_log) == 1
