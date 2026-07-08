"""Transcript serialization tests (T1)."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.db.repositories import list_messages_for_thread
from message_evidence_workstation.domain.models import Message
from message_evidence_workstation.importers.normalized_loader import load_normalized_dataset
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.search.conversational_answer import build_dataset_transcript
from message_evidence_workstation.search.date_scope import MessageDateScope, date_scope_sql_clauses
from message_evidence_workstation.search.transcript import (
    estimate_token_count,
    load_dataset_messages,
    serialize_message_range,
    serialize_messages,
    serialize_thread_transcript,
    sort_messages_chronologically,
    transcript_fits_budget,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_dataset"


@pytest.fixture
def transcript_db(tmp_path):
    conn = connect(tmp_path / "transcript.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    dataset_id = load_normalized_dataset(conn, logger, FIXTURE_DIR)
    return conn, dataset_id


def _message(
    message_id: str,
    *,
    timestamp: str,
    sort_index: int,
    body: str = "hello",
    sender_display: str = "Alex",
) -> Message:
    return Message(
        message_id=message_id,
        dataset_id=1,
        source_thread_id="thread_test",
        source_platform="sms",
        source_message_id=message_id,
        timestamp=timestamp,
        sender_id="alex",
        sender_display=sender_display,
        body=body,
        body_normalized=body.lower(),
        has_attachment=False,
        attachment_summary="",
        sort_index=sort_index,
        source_metadata_json={},
    )


def test_sort_messages_chronologically_uses_timestamp_then_sort_index() -> None:
    messages = [
        _message("msg_b", timestamp="2024-01-02T10:00:00", sort_index=2),
        _message("msg_a", timestamp="2024-01-02T09:00:00", sort_index=1),
        _message("msg_c", timestamp="2024-01-02T10:00:00", sort_index=1),
    ]
    ordered = sort_messages_chronologically(messages)
    assert [message.message_id for message in ordered] == ["msg_a", "msg_c", "msg_b"]


def test_serialize_messages_includes_ids_timestamps_senders_and_bodies() -> None:
    messages = [
        _message("msg_001", timestamp="2024-01-02T13:00:00", sort_index=0, body="First"),
        _message("msg_002", timestamp="2024-01-02T14:00:00", sort_index=1, body="Second"),
    ]
    transcript = serialize_messages(messages)
    assert transcript.message_ids == ["msg_001", "msg_002"]
    assert "[msg_001] 2024-01-02 13:00 | Alex: First" in transcript.text
    assert "[msg_002] 2024-01-02 14:00 | Alex: Second" in transcript.text
    assert transcript.lines[0].sender_display == "Alex"
    assert transcript.char_count == len(transcript.text)
    assert transcript.approximate_token_count == estimate_token_count(transcript.char_count)


def test_empty_body_is_replaced_with_placeholder() -> None:
    messages = [_message("msg_001", timestamp="2024-01-02T13:00:00", sort_index=0, body="")]
    transcript = serialize_messages(messages)
    assert "(empty message)" in transcript.text


def test_load_dataset_messages_preserves_source_metadata(transcript_db) -> None:
    conn, dataset_id = transcript_db
    conn.execute(
        """
        UPDATE message
        SET source_metadata_json = ?
        WHERE dataset_id = ? AND message_id = 'msg_001'
        """,
        ('{"sha256":"abc","source_path":"/donor/messages/1.json"}', dataset_id),
    )
    conn.commit()
    messages = load_dataset_messages(conn, dataset_id)
    first = next(message for message in messages if message.message_id == "msg_001")
    assert first.source_metadata_json["sha256"] == "abc"
    transcript = serialize_messages([first])
    assert "sha256" not in transcript.text
    assert "/donor/messages/1.json" not in transcript.text


def test_multi_day_fixture_transcript_is_chronological(transcript_db) -> None:
    conn, dataset_id = transcript_db
    messages = load_dataset_messages(conn, dataset_id)
    transcript = serialize_messages(messages)
    timestamps = [line.display_timestamp for line in transcript.lines]
    assert timestamps == sorted(timestamps)
    assert transcript.message_ids[0] == "msg_001"
    assert len(transcript.message_ids) == 100


def test_serialize_thread_transcript_matches_thread_messages(transcript_db) -> None:
    conn, dataset_id = transcript_db
    thread_transcript = serialize_thread_transcript(conn, dataset_id, "thread_001")
    messages = list_messages_for_thread(conn, dataset_id, "thread_001")
    expected = serialize_messages(messages, source_thread_id="thread_001")
    assert thread_transcript.text == expected.text
    assert thread_transcript.message_ids == expected.message_ids


def test_serialize_message_range_inclusive_bounds() -> None:
    messages = [
        _message("msg_001", timestamp="2024-01-02T10:00:00", sort_index=0, body="one"),
        _message("msg_002", timestamp="2024-01-02T11:00:00", sort_index=1, body="two"),
        _message("msg_003", timestamp="2024-01-02T12:00:00", sort_index=2, body="three"),
    ]
    ranged = serialize_message_range(messages, start_message_id="msg_001", end_message_id="msg_003")
    assert ranged.message_ids == ["msg_001", "msg_002", "msg_003"]


def test_transcript_fits_budget() -> None:
    messages = [_message("msg_001", timestamp="2024-01-02T13:00:00", sort_index=0, body="x" * 20)]
    transcript = serialize_messages(messages)
    assert transcript_fits_budget(transcript, 1000)
    assert not transcript_fits_budget(transcript, 10)


# ── T99: scoped transcript loading ──────────────────────────────────────

def test_date_scope_sql_clauses_no_scope() -> None:
    """Inactive and None scope produce empty clause."""
    assert date_scope_sql_clauses(None) == ("", ())
    assert date_scope_sql_clauses(MessageDateScope()) == ("", ())


def test_date_scope_sql_clauses_start_only() -> None:
    clause, params = date_scope_sql_clauses(
        MessageDateScope(start_timestamp="2024-01-01T00:00:00+00:00")
    )
    assert clause == "timestamp >= ?"
    assert params == ("2024-01-01T00:00:00+00:00",)


def test_date_scope_sql_clauses_end_only() -> None:
    clause, params = date_scope_sql_clauses(
        MessageDateScope(end_timestamp="2024-01-31T23:59:59+00:00")
    )
    assert clause == "timestamp <= ?"
    assert params == ("2024-01-31T23:59:59+00:00",)


def test_date_scope_sql_clauses_both_bounds() -> None:
    clause, params = date_scope_sql_clauses(
        MessageDateScope(
            start_timestamp="2024-01-01T00:00:00+00:00",
            end_timestamp="2024-01-31T23:59:59+00:00",
        )
    )
    assert clause == "timestamp >= ? AND timestamp <= ?"
    assert params == ("2024-01-01T00:00:00+00:00", "2024-01-31T23:59:59+00:00")


def test_message_date_scope_is_active() -> None:
    assert not MessageDateScope().is_active
    assert not MessageDateScope(start_timestamp=None, end_timestamp=None).is_active
    assert MessageDateScope(start_timestamp="2024-01-01T00:00:00+00:00").is_active
    assert MessageDateScope(end_timestamp="2024-01-01T00:00:00+00:00").is_active
    assert MessageDateScope(
        start_timestamp="2024-01-01T00:00:00+00:00",
        end_timestamp="2024-01-31T23:59:59+00:00",
    ).is_active
    # Empty strings treated as unset (UI normalizes before reaching here).
    assert not MessageDateScope(start_timestamp="").is_active
    assert not MessageDateScope(end_timestamp="").is_active


def test_build_dataset_transcript_date_scoped(transcript_db) -> None:
    """build_dataset_transcript passes date_scope through to load_dataset_messages."""
    conn, dataset_id = transcript_db
    full = build_dataset_transcript(conn, dataset_id)
    assert len(full.message_ids) == 100
    scope = MessageDateScope(end_timestamp="2024-01-02T23:59:59+00:00")
    scoped = build_dataset_transcript(conn, dataset_id, date_scope=scope)
    assert 1 <= len(scoped.message_ids) < 100
    for message_id in scoped.message_ids:
        assert message_id in full.message_ids


def test_load_dataset_messages_no_scope_returns_all(transcript_db) -> None:
    conn, dataset_id = transcript_db
    messages = load_dataset_messages(conn, dataset_id)
    assert len(messages) == 100
    none_messages = load_dataset_messages(conn, dataset_id, date_scope=None)
    assert len(none_messages) == 100
    inactive = load_dataset_messages(conn, dataset_id, date_scope=MessageDateScope())
    assert len(inactive) == 100


def test_load_dataset_messages_start_only(transcript_db) -> None:
    conn, dataset_id = transcript_db
    scope = MessageDateScope(start_timestamp="2024-01-10T00:00:00+00:00")
    scoped = load_dataset_messages(conn, dataset_id, date_scope=scope)
    assert 1 <= len(scoped) < 100
    for message in scoped:
        assert message.timestamp >= scope.start_timestamp


def test_load_dataset_messages_end_only(transcript_db) -> None:
    conn, dataset_id = transcript_db
    scope = MessageDateScope(end_timestamp="2024-01-03T00:00:00+00:00")
    scoped = load_dataset_messages(conn, dataset_id, date_scope=scope)
    assert 1 <= len(scoped) < 100
    for message in scoped:
        assert message.timestamp <= scope.end_timestamp


def test_load_dataset_messages_inclusive_bounded(transcript_db) -> None:
    conn, dataset_id = transcript_db
    scope = MessageDateScope(
        start_timestamp="2024-01-03T00:00:00+00:00",
        end_timestamp="2024-01-05T23:59:59+00:00",
    )
    scoped = load_dataset_messages(conn, dataset_id, date_scope=scope)
    assert 1 <= len(scoped) < 100
    for message in scoped:
        assert message.timestamp >= scope.start_timestamp
        assert message.timestamp <= scope.end_timestamp
    # All messages are within dates Jan 3-5.
    all_ids = {message.message_id for message in scoped}
    full_messages = load_dataset_messages(conn, dataset_id)
    for message in full_messages:
        if message.timestamp < scope.start_timestamp or message.timestamp > scope.end_timestamp:
            assert message.message_id not in all_ids


def test_load_dataset_messages_empty_range(transcript_db) -> None:
    conn, dataset_id = transcript_db
    scope = MessageDateScope(
        start_timestamp="2020-01-01T00:00:00+00:00",
        end_timestamp="2020-01-02T00:00:00+00:00",
    )
    scoped = load_dataset_messages(conn, dataset_id, date_scope=scope)
    assert scoped == []


def test_multi_day_manual_messages_span_days() -> None:
    base = datetime(2024, 1, 1, 9, 0, 0)
    messages = [
        _message(
            f"msg_{index:03d}",
            timestamp=(base + timedelta(days=index)).isoformat(),
            sort_index=index,
            body=f"day {index}",
        )
        for index in range(3)
    ]
    transcript = serialize_messages(messages)
    assert "2024-01-01" in transcript.text
    assert "2024-01-03" in transcript.text
