"""SQL-backed dataset statistics for answer mode budgeting."""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass

from message_evidence_workstation.search.date_scope import MessageDateScope, date_scope_sql_clauses
from message_evidence_workstation.search.transcript import CHARS_PER_TOKEN_ESTIMATE

# Conservative overhead for `[message_id] timestamp | sender: ` formatting per row.
PER_MESSAGE_FORMAT_OVERHEAD_CHARS = 48
# Thread header / separator overhead when multiple threads are serialized.
PER_THREAD_HEADER_OVERHEAD_CHARS = 64
# Favor exhaustive scan when estimate is uncertain.
ESTIMATOR_SAFETY_MARGIN = 1.15


@dataclass(slots=True)
class DatasetBudgetStats:
    message_count: int
    thread_count: int
    total_body_chars: int
    total_body_normalized_chars: int
    largest_thread_message_count: int


@dataclass(slots=True)
class TranscriptTokenEstimate:
    estimated_tokens: int
    method: str
    safety_margin: float
    estimated_body_chars: int
    message_overhead_chars: int
    thread_overhead_chars: int


def compute_dataset_budget_stats(
    conn: sqlite3.Connection,
    dataset_id: int,
    *,
    date_scope: MessageDateScope | None = None,
) -> DatasetBudgetStats:
    date_clause, date_params = date_scope_sql_clauses(date_scope)
    shared_params = (dataset_id,) + date_params
    summary_sql = f"""
        SELECT
            COUNT(*) AS message_count,
            COUNT(DISTINCT source_thread_id) AS thread_count,
            COALESCE(SUM(LENGTH(body)), 0) AS total_body_chars,
            COALESCE(SUM(LENGTH(body_normalized)), 0) AS total_body_normalized_chars
        FROM message
        WHERE dataset_id = ?
        {"AND " + date_clause if date_clause else ""}
        """
    summary = conn.execute(summary_sql, shared_params).fetchone()

    largest_sql = f"""
        SELECT COALESCE(MAX(thread_count), 0) AS largest_thread_message_count
        FROM (
            SELECT COUNT(*) AS thread_count
            FROM message
            WHERE dataset_id = ?
            {"AND " + date_clause if date_clause else ""}
            GROUP BY source_thread_id
        )
        """
    largest_row = conn.execute(largest_sql, shared_params).fetchone()
    return DatasetBudgetStats(
        message_count=int(summary["message_count"] or 0),
        thread_count=int(summary["thread_count"] or 0),
        total_body_chars=int(summary["total_body_chars"] or 0),
        total_body_normalized_chars=int(summary["total_body_normalized_chars"] or 0),
        largest_thread_message_count=int(largest_row["largest_thread_message_count"] or 0),
    )


def estimate_transcript_tokens_from_stats(stats: DatasetBudgetStats) -> TranscriptTokenEstimate:
    if stats.message_count <= 0:
        return TranscriptTokenEstimate(
            estimated_tokens=0,
            method="sql_aggregate_heuristic",
            safety_margin=ESTIMATOR_SAFETY_MARGIN,
            estimated_body_chars=0,
            message_overhead_chars=0,
            thread_overhead_chars=0,
        )
    message_overhead_chars = stats.message_count * PER_MESSAGE_FORMAT_OVERHEAD_CHARS
    thread_overhead_chars = stats.thread_count * PER_THREAD_HEADER_OVERHEAD_CHARS
    estimated_body_chars = stats.total_body_chars + message_overhead_chars + thread_overhead_chars
    raw_tokens = max(
        1,
        math.ceil(estimated_body_chars / CHARS_PER_TOKEN_ESTIMATE),
    )
    estimated_tokens = max(1, math.ceil(raw_tokens * ESTIMATOR_SAFETY_MARGIN))
    return TranscriptTokenEstimate(
        estimated_tokens=estimated_tokens,
        method="sql_aggregate_heuristic",
        safety_margin=ESTIMATOR_SAFETY_MARGIN,
        estimated_body_chars=estimated_body_chars,
        message_overhead_chars=message_overhead_chars,
        thread_overhead_chars=thread_overhead_chars,
    )
