"""Tests for virtual transcript height index."""

from __future__ import annotations

from message_evidence_workstation.ui.virtual_transcript_height_index import TranscriptHeightIndex


def test_height_index_total_and_offsets() -> None:
    index = TranscriptHeightIndex(5, default_height=10.0)
    assert index.total_height() == 50.0
    assert index.offset_for_ordinal(0) == 0.0
    assert index.offset_for_ordinal(3) == 30.0


def test_height_index_update_changes_total() -> None:
    index = TranscriptHeightIndex(4, default_height=10.0)
    index.set_height(1, 20.0)
    assert index.height_at(1) == 20.0
    assert index.total_height() == 50.0
    assert index.measured_count == 1


def test_height_index_offset_to_ordinal() -> None:
    index = TranscriptHeightIndex(3, default_height=10.0)
    index.set_height(1, 30.0)
    assert index.ordinal_for_offset(0.0) == 0
    assert index.ordinal_for_offset(15.0) == 1
    assert index.ordinal_for_offset(45.0) == 2


def test_height_index_invalidate_resets_measured() -> None:
    index = TranscriptHeightIndex(3, default_height=10.0)
    index.set_height(0, 25.0)
    index.invalidate_all(default_height=12.0)
    assert index.total_height() == 36.0
    assert index.measured_count == 0
