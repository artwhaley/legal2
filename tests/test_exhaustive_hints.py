"""Unit tests for exhaustive scan retrieval hints."""

from __future__ import annotations

from message_evidence_workstation.search.exhaustive_hints import (
    ExhaustiveHintBlock,
    ExhaustiveHintItem,
    _assign_blocks_to_windows,
    _merge_contiguous_hint_items,
    parse_exhaustive_scan_retrieval_terms,
)
from message_evidence_workstation.search.window_planner import TranscriptWindow


def test_parse_exhaustive_scan_retrieval_terms_accepts_strict_json() -> None:
    terms = parse_exhaustive_scan_retrieval_terms('{"terms":["school records","iep"]}')
    assert terms == ["school records", "iep"]


def test_parse_exhaustive_scan_retrieval_terms_rejects_non_json() -> None:
    try:
        parse_exhaustive_scan_retrieval_terms("school, iep")
    except ValueError as exc:
        assert "invalid JSON" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_merge_contiguous_hint_items_merges_adjacent_messages() -> None:
    blocks = _merge_contiguous_hint_items(
        [
            ExhaustiveHintItem(
                source="fts5",
                term="school",
                source_thread_id="thread_1",
                hit_message_id="m2",
                start_message_id="m2",
                end_message_id="m2",
            ),
            ExhaustiveHintItem(
                source="message_embedding",
                term="education",
                source_thread_id="thread_1",
                hit_message_id="m3",
                start_message_id="m3",
                end_message_id="m3",
            ),
        ],
        thread_message_ids={"thread_1": ["m1", "m2", "m3", "m4"]},
    )

    assert len(blocks) == 1
    assert blocks[0].start_message_id == "m2"
    assert blocks[0].end_message_id == "m3"
    assert blocks[0].hit_message_ids == ("m2", "m3")


def test_merge_contiguous_hint_items_does_not_merge_across_gap() -> None:
    blocks = _merge_contiguous_hint_items(
        [
            ExhaustiveHintItem(
                source="fts5",
                term="school",
                source_thread_id="thread_1",
                hit_message_id="m1",
                start_message_id="m1",
                end_message_id="m1",
            ),
            ExhaustiveHintItem(
                source="fts5",
                term="school",
                source_thread_id="thread_1",
                hit_message_id="m3",
                start_message_id="m3",
                end_message_id="m3",
            ),
        ],
        thread_message_ids={"thread_1": ["m1", "m2", "m3", "m4"]},
    )

    assert len(blocks) == 2
    assert [block.start_message_id for block in blocks] == ["m1", "m3"]


def test_assign_blocks_to_windows_clips_overlap_per_window() -> None:
    block = ExhaustiveHintBlock(
        source_thread_id="thread_1",
        start_message_id="m2",
        end_message_id="m5",
        hit_message_ids=("m2", "m4", "m5"),
        terms=("school",),
        sources=("fts5", "chunk_embedding"),
    )
    planned_windows = [
        TranscriptWindow(
            window_id="w1",
            source_thread_id="thread_1",
            start_message_id="m1",
            end_message_id="m3",
            message_ids=["m1", "m2", "m3"],
            estimated_tokens=10,
            text="",
        ),
        TranscriptWindow(
            window_id="w2",
            source_thread_id="thread_1",
            start_message_id="m4",
            end_message_id="m6",
            message_ids=["m4", "m5", "m6"],
            estimated_tokens=10,
            text="",
        ),
    ]

    assigned = _assign_blocks_to_windows(
        [block],
        planned_windows=planned_windows,
        thread_message_ids={"thread_1": ["m1", "m2", "m3", "m4", "m5", "m6"]},
    )

    assert assigned["w1"][0].start_message_id == "m2"
    assert assigned["w1"][0].end_message_id == "m3"
    assert assigned["w1"][0].hit_message_ids == ("m2",)
    assert assigned["w2"][0].start_message_id == "m4"
    assert assigned["w2"][0].end_message_id == "m5"
    assert assigned["w2"][0].hit_message_ids == ("m4", "m5")
