"""SQL dataset budget stats tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.importers.normalized_loader import load_normalized_dataset
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
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
