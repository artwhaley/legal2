"""SQL dataset budget stats tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.importers.normalized_loader import load_normalized_dataset
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.search.date_scope import MessageDateScope
from message_evidence_workstation.search.dataset_budget import (
    DatasetBudgetStats,
    compute_dataset_budget_stats,
    estimate_transcript_tokens_from_stats,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_dataset"


@pytest.fixture
def budget_db(tmp_path):
    conn = connect(tmp_path / "budget.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    dataset_id = load_normalized_dataset(conn, logger, FIXTURE_DIR)
    return conn, dataset_id


def test_compute_dataset_budget_stats_on_fixture(budget_db) -> None:
    conn, dataset_id = budget_db
    stats = compute_dataset_budget_stats(conn, dataset_id)
    assert stats.message_count == 100
    assert stats.thread_count == 1
    assert stats.total_body_chars > 0
    assert stats.largest_thread_message_count == 100


# ── T99: scoped budget stats ─────────────────────────────────────────────

def test_compute_dataset_budget_stats_no_scope(budget_db) -> None:
    """Passing None or inactive scope returns full-dataset stats."""
    conn, dataset_id = budget_db
    full = compute_dataset_budget_stats(conn, dataset_id)
    none_scope = compute_dataset_budget_stats(conn, dataset_id, date_scope=None)
    inactive = compute_dataset_budget_stats(conn, dataset_id, date_scope=MessageDateScope())
    assert full.message_count == none_scope.message_count
    assert full.thread_count == none_scope.thread_count
    assert inactive.message_count == full.message_count


def test_scoped_budget_stats_start_only(budget_db) -> None:
    """Start-only bound excludes messages before the cutoff."""
    conn, dataset_id = budget_db
    scope = MessageDateScope(start_timestamp="2024-01-07T00:00:00+00:00")
    scoped = compute_dataset_budget_stats(conn, dataset_id, date_scope=scope)
    assert scoped.message_count >= 1
    assert scoped.message_count < 100
    assert scoped.thread_count >= 1
    assert scoped.total_body_chars > 0


def test_scoped_budget_stats_end_only(budget_db) -> None:
    """End-only bound excludes messages after the cutoff."""
    conn, dataset_id = budget_db
    scope = MessageDateScope(end_timestamp="2024-01-03T00:00:00+00:00")
    scoped = compute_dataset_budget_stats(conn, dataset_id, date_scope=scope)
    assert scoped.message_count >= 1
    assert scoped.message_count < 100
    assert scoped.thread_count >= 1


def test_scoped_budget_stats_inclusive_bounded(budget_db) -> None:
    """Inclusive start+end range returns correct subset."""
    conn, dataset_id = budget_db
    scope = MessageDateScope(
        start_timestamp="2024-01-03T00:00:00+00:00",
        end_timestamp="2024-01-05T23:59:59+00:00",
    )
    scoped = compute_dataset_budget_stats(conn, dataset_id, date_scope=scope)
    assert scoped.message_count >= 1
    assert scoped.message_count < 100

    # Verify that no message outside the range is counted.
    full = compute_dataset_budget_stats(conn, dataset_id)
    before = compute_dataset_budget_stats(
        conn, dataset_id, date_scope=MessageDateScope(end_timestamp="2024-01-02T23:59:59+00:00")
    )
    after = compute_dataset_budget_stats(
        conn, dataset_id, date_scope=MessageDateScope(start_timestamp="2024-01-16T00:00:00+00:00")
    )
    assert before.message_count + scoped.message_count + after.message_count <= full.message_count


def test_scoped_budget_stats_empty_range(budget_db) -> None:
    """A range with zero messages returns zero counts."""
    conn, dataset_id = budget_db
    scope = MessageDateScope(
        start_timestamp="2020-01-01T00:00:00+00:00",
        end_timestamp="2020-01-02T00:00:00+00:00",
    )
    scoped = compute_dataset_budget_stats(conn, dataset_id, date_scope=scope)
    assert scoped.message_count == 0
    assert scoped.thread_count == 0
    assert scoped.total_body_chars == 0
    assert scoped.total_body_normalized_chars == 0
    assert scoped.largest_thread_message_count == 0


def test_scoped_budget_stats_largest_thread_count_is_scoped(budget_db) -> None:
    """largest_thread_message_count respects the date scope."""
    conn, dataset_id = budget_db
    full = compute_dataset_budget_stats(conn, dataset_id)
    scope = MessageDateScope(
        start_timestamp="2024-01-03T00:00:00+00:00",
        end_timestamp="2024-01-05T23:59:59+00:00",
    )
    scoped = compute_dataset_budget_stats(conn, dataset_id, date_scope=scope)
    # The scoped largest thread message count should be <= the full count.
    assert scoped.largest_thread_message_count <= full.largest_thread_message_count


def test_token_estimator_includes_overhead_not_body_chars_only() -> None:
    body_only = DatasetBudgetStats(
        message_count=100,
        thread_count=1,
        total_body_chars=400,
        total_body_normalized_chars=400,
        largest_thread_message_count=100,
    )
    estimate = estimate_transcript_tokens_from_stats(body_only)
    assert estimate.message_overhead_chars == 100 * 48
    assert estimate.thread_overhead_chars == 64
    assert estimate.estimated_body_chars > body_only.total_body_chars
    assert estimate.estimated_tokens > body_only.total_body_chars // 4
