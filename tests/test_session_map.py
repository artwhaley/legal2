"""Transcript session map tests (T5)."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.domain.models import Message
from message_evidence_workstation.embeddings.chunking import MessageChunkSpec
from message_evidence_workstation.importers.normalized_loader import load_normalized_dataset
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.search.session_map import (
    build_sessions_for_dataset,
    build_sessions_for_thread,
    list_sessions,
    rebuild_dataset_sessions,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_dataset"


@pytest.fixture
def session_db(tmp_path):
    conn = connect(tmp_path / "sessions.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    dataset_id = load_normalized_dataset(conn, logger, FIXTURE_DIR)
    return conn, logger, dataset_id


def _message(
    message_id: str,
    *,
    timestamp: str,
    sort_index: int,
    thread_id: str = "thread_test",
) -> Message:
    return Message(
        message_id=message_id,
        dataset_id=1,
        source_thread_id=thread_id,
        source_platform="sms",
        source_message_id=message_id,
        timestamp=timestamp,
        sender_id="alex",
        sender_display="Alex",
        body=f"body {message_id}",
        body_normalized=f"body {message_id}",
        has_attachment=False,
        attachment_summary="",
        sort_index=sort_index,
        source_metadata_json={},
    )


def test_build_sessions_splits_on_day_boundary() -> None:
    messages = [
        _message("msg_001", timestamp="2024-01-01T10:00:00", sort_index=0),
        _message("msg_002", timestamp="2024-01-01T11:00:00", sort_index=1),
        _message("msg_003", timestamp="2024-01-02T09:00:00", sort_index=2),
    ]
    sessions = build_sessions_for_thread(messages, dataset_id=1, source_thread_id="thread_test")
    assert len(sessions) == 2
    assert sessions[0].end_message_id == "msg_002"
    assert sessions[1].start_message_id == "msg_003"


def test_build_sessions_splits_on_inactivity_gap() -> None:
    base = datetime(2024, 1, 1, 10, 0, 0)
    messages = [
        _message("msg_001", timestamp=base.isoformat(), sort_index=0),
        _message(
            "msg_002",
            timestamp=(base + timedelta(hours=5)).isoformat(),
            sort_index=1,
        ),
    ]
    sessions = build_sessions_for_thread(
        messages,
        dataset_id=1,
        source_thread_id="thread_test",
        gap_minutes=60,
    )
    assert len(sessions) == 2


def test_rebuild_dataset_sessions_persists_without_duplicates(session_db) -> None:
    conn, logger, dataset_id = session_db
    first = rebuild_dataset_sessions(conn, logger, dataset_id, gap_minutes=120)
    second = rebuild_dataset_sessions(conn, logger, dataset_id, gap_minutes=120)
    assert first
    assert len(second) == len(first)
    rows = list_sessions(conn, dataset_id)
    assert len(rows) == len(first)
    assert len({row.session_id for row in rows}) == len(rows)


def test_build_sessions_for_dataset_uses_semantic_chunk_boundaries(session_db, monkeypatch) -> None:
    conn, _, dataset_id = session_db

    chunks = [
        MessageChunkSpec(
            source_thread_id="thread_001",
            start_message_id="msg_001",
            end_message_id="msg_003",
            message_count=3,
            char_count=100,
            text_checksum="a",
            body_text="chunk a",
        ),
        MessageChunkSpec(
            source_thread_id="thread_001",
            start_message_id="msg_004",
            end_message_id="msg_005",
            message_count=2,
            char_count=100,
            text_checksum="b",
            body_text="chunk b",
        ),
    ]

    monkeypatch.setattr(
        "message_evidence_workstation.search.session_map.iter_dataset_chunks",
        lambda *_args, **_kwargs: iter(chunks),
    )

    sessions = build_sessions_for_dataset(conn, dataset_id, use_semantic_chunks=True)

    assert [session.start_message_id for session in sessions] == ["msg_001", "msg_004"]
    assert [session.end_message_id for session in sessions] == ["msg_003", "msg_005"]


def test_fixture_dataset_builds_sessions(session_db) -> None:
    conn, logger, dataset_id = session_db
    sessions = list_sessions(conn, dataset_id)
    assert sessions
    assert all(session.message_count > 0 for session in sessions)
    assert sessions[0].session_id.startswith("thread_001__session_")
