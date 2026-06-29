"""Token-bounded window planner tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.importers.normalized_loader import load_normalized_dataset
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.search.session_map import rebuild_dataset_sessions
from message_evidence_workstation.search.window_planner import (
    all_session_message_ids,
    build_token_bounded_windows,
    iter_thread_messages_for_window_planning,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_dataset"


@pytest.fixture
def planner_db(tmp_path):
    conn = connect(tmp_path / "planner.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    dataset_id = load_normalized_dataset(conn, logger, FIXTURE_DIR)
    sessions = rebuild_dataset_sessions(conn, logger, dataset_id, gap_minutes=30)
    return conn, logger, dataset_id, sessions


def test_small_session_produces_one_window(planner_db) -> None:
    conn, _logger, dataset_id, sessions = planner_db
    windows = build_token_bounded_windows(
        conn,
        dataset_id,
        sessions,
        target_tokens=50_000,
        overlap_messages=0,
        model_id="test-model",
    )
    assert len(windows) >= 1
    assert all(window.message_ids for window in windows)


def test_large_session_splits_by_token_target(planner_db) -> None:
    conn, logger, dataset_id, _sessions = planner_db
    large_sessions = rebuild_dataset_sessions(conn, logger, dataset_id, gap_minutes=24 * 60)
    windows = build_token_bounded_windows(
        conn,
        dataset_id,
        large_sessions,
        target_tokens=500,
        overlap_messages=0,
        model_id="test-model",
    )
    assert len(windows) > 1


def test_overlap_messages_are_included(planner_db) -> None:
    conn, logger, dataset_id, _sessions = planner_db
    large_sessions = rebuild_dataset_sessions(conn, logger, dataset_id, gap_minutes=24 * 60)
    no_overlap = build_token_bounded_windows(
        conn,
        dataset_id,
        large_sessions,
        target_tokens=500,
        overlap_messages=0,
        model_id="test-model",
    )
    with_overlap = build_token_bounded_windows(
        conn,
        dataset_id,
        large_sessions,
        target_tokens=500,
        overlap_messages=2,
        model_id="test-model",
    )
    assert len(with_overlap) >= len(no_overlap)


def test_no_message_loss(planner_db) -> None:
    conn, _logger, dataset_id, sessions = planner_db
    windows = build_token_bounded_windows(
        conn,
        dataset_id,
        sessions,
        target_tokens=500,
        overlap_messages=1,
        model_id="test-model",
    )
    expected_ids = set(all_session_message_ids(conn, dataset_id, sessions))
    covered_ids = {message_id for window in windows for message_id in window.message_ids}
    assert expected_ids.issubset(covered_ids)


def test_window_text_contains_message_ids(planner_db) -> None:
    conn, _logger, dataset_id, sessions = planner_db
    windows = build_token_bounded_windows(
        conn,
        dataset_id,
        sessions,
        target_tokens=50_000,
        overlap_messages=0,
        model_id="test-model",
    )
    window = windows[0]
    assert window.start_message_id in window.text
    assert window.end_message_id in window.text


def test_dataset_windowing_packs_full_thread_not_one_message_per_window(planner_db) -> None:
    conn, _logger, dataset_id, _sessions = planner_db
    from message_evidence_workstation.search.window_planner import build_token_bounded_windows_for_dataset

    windows = build_token_bounded_windows_for_dataset(
        conn,
        dataset_id,
        target_tokens=50_000,
        overlap_messages=0,
        model_id="test-model",
    )
    assert len(windows) == 1
    assert len(windows[0].message_ids) == 100


def test_large_budget_produces_fewer_windows_than_tiny_budget(planner_db) -> None:
    conn, _logger, dataset_id, _sessions = planner_db
    from message_evidence_workstation.search.window_planner import build_token_bounded_windows_for_dataset

    large_budget_windows = build_token_bounded_windows_for_dataset(
        conn,
        dataset_id,
        target_tokens=128_000,
        overlap_messages=0,
        model_id="test-model",
    )
    tiny_budget_windows = build_token_bounded_windows_for_dataset(
        conn,
        dataset_id,
        target_tokens=500,
        overlap_messages=0,
        model_id="test-model",
    )
    assert len(large_budget_windows) < len(tiny_budget_windows)


def test_streaming_planner_does_not_load_full_thread_list(planner_db, monkeypatch) -> None:
    conn, _logger, dataset_id, _sessions = planner_db
    from message_evidence_workstation.search import window_planner

    load_calls = 0
    original = window_planner.load_thread_messages

    def counting_load(*args, **kwargs):
        nonlocal load_calls
        load_calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(window_planner, "load_thread_messages", counting_load)
    window_planner.build_token_bounded_windows_for_dataset(
        conn,
        dataset_id,
        target_tokens=50_000,
        overlap_messages=0,
        model_id="test-model",
    )
    assert load_calls == 0


def test_streaming_planner_keyset_matches_timestamp_order(planner_db) -> None:
    conn, _logger, dataset_id, _sessions = planner_db
    conn.execute(
        """
        INSERT INTO source_thread (
            source_thread_id, dataset_id, source_platform, platform_thread_id,
            display_title, participant_summary, start_ts, end_ts, message_count,
            metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '{}')
        """,
        (
            "thread_keyset",
            dataset_id,
            "messenger",
            "thread-keyset",
            "Keyset Thread",
            "A",
            "2024-01-01T08:00:00+00:00",
            "2024-01-01T09:00:00+00:00",
            2,
        ),
    )
    conn.execute(
        """
        INSERT INTO message (
            message_id, dataset_id, source_thread_id, source_platform,
            source_message_id, timestamp, sender_id, sender_display, body,
            body_normalized, has_attachment, attachment_summary, sort_index,
            source_metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, '', ?, '{}')
        """,
        (
            "out_of_sort_early",
            dataset_id,
            "thread_keyset",
            "messenger",
            "k1",
            "2024-01-01T08:00:00+00:00",
            "a",
            "A",
            "early timestamp with high sort index",
            "early timestamp with high sort index",
            99,
        ),
    )
    conn.execute(
        """
        INSERT INTO message (
            message_id, dataset_id, source_thread_id, source_platform,
            source_message_id, timestamp, sender_id, sender_display, body,
            body_normalized, has_attachment, attachment_summary, sort_index,
            source_metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, '', ?, '{}')
        """,
        (
            "out_of_sort_late",
            dataset_id,
            "thread_keyset",
            "messenger",
            "k2",
            "2024-01-01T09:00:00+00:00",
            "a",
            "A",
            "later timestamp with low sort index",
            "later timestamp with low sort index",
            1,
        ),
    )
    conn.commit()

    messages = list(
        iter_thread_messages_for_window_planning(
            conn,
            dataset_id,
            "thread_keyset",
            batch_size=1,
        )
    )

    assert [message.message_id for message in messages] == [
        "out_of_sort_early",
        "out_of_sort_late",
    ]
