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
