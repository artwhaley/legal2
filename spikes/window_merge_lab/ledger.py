"""Deterministic evidence ledger builder for the unified synthesis strategy."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EvidenceLedgerRecord:
    range_id: str
    source_range_key: str
    source_batch_id: str
    source_thread_id: str
    input_title: str
    input_summary: str
    input_display_text: str
    date_description: str
    hit_message_id: str
    start_message_id: str
    end_message_id: str


@dataclass
class SourceBatchContext:
    source_batch_id: str
    source_thread_id: str
    summary: str


def build_ledger(
    source_batches: list[dict],
    *,
    record_key: str = "answer_ranges",
    summary_key: str = "answer_summary",
    batch_id_key: str = "window_id",
    thread_id_key: str = "source_thread_id",
) -> tuple[list[EvidenceLedgerRecord], list[SourceBatchContext]]:
    records: list[EvidenceLedgerRecord] = []
    batch_contexts: list[SourceBatchContext] = []

    for batch in source_batches:
        batch_id = str(batch.get(batch_id_key, ""))
        thread_id = str(batch.get(thread_id_key, ""))

        batch_summary = str(batch.get(summary_key, "") or "")
        if batch_summary:
            batch_contexts.append(SourceBatchContext(
                source_batch_id=batch_id,
                source_thread_id=thread_id,
                summary=batch_summary,
            ))

        for r in batch.get(record_key, []):
            if not isinstance(r, dict):
                continue
            title = str(r.get("title", ""))
            hit_id = str(r.get("hit_message_id", "") or "")
            records.append(EvidenceLedgerRecord(
                range_id="",
                source_range_key="",
                source_batch_id=batch_id,
                source_thread_id=thread_id,
                input_title=title,
                input_summary=str(r.get("summary", "") or ""),
                input_display_text=str(r.get("display_text", "") or ""),
                date_description=str(r.get("date_description", "") or ""),
                hit_message_id=str(r.get("hit_message_id", "") or ""),
                start_message_id=str(r.get("start_message_id", "") or ""),
                end_message_id=str(r.get("end_message_id", "") or ""),
            ))

    _assign_range_ids(records)
    return records, batch_contexts


def _assign_range_ids(records: list[EvidenceLedgerRecord]) -> None:
    for i, rec in enumerate(records, 1):
        rec.range_id = f"r{i:06d}"
        rec.source_range_key = (
            f"{rec.source_batch_id}::{rec.range_id}::{rec.hit_message_id}"
        )


def ledger_to_dicts(records: list[EvidenceLedgerRecord]) -> list[dict[str, Any]]:
    return [
        {
            "range_id": r.range_id,
            "source_range_key": r.source_range_key,
            "source_batch_id": r.source_batch_id,
            "source_thread_id": r.source_thread_id,
            "input_title": r.input_title,
            "input_summary": r.input_summary,
            "input_display_text": r.input_display_text,
            "date_description": r.date_description,
            "hit_message_id": r.hit_message_id,
            "start_message_id": r.start_message_id,
            "end_message_id": r.end_message_id,
        }
        for r in records
    ]


def batch_context_to_dicts(contexts: list[SourceBatchContext]) -> list[dict[str, Any]]:
    return [
        {
            "source_batch_id": c.source_batch_id,
            "source_thread_id": c.source_thread_id,
            "summary": c.summary,
        }
        for c in contexts
    ]
