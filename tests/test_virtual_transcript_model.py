"""Tests for virtual transcript SQL model."""

from __future__ import annotations

from pathlib import Path

import pytest

from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.domain.models import EvidenceBlock, Message
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.ui.transcript_data_source import InMemoryTranscriptDataSource
from message_evidence_workstation.ui.virtual_transcript_model import VirtualTranscriptModel, in_memory_model


def _sample_message(index: int, thread_id: str = "thread_large") -> Message:
    return Message(
        message_id=f"msg_{index:05d}",
        dataset_id=1,
        source_thread_id=thread_id,
        source_platform="facebook",
        source_message_id=f"s{index}",
        timestamp=f"2024-01-01T10:{index % 60:02d}:00+00:00",
        sender_id="a",
        sender_display="Alice",
        body=f"body {index}",
        body_normalized=f"body {index}",
        has_attachment=False,
        attachment_summary="",
        sort_index=index,
        source_metadata_json={},
        thread_ordinal=index,
    )


@pytest.fixture
def logger():
    conn = connect(Path(":memory:"))
    initialize_schema(conn, ProcessLogger(conn))
    conn.execute(
        """
        INSERT INTO dataset (dataset_id, name, created_at, schema_version)
        VALUES (1, 'test', '2024-01-01T00:00:00+00:00', 1)
        """
    )
    conn.commit()
    return ProcessLogger(conn)


def test_load_thread_does_not_hydrate_all_messages(logger) -> None:
    thread_id = "thread_large"
    messages = [_sample_message(index, thread_id) for index in range(15_000)]
    model = in_memory_model(
        logger.conn,
        logger,
        dataset_id=1,
        messages_by_thread={thread_id: messages},
    )
    model.load_thread(thread_id)
    assert model.message_count == 15_000
    assert model.cached_message_count() == 0
    assert model.fetch_count == 0


def test_messages_for_range_fetches_bounded_window(logger) -> None:
    thread_id = "thread_large"
    messages = [_sample_message(index, thread_id) for index in range(15_000)]
    model = in_memory_model(
        logger.conn,
        logger,
        dataset_id=1,
        messages_by_thread={thread_id: messages},
    )
    model.load_thread(thread_id)
    window = model.messages_for_range(100, 120)
    assert len(window) == 20
    assert window[0].message_id == "msg_00100"
    assert model.fetch_count == 1
    assert model.cached_message_count() == 20


def test_ordinal_and_message_id_lookup(logger) -> None:
    thread_id = "thread_large"
    messages = [_sample_message(index, thread_id) for index in range(100)]
    model = in_memory_model(
        logger.conn,
        logger,
        dataset_id=1,
        messages_by_thread={thread_id: messages},
    )
    model.load_thread(thread_id)
    assert model.ordinal_for_message_id("msg_00042") == 42
    assert model.message_id_for_ordinal(42) == "msg_00042"


def test_update_overlay_slots_only_affects_target_block(logger) -> None:
    thread_id = "thread_large"
    messages = [_sample_message(index, thread_id) for index in range(50)]
    blocks = [
        EvidenceBlock(
            evidence_block_id=1,
            dataset_id=1,
            category_id=1,
            source_thread_id=thread_id,
            title="Block A",
            summary="",
            core_hit_message_id="msg_00010",
            context_start_slot=8,
            relevant_start_slot=10,
            relevant_end_slot=11,
            context_end_slot=12,
            created_by="manual",
            created_at="2024-01-01T00:00:00+00:00",
            updated_at="2024-01-01T00:00:00+00:00",
            highlighted_message_ids=frozenset(),
        ),
        EvidenceBlock(
            evidence_block_id=2,
            dataset_id=1,
            category_id=1,
            source_thread_id=thread_id,
            title="Block B",
            summary="",
            core_hit_message_id="msg_00030",
            context_start_slot=28,
            relevant_start_slot=30,
            relevant_end_slot=31,
            context_end_slot=32,
            created_by="manual",
            created_at="2024-01-01T00:00:00+00:00",
            updated_at="2024-01-01T00:00:00+00:00",
            highlighted_message_ids=frozenset(),
        ),
    ]
    model = in_memory_model(
        logger.conn,
        logger,
        dataset_id=1,
        messages_by_thread={thread_id: messages},
        blocks_by_thread={thread_id: blocks},
    )
    model.load_thread(thread_id)
    model.update_overlay_slots(
        2,
        context_start=27,
        relevant_start=29,
        relevant_end=31,
        context_end=33,
    )
    overlay_a = model.overlay_for_block(1)
    overlay_b = model.overlay_for_block(2)
    assert overlay_a is not None
    assert overlay_b is not None
    assert overlay_a.relevant_start_slot == 10
    assert overlay_b.relevant_start_slot == 29


def test_overlay_containing_ordinal(logger) -> None:
    thread_id = "thread_large"
    messages = [_sample_message(index, thread_id) for index in range(50)]
    blocks = [
        EvidenceBlock(
            evidence_block_id=1,
            dataset_id=1,
            category_id=1,
            source_thread_id=thread_id,
            title="Block A",
            summary="",
            core_hit_message_id="msg_00010",
            context_start_slot=8,
            relevant_start_slot=10,
            relevant_end_slot=11,
            context_end_slot=12,
            created_by="manual",
            created_at="2024-01-01T00:00:00+00:00",
            updated_at="2024-01-01T00:00:00+00:00",
            highlighted_message_ids=frozenset(),
        ),
    ]
    model = in_memory_model(
        logger.conn,
        logger,
        dataset_id=1,
        messages_by_thread={thread_id: messages},
        blocks_by_thread={thread_id: blocks},
    )
    model.load_thread(thread_id)
    overlay = model.overlay_containing_ordinal(10)
    assert overlay is not None
    assert overlay.evidence_block_id == 1
    assert model.overlay_containing_ordinal(20) is None


def test_remove_evidence_block_from_model(logger) -> None:
    thread_id = "thread_large"
    messages = [_sample_message(index, thread_id) for index in range(20)]
    block = EvidenceBlock(
        evidence_block_id=1,
        dataset_id=1,
        category_id=1,
        source_thread_id=thread_id,
        title="Block",
        summary="",
        core_hit_message_id="msg_00005",
        context_start_slot=3,
        relevant_start_slot=5,
        relevant_end_slot=6,
        context_end_slot=8,
        created_by="manual",
        created_at="2024-01-01T00:00:00+00:00",
        updated_at="2024-01-01T00:00:00+00:00",
        highlighted_message_ids=frozenset(),
    )
    model = in_memory_model(
        logger.conn,
        logger,
        dataset_id=1,
        messages_by_thread={thread_id: messages},
        blocks_by_thread={thread_id: [block]},
    )
    model.load_thread(thread_id)
    model.remove_evidence_block(1)
    assert model.block_overlays() == []
    assert model.overlay_containing_ordinal(5) is None


def test_load_evidence_blocks_without_full_hydration(logger) -> None:
    thread_id = "thread_large"
    messages = [_sample_message(index, thread_id) for index in range(200)]
    block = EvidenceBlock(
        evidence_block_id=1,
        dataset_id=1,
        category_id=1,
        source_thread_id=thread_id,
        title="Block",
        summary="",
        core_hit_message_id="msg_00010",
        context_start_slot=8,
        relevant_start_slot=10,
        relevant_end_slot=11,
        context_end_slot=12,
        created_by="manual",
        created_at="2024-01-01T00:00:00+00:00",
        updated_at="2024-01-01T00:00:00+00:00",
        highlighted_message_ids=frozenset({"msg_00010"}),
    )
    model = in_memory_model(
        logger.conn,
        logger,
        dataset_id=1,
        messages_by_thread={thread_id: messages},
        blocks_by_thread={thread_id: [block]},
    )
    model.load_thread(thread_id)
    blocks = model.load_evidence_blocks()
    assert len(blocks) == 1
    assert model.cached_message_count() == 0


def test_load_thread_does_not_auto_activate_evidence_blocks(logger) -> None:
    thread_id = "thread_large"
    messages = [_sample_message(index, thread_id) for index in range(20)]
    block = EvidenceBlock(
        evidence_block_id=1,
        dataset_id=1,
        category_id=1,
        source_thread_id=thread_id,
        title="Block",
        summary="",
        core_hit_message_id="msg_00005",
        context_start_slot=3,
        relevant_start_slot=5,
        relevant_end_slot=6,
        context_end_slot=8,
        created_by="manual",
        created_at="2024-01-01T00:00:00+00:00",
        updated_at="2024-01-01T00:00:00+00:00",
        highlighted_message_ids=frozenset(),
    )
    model = in_memory_model(
        logger.conn,
        logger,
        dataset_id=1,
        messages_by_thread={thread_id: messages},
        blocks_by_thread={thread_id: [block]},
    )
    model.load_thread(thread_id)
    assert model.active_evidence_block_id is None
    assert model.active_overlay() is None
    assert len(model.block_overlays()) == 1
    assert model.message_zone(5) == "relevant"
