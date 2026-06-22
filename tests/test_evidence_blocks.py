"""Evidence block repository tests."""

from pathlib import Path

import pytest

from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.evidence_blocks import (
    create_evidence_block,
    create_evidence_block_from_search,
    ensure_uncategorized_category,
    get_evidence_block,
    list_evidence_blocks,
    move_evidence_block_to_category,
    set_evidence_block_highlights,
    update_evidence_block_slots,
)
from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.db.repositories import create_category, list_messages_for_thread
from message_evidence_workstation.db.workspace import import_into_workspace
from message_evidence_workstation.domain.constants import UNCATEGORIZED_CATEGORY_NAME
from message_evidence_workstation.domain.slots import validate_slot_bounds
from message_evidence_workstation.logging_ui.process_log import ProcessLogger

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_dataset"


@pytest.fixture
def workspace_db(tmp_path):
    evw_path = tmp_path / "blocks.evw"
    conn = connect(evw_path)
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    dataset_id = import_into_workspace(conn, logger, FIXTURE_DIR)
    return conn, logger, dataset_id


def test_uncategorized_category_is_created_on_import(workspace_db) -> None:
    conn, logger, dataset_id = workspace_db
    category = ensure_uncategorized_category(conn, logger, dataset_id)
    assert category.name == UNCATEGORIZED_CATEGORY_NAME
    again = ensure_uncategorized_category(conn, logger, dataset_id)
    assert again.category_id == category.category_id


def test_create_evidence_block_enforces_slot_invariant(workspace_db) -> None:
    conn, logger, dataset_id = workspace_db
    category = ensure_uncategorized_category(conn, logger, dataset_id)
    messages = list_messages_for_thread(conn, dataset_id, "thread_001")
    ordered_ids = [message.message_id for message in messages]
    block = create_evidence_block(
        conn,
        logger,
        dataset_id=dataset_id,
        category_id=category.category_id,
        source_thread_id="thread_001",
        title="Allergy mention",
        core_hit_message_id="msg_002",
        ordered_message_ids=ordered_ids,
        context_start_slot=0,
        relevant_start_slot=1,
        relevant_end_slot=2,
        context_end_slot=3,
        highlighted_message_ids=["msg_002"],
    )
    assert block.evidence_block_id > 0
    assert block.relevant_message_ids(ordered_ids) == ["msg_002"]
    assert block.leading_context_message_ids(ordered_ids) == ["msg_001"]
    assert block.trailing_context_message_ids(ordered_ids) == ["msg_003"]
    assert "msg_002" in block.highlighted_message_ids


def test_create_evidence_block_from_search_uses_uncategorized(workspace_db) -> None:
    conn, logger, dataset_id = workspace_db
    messages = list_messages_for_thread(conn, dataset_id, "thread_002")
    ordered_ids = [message.message_id for message in messages]
    block = create_evidence_block_from_search(
        conn,
        logger,
        dataset_id=dataset_id,
        source_thread_id="thread_002",
        primary_hit_message_id="msg_004",
        title="Pickup thread hit",
        ordered_message_ids=ordered_ids,
    )
    category = conn.execute(
        "SELECT name FROM category WHERE category_id = ?",
        (block.category_id,),
    ).fetchone()
    assert category["name"] == UNCATEGORIZED_CATEGORY_NAME


def test_update_slots_and_move_category(workspace_db) -> None:
    conn, logger, dataset_id = workspace_db
    uncategorized = ensure_uncategorized_category(conn, logger, dataset_id)
    work = create_category(conn, logger, dataset_id, "work")
    messages = list_messages_for_thread(conn, dataset_id, "thread_002")
    ordered_ids = [message.message_id for message in messages]
    block = create_evidence_block_from_search(
        conn,
        logger,
        dataset_id=dataset_id,
        source_thread_id="thread_002",
        primary_hit_message_id="msg_005",
        title="Pickup",
        ordered_message_ids=ordered_ids,
    )
    updated = update_evidence_block_slots(
        conn,
        logger,
        evidence_block_id=block.evidence_block_id,
        message_count=len(ordered_ids),
        context_start_slot=0,
        relevant_start_slot=0,
        relevant_end_slot=2,
        context_end_slot=2,
    )
    assert updated.relevant_message_ids(ordered_ids) == ordered_ids
    moved = move_evidence_block_to_category(
        conn,
        logger,
        evidence_block_id=block.evidence_block_id,
        category_id=work.category_id,
    )
    assert moved.category_id == work.category_id
    assert uncategorized.category_id != moved.category_id


def test_highlight_updates_persist(workspace_db) -> None:
    conn, logger, dataset_id = workspace_db
    category = ensure_uncategorized_category(conn, logger, dataset_id)
    messages = list_messages_for_thread(conn, dataset_id, "thread_001")
    ordered_ids = [message.message_id for message in messages]
    block = create_evidence_block_from_search(
        conn,
        logger,
        dataset_id=dataset_id,
        source_thread_id="thread_001",
        primary_hit_message_id="msg_001",
        title="Thread one",
        ordered_message_ids=ordered_ids,
    )
    updated = set_evidence_block_highlights(
        conn,
        logger,
        evidence_block_id=block.evidence_block_id,
        highlighted_message_ids=["msg_001", "msg_003"],
    )
    reloaded = get_evidence_block(conn, block.evidence_block_id)
    assert reloaded is not None
    assert updated.highlighted_message_ids == frozenset({"msg_001", "msg_003"})
    blocks = list_evidence_blocks(conn, dataset_id, source_thread_id="thread_001")
    assert len(blocks) >= 1


def test_validate_slot_bounds_rejects_invalid_ranges() -> None:
    with pytest.raises(ValueError):
        validate_slot_bounds(3, 0, 2, 1, 3)
