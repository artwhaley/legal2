"""Conversational answer tests."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.importers.normalized_loader import load_normalized_dataset
from message_evidence_workstation.logging_ui.process_log import ProcessLogger, fetch_process_logs
from message_evidence_workstation.config.settings import (
    AnswerSettings,
    LEGACY_ANSWER_STRATEGIES,
    NimSettings,
    _normalize_answer_settings,
)
from tests.router_helpers import router_with_role_models
from message_evidence_workstation.nim.client import NimChatResult
from message_evidence_workstation.nim.prompts import (
    RUN_TYPE_EVIDENCE_LEDGER_SYNTHESIS,
    RUN_TYPE_EXHAUSTIVE_SCAN_RETRIEVAL_TERMS,
    RUN_TYPE_EXHAUSTIVE_WINDOW_MERGE,
    RUN_TYPE_EXHAUSTIVE_WINDOW_SCAN,
    RUN_TYPE_WHOLE_TRANSCRIPT_ANSWER,
)
from message_evidence_workstation.search.conversational_answer import (
    ANSWER_MODE_EXHAUSTIVE_WINDOW_SCAN,
    ANSWER_MODE_WHOLE_TRANSCRIPT,
    ANSWER_STRATEGY_EXHAUSTIVE_WINDOW_SCAN,
    ANSWER_STRATEGY_WHOLE_TRANSCRIPT,
    ConversationalAnswerParseError,
    build_dataset_transcript,
    build_whole_transcript_context_content,
    build_whole_transcript_query_content,
    build_whole_transcript_user_content,
    build_exhaustive_window_merge_user_content,
    parse_exhaustive_window_scan_response,
    parse_whole_transcript_answer_response,
    resolve_answer_budget,
    resolve_answer_mode,
    run_exhaustive_window_scan_answer,
    run_whole_transcript_answer,
)
from message_evidence_workstation.search.date_scope import MessageDateScope
from message_evidence_workstation.search.exhaustive_hints import ExhaustiveHintCollection
from message_evidence_workstation.search.dataset_budget import (
    DatasetBudgetStats,
    compute_dataset_budget_stats,
)
from message_evidence_workstation.search.transcript import serialize_thread_transcript
from message_evidence_workstation.search.window_planner import TranscriptWindow

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_dataset"


@pytest.fixture
def answer_db(tmp_path):
    conn = connect(tmp_path / "answer.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    dataset_id = load_normalized_dataset(conn, logger, FIXTURE_DIR)
    return conn, logger, dataset_id


EMPTY_HINT_COLLECTION = ExhaustiveHintCollection(
    planner_terms=(),
    all_blocks=(),
    window_blocks_by_id={},
)


def test_resolve_answer_budget_ignores_provider_metadata_without_user_setting(answer_db) -> None:
    conn, _, dataset_id = answer_db
    stats = compute_dataset_budget_stats(conn, dataset_id)
    settings = AnswerSettings(answer_strategy=ANSWER_STRATEGY_WHOLE_TRANSCRIPT)
    with pytest.raises(Exception):
        resolve_answer_budget(
            stats,
            settings,
            "nvidia/nemotron-mini-4b-instruct",
            nim_settings=NimSettings(),
            provider_metadata={"context_length": 4096},
        )


def test_resolve_answer_budget_unknown_default_uses_conservative_window(answer_db) -> None:
    conn, _, dataset_id = answer_db
    stats = compute_dataset_budget_stats(conn, dataset_id)
    settings = AnswerSettings(answer_strategy=ANSWER_STRATEGY_WHOLE_TRANSCRIPT)
    with pytest.raises(Exception):
        resolve_answer_budget(stats, settings, "vendor/unknown-model")


def test_resolve_answer_budget_whole_transcript_selects_whole_when_tokens_fit(answer_db) -> None:
    conn, _, dataset_id = answer_db
    stats = compute_dataset_budget_stats(conn, dataset_id)
    settings = AnswerSettings(answer_strategy=ANSWER_STRATEGY_WHOLE_TRANSCRIPT)
    budget = resolve_answer_budget(
        stats,
        settings,
        "test-model",
        nim_settings=NimSettings(context_window_tokens=1_000_000),
    )
    assert budget.decision == ANSWER_MODE_WHOLE_TRANSCRIPT


def test_resolve_answer_budget_whole_transcript_selects_exhaustive_when_tokens_do_not_fit(answer_db) -> None:
    conn, _, dataset_id = answer_db
    stats = compute_dataset_budget_stats(conn, dataset_id)
    settings = AnswerSettings(answer_strategy=ANSWER_STRATEGY_WHOLE_TRANSCRIPT)
    nim = NimSettings(context_window_tokens=500, max_output_tokens=100, prompt_overhead_tokens=100)
    budget = resolve_answer_budget(stats, settings, "test-model", nim_settings=nim)
    assert budget.decision == ANSWER_MODE_EXHAUSTIVE_WINDOW_SCAN


def test_resolve_answer_mode_whole_transcript_selects_whole_when_fits(answer_db) -> None:
    conn, _, dataset_id = answer_db
    stats = compute_dataset_budget_stats(conn, dataset_id)
    settings = AnswerSettings(answer_strategy=ANSWER_STRATEGY_WHOLE_TRANSCRIPT)
    mode = resolve_answer_mode(
        strategy=ANSWER_STRATEGY_WHOLE_TRANSCRIPT,
        stats=stats,
        answer_settings=settings,
        nim_settings=NimSettings(context_window_tokens=1_000_000),
        model_id="test-model",
    )
    assert mode == ANSWER_MODE_WHOLE_TRANSCRIPT


def test_resolve_answer_mode_whole_transcript_selects_exhaustive_when_too_large(answer_db) -> None:
    conn, _, dataset_id = answer_db
    stats = compute_dataset_budget_stats(conn, dataset_id)
    settings = AnswerSettings(answer_strategy=ANSWER_STRATEGY_WHOLE_TRANSCRIPT)
    nim = NimSettings(context_window_tokens=500, max_output_tokens=100, prompt_overhead_tokens=100)
    mode = resolve_answer_mode(
        strategy=ANSWER_STRATEGY_WHOLE_TRANSCRIPT,
        stats=stats,
        answer_settings=settings,
        nim_settings=nim,
        model_id="test-model",
    )
    assert mode == ANSWER_MODE_EXHAUSTIVE_WINDOW_SCAN


def test_char_limit_no_longer_controls_whole_transcript(answer_db) -> None:
    conn, _, dataset_id = answer_db
    stats = compute_dataset_budget_stats(conn, dataset_id)
    settings = AnswerSettings(answer_strategy=ANSWER_STRATEGY_WHOLE_TRANSCRIPT)
    mode = resolve_answer_mode(
        strategy=ANSWER_STRATEGY_WHOLE_TRANSCRIPT,
        stats=stats,
        answer_settings=settings,
        nim_settings=NimSettings(context_window_tokens=1_000_000),
        model_id="test-model",
    )
    assert mode == ANSWER_MODE_WHOLE_TRANSCRIPT


def test_resolve_answer_mode_explicit_strategies_still_work(answer_db) -> None:
    conn, _, dataset_id = answer_db
    stats = compute_dataset_budget_stats(conn, dataset_id)
    settings = AnswerSettings()
    nim = NimSettings(context_window_tokens=1_000_000)
    assert (
        resolve_answer_mode(
            strategy=ANSWER_STRATEGY_EXHAUSTIVE_WINDOW_SCAN,
            stats=stats,
            answer_settings=settings,
            nim_settings=nim,
            model_id="test-model",
        )
        == ANSWER_MODE_EXHAUSTIVE_WINDOW_SCAN
    )


def test_legacy_answer_strategies_normalize_to_whole_transcript() -> None:
    for legacy in LEGACY_ANSWER_STRATEGIES:
        normalized = _normalize_answer_settings({"answer_strategy": legacy})
        assert normalized.answer_strategy == ANSWER_STRATEGY_WHOLE_TRANSCRIPT


def test_resolve_answer_budget_never_returns_retrieval_fallback(answer_db) -> None:
    conn, _, dataset_id = answer_db
    stats = compute_dataset_budget_stats(conn, dataset_id)
    for strategy in (
        ANSWER_STRATEGY_WHOLE_TRANSCRIPT,
        ANSWER_STRATEGY_EXHAUSTIVE_WINDOW_SCAN,
    ):
        budget = resolve_answer_budget(
            stats,
            AnswerSettings(answer_strategy=strategy),
            "test-model",
            nim_settings=NimSettings(context_window_tokens=1_000_000),
        )
        assert budget.decision != "retrieval_fallback"


def test_resolve_answer_budget_huge_stats_select_exhaustive_scan() -> None:
    huge = DatasetBudgetStats(
        message_count=1_000_000,
        thread_count=10_000,
        total_body_chars=40_000_000,
        total_body_normalized_chars=40_000_000,
        largest_thread_message_count=50_000,
    )
    budget = resolve_answer_budget(
        huge,
        AnswerSettings(answer_strategy=ANSWER_STRATEGY_WHOLE_TRANSCRIPT),
        "test-model",
        nim_settings=NimSettings(context_window_tokens=128_000),
    )
    assert budget.decision == ANSWER_MODE_EXHAUSTIVE_WINDOW_SCAN


def test_build_whole_transcript_user_content_includes_full_transcript(answer_db) -> None:
    conn, _, dataset_id = answer_db
    transcript = build_dataset_transcript(conn, dataset_id)
    payload = json.loads(build_whole_transcript_user_content("allergy forms", transcript))
    assert payload["user_query"] == "allergy forms"
    assert payload["transcript"] == transcript.text
    assert len(payload["message_ids"]) == len(transcript.message_ids)
    assert "[msg_001]" in payload["transcript"]
    assert "[msg_100]" in payload["transcript"]
    keys = list(payload.keys())
    assert keys.index("user_query") > keys.index("transcript")


def test_build_whole_transcript_cache_payload_splits_context_and_query(answer_db) -> None:
    conn, _, dataset_id = answer_db
    transcript = build_dataset_transcript(conn, dataset_id)
    context = json.loads(build_whole_transcript_context_content(transcript))
    query = json.loads(build_whole_transcript_query_content("allergy forms"))
    assert "user_query" not in context
    assert query == {"user_query": "allergy forms"}
    assert context["transcript"] == transcript.text


def test_build_exhaustive_window_merge_user_content_reports_full_coverage(answer_db) -> None:
    conn, _logger, dataset_id = answer_db
    rows = conn.execute(
        "SELECT DISTINCT source_thread_id FROM message WHERE dataset_id = ? ORDER BY source_thread_id",
        (dataset_id,),
    ).fetchall()
    source_thread_ids = [str(row["source_thread_id"]) for row in rows]
    payload = json.loads(
        build_exhaustive_window_merge_user_content(
            "travel chess set",
            source_thread_ids=source_thread_ids,
            window_results=[
                {
                    "source_thread_id": source_thread_ids[0],
                    "message_ids": ["msg_001", "msg_003"],
                    "answer": "No relevant evidence.",
                    "cited_message_ids": [],
                    "candidate_evidence_blocks": [],
                    "uncertainties": [],
                }
                for _ in range(2)
            ],
        )
    )
    assert payload["coverage_summary"]["mode"] == ANSWER_MODE_EXHAUSTIVE_WINDOW_SCAN
    assert payload["coverage_summary"]["source_thread_ids"] == source_thread_ids
    assert payload["coverage_summary"]["windows_inspected"] == 2


def test_parse_whole_transcript_answer_response_valid() -> None:
    valid_ids = {"msg_001", "msg_002", "msg_003", "msg_004"}
    content = json.dumps(
        {
            "answer": "Alex mentioned allergy paperwork.",
            "cited_message_ids": ["msg_002", "msg_002"],
            "candidate_evidence_blocks": [
                {
                    "title": "Allergy mention",
                    "summary": "Allergy form discussion",
                    "core_message_id": "msg_002",
                    "relevant_start_message_id": "msg_001",
                    "relevant_end_message_id": "msg_003",
                    "leading_context_start_message_id": "msg_001",
                    "trailing_context_end_message_id": "msg_004",
                    "highlighted_message_ids": ["msg_002"],
                }
            ],
            "uncertainties": [],
            "coverage_summary": {
                "mode": "whole_transcript",
                "messages_considered": 4,
                "source_thread_ids": ["thread_001"],
            },
        }
    )
    result = parse_whole_transcript_answer_response(
        content,
        valid_message_ids=valid_ids,
        message_thread_by_id={
            "msg_001": "thread_001",
            "msg_002": "thread_001",
            "msg_003": "thread_001",
            "msg_004": "thread_001",
        },
        source_thread_ids=["thread_001"],
        messages_considered=4,
    )
    assert result.answer.startswith("Alex mentioned")
    assert result.cited_message_ids == ["msg_002"]
    assert len(result.candidate_evidence_blocks) == 1
    assert result.coverage_summary.mode == "whole_transcript"


def test_parse_whole_transcript_answer_response_accepts_answer_ranges() -> None:
    content = json.dumps(
        {
            "answer": "The allergy issue appears in one compact exchange.",
            "answer_summary": "The transcript contains one allergy-related exchange.",
            "answer_format": "detailed",
            "answer_ranges": [
                {
                    "title": "Allergy form and nurse call",
                    "summary": "Art asks about the school allergy form and Jane mentions Nurse Kim.",
                    "date_description": "On June 6, 2023",
                    "display_text": "Art and Jane discussed the school allergy form and Nurse Kim.",
                    "hit_message_id": "msg_002",
                    "start_message_id": "msg_001",
                    "end_message_id": "msg_003",
                }
            ],
            "uncertainties": [],
        }
    )
    result = parse_whole_transcript_answer_response(
        content,
        valid_message_ids={"msg_001", "msg_002", "msg_003", "msg_004", "msg_005", "msg_006"},
        message_thread_by_id={
            "msg_001": "thread_001",
            "msg_002": "thread_001",
            "msg_003": "thread_001",
            "msg_004": "thread_001",
            "msg_005": "thread_001",
            "msg_006": "thread_001",
        },
        source_thread_ids=["thread_001"],
        messages_considered=6,
        message_order_by_thread={
            "thread_001": ["msg_001", "msg_002", "msg_003", "msg_004", "msg_005", "msg_006"]
        },
    )

    assert len(result.answer_ranges) == 1
    answer_range = result.answer_ranges[0]
    assert answer_range.hit_message_id == "msg_002"
    assert answer_range.start_message_id == "msg_001"
    assert answer_range.end_message_id == "msg_003"
    assert answer_range.date_description == "On June 6, 2023"
    assert answer_range.display_text == "Art and Jane discussed the school allergy form and Nurse Kim."
    assert result.answer_summary == "The transcript contains one allergy-related exchange."
    assert result.answer_format == "detailed"
    candidate = result.candidate_evidence_blocks[0]
    assert candidate.core_message_id == "msg_002"
    assert candidate.relevant_start_message_id == "msg_001"
    assert candidate.relevant_end_message_id == "msg_003"
    assert candidate.leading_context_start_message_id == "msg_001"
    assert candidate.trailing_context_end_message_id == "msg_006"
    assert candidate.highlighted_message_ids == ["msg_002"]


def test_parse_whole_transcript_answer_response_rejects_invalid_answer_range() -> None:
    content = json.dumps(
        {
            "answer": "Invalid range should be skipped.",
            "answer_ranges": [
                {
                    "title": "Bad range",
                    "summary": "The hit is outside the selected range.",
                    "hit_message_id": "msg_004",
                    "start_message_id": "msg_001",
                    "end_message_id": "msg_003",
                }
            ],
            "uncertainties": [],
        }
    )
    result = parse_whole_transcript_answer_response(
        content,
        valid_message_ids={"msg_001", "msg_002", "msg_003", "msg_004"},
        message_thread_by_id={
            "msg_001": "thread_001",
            "msg_002": "thread_001",
            "msg_003": "thread_001",
            "msg_004": "thread_001",
        },
        source_thread_ids=["thread_001"],
        messages_considered=4,
        message_order_by_thread={"thread_001": ["msg_001", "msg_002", "msg_003", "msg_004"]},
    )

    assert len(result.answer_ranges) == 1
    assert result.answer_ranges[0].hit_message_id == "msg_004"
    assert result.answer_ranges[0].start_message_id == "msg_004"
    assert result.answer_ranges[0].end_message_id == "msg_004"
    assert result.answer_ranges[0].title == "Bad range"
    assert len(result.repaired_answer_ranges) == 1
    assert result.repaired_answer_ranges[0].reason == "range_order"
    assert result.repaired_answer_ranges[0].original_start_message_id == "msg_001"
    assert result.repaired_answer_ranges[0].original_end_message_id == "msg_003"
    assert result.repaired_answer_ranges[0].repaired_start_message_id == "msg_004"
    assert any("Repaired 1 range(s)" in item for item in result.uncertainties)


def test_parse_whole_transcript_answer_response_rejects_invented_ids() -> None:
    content = json.dumps(
        {
            "answer": "Claim with bad citation.",
            "cited_message_ids": ["msg_999"],
            "candidate_evidence_blocks": [],
            "uncertainties": [],
            "coverage_summary": {"mode": "whole_transcript", "messages_considered": 1, "source_thread_ids": []},
        }
    )
    result = parse_whole_transcript_answer_response(
        content,
        valid_message_ids={"msg_001"},
        message_thread_by_id={"msg_001": "thread_001"},
        source_thread_ids=["thread_001"],
        messages_considered=1,
    )
    assert result.cited_message_ids == []
    assert "msg_999" in result.removed_invalid_citation_ids
    assert result.uncertainties


def test_parse_whole_transcript_answer_response_malformed_json_raises() -> None:
    with pytest.raises(ConversationalAnswerParseError) as exc_info:
        parse_whole_transcript_answer_response(
            '{"answer":',
            valid_message_ids=set(),
            message_thread_by_id={},
            source_thread_ids=[],
            messages_considered=0,
        )
    assert "error_context" in exc_info.value.details
    assert exc_info.value.details["possibly_truncated"] is True


def test_parse_whole_transcript_answer_response_accepts_wrapped_json() -> None:
    content = """
    Here is the structured answer:
    {
      "answer": "Alex mentioned allergy paperwork.",
      "cited_message_ids": ["msg_001"],
      "candidate_evidence_blocks": [],
      "uncertainties": [],
      "coverage_summary": {
        "mode": "whole_transcript",
        "messages_considered": 1,
        "source_thread_ids": ["thread_001"],
      }
    }
    """
    result = parse_whole_transcript_answer_response(
        content,
        valid_message_ids={"msg_001"},
        message_thread_by_id={"msg_001": "thread_001"},
        source_thread_ids=["thread_001"],
        messages_considered=1,
    )
    assert result.cited_message_ids == ["msg_001"]


def test_run_whole_transcript_answer_passes_full_transcript_to_nim(answer_db) -> None:
    conn, logger, dataset_id = answer_db
    transcript = serialize_thread_transcript(conn, dataset_id, "thread_001")
    captured: dict[str, object] = {}

    def fake_run_nim_chat(_conn, _logger, _client, *, run_type, user_content=None, messages=None, dataset_id=None, **kwargs):
        captured["run_type"] = run_type
        captured["messages"] = messages
        assert user_content is None
        assert messages is not None
        context_payload = json.loads(messages[1]["content"])
        query_payload = json.loads(messages[2]["content"])
        return NimChatResult(
            content=json.dumps(
                {
                    "answer": "Found allergy paperwork references.",
                    "cited_message_ids": ["msg_002"],
                    "candidate_evidence_blocks": [],
                    "uncertainties": [],
                    "coverage_summary": {
                        "mode": "whole_transcript",
                        "messages_considered": len(context_payload["message_ids"]),
                        "source_thread_ids": context_payload["source_thread_ids"],
                    },
                }
            ),
            raw_response={},
            latency_ms=1,
        )

    router = router_with_role_models()
    with patch(
        "message_evidence_workstation.search.conversational_answer.run_nim_chat",
        side_effect=fake_run_nim_chat,
    ):
        result = run_whole_transcript_answer(
            conn,
            logger,
            router,
            user_query="allergy paperwork",
            dataset_id=dataset_id,
            transcript=transcript,
        )
    assert captured["run_type"] == RUN_TYPE_WHOLE_TRANSCRIPT_ANSWER
    messages = captured["messages"]
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert messages[2]["role"] == "user"
    context_payload = json.loads(messages[1]["content"])
    query_payload = json.loads(messages[2]["content"])
    assert context_payload["transcript"] == transcript.text
    assert query_payload["user_query"] == "allergy paperwork"
    assert len(context_payload["transcript"].splitlines()) == 100
    assert result.mode == ANSWER_MODE_WHOLE_TRANSCRIPT
    assert result.cited_message_ids == ["msg_002"]


def test_run_exhaustive_window_scan_answer_inspects_every_planned_window(answer_db) -> None:
    conn, logger, dataset_id = answer_db
    from message_evidence_workstation.config.settings import AnswerSettings, NimSettings
    from message_evidence_workstation.nim.prompts import (
        RUN_TYPE_EVIDENCE_LEDGER_SYNTHESIS,
        RUN_TYPE_EXHAUSTIVE_WINDOW_SCAN,
    )

    answer_settings = AnswerSettings()
    nim_settings = NimSettings(
        context_window_tokens=1_000_000,
        max_output_tokens=4096,
        window_overlap_messages=2,
    )
    calls: list[tuple[str, dict, dict]] = []
    scan_count = 0
    planned_windows = [
        TranscriptWindow(
            window_id="thread_001__window_001",
            source_thread_id="thread_001",
            start_message_id="msg_001",
            end_message_id="msg_003",
            message_ids=["msg_001", "msg_002", "msg_003"],
            estimated_tokens=200,
            text="window 1",
        ),
        TranscriptWindow(
            window_id="thread_001__window_002",
            source_thread_id="thread_001",
            start_message_id="msg_004",
            end_message_id="msg_006",
            message_ids=["msg_004", "msg_005", "msg_006"],
            estimated_tokens=200,
            text="window 2",
        ),
    ]

    def fake_run_nim_chat(_conn, _logger, _client, *, run_type, user_content=None, messages=None, dataset_id=None, **kwargs):
        nonlocal scan_count
        if run_type == RUN_TYPE_EXHAUSTIVE_WINDOW_SCAN:
            payload = json.loads(user_content)
            calls.append((run_type, payload, kwargs))
            n = payload["messages_considered"]
            offset = scan_count * 3
            ids = [f"msg_{offset + i + 1:03d}" for i in range(n)]
            scan_count += 1
            assert "window_id" in payload
            assert "estimated_tokens" in payload
            return NimChatResult(
                content=json.dumps(
                    {
                        "answer": "Window inspected.",
                        "answer_summary": f"Findings for {payload['window_id']}.",
                        "cited_message_ids": [ids[1]],
                        "answer_ranges": [
                            {
                                "title": f"Evidence in {payload['window_id']}",
                                "summary": "Relevant evidence from this window.",
                                "display_text": "Relevant evidence from this window.",
                                "date_description": "On Jan 1",
                                "hit_message_id": ids[1],
                                "start_message_id": ids[0],
                                "end_message_id": ids[-1],
                            }
                        ],
                        "uncertainties": [],
                        "coverage_summary": {
                            "mode": "exhaustive_window_scan",
                            "messages_considered": n,
                            "source_thread_ids": [payload["source_thread_id"]],
                        },
                    }
                ),
                raw_response={},
                latency_ms=1,
            )
        assert run_type == RUN_TYPE_EVIDENCE_LEDGER_SYNTHESIS
        assert messages is not None
        payload = json.loads(messages[1]["content"])
        calls.append((run_type, payload, kwargs))
        assert scan_count > 0
        assert len(payload["ledger_records"]) == scan_count
        assert payload["record_count"] == scan_count
        return NimChatResult(
            content=json.dumps(
                {
                    "answer_summary": "Evidence-ledger synthesis result.",
                    "answer": "Merged exhaustive scan answer with enough detail to pass validation.",
                    "themes": [],
                    "notable_patterns": [],
                    "contradictions_or_tensions": [],
                    "uncertainties": [],
                }
            ),
            raw_response={},
            latency_ms=1,
        )

    router = router_with_role_models()
    with (
        patch(
            "message_evidence_workstation.search.conversational_answer.run_nim_chat",
            side_effect=fake_run_nim_chat,
        ),
        patch(
            "message_evidence_workstation.search.conversational_answer.collect_exhaustive_window_hints",
            return_value=EMPTY_HINT_COLLECTION,
        ),
        patch(
            "message_evidence_workstation.search.conversational_answer.build_token_bounded_windows_for_dataset",
            return_value=planned_windows,
        ),
    ):
        result = run_exhaustive_window_scan_answer(
            conn,
            logger,
            router,
            user_query="travel chess set",
            dataset_id=dataset_id,
            answer_settings=answer_settings,
            nim_settings=nim_settings,
            max_tokens=nim_settings.max_output_tokens,
        )

    scan_calls = [call for call in calls if call[0] == RUN_TYPE_EXHAUSTIVE_WINDOW_SCAN]
    assert len(scan_calls) == scan_count
    assert scan_count > 0
    assert all(call[2].get("max_tokens") == nim_settings.max_output_tokens for call in scan_calls)
    merge_calls = [call for call in calls if call[0] == RUN_TYPE_EVIDENCE_LEDGER_SYNTHESIS]
    assert len(merge_calls) == 1
    assert merge_calls[0][2].get("max_tokens") == nim_settings.max_output_tokens
    assert result.mode == ANSWER_MODE_EXHAUSTIVE_WINDOW_SCAN
    assert result.coverage_summary.windows_inspected == scan_count
    assert result.coverage_summary.token_budget is not None
    window_logs = [
        entry
        for entry in fetch_process_logs(conn, component="search.conversational_answer", limit=50)
        if entry.operation == "exhaustive_window_scan_window_completed"
    ]
    assert len(window_logs) == scan_count
    details_by_window = {entry.details_json["window_id"]: entry.details_json for entry in window_logs}
    assert details_by_window["thread_001__window_001"]["raw_answer_range_count"] == 1
    assert details_by_window["thread_001__window_001"]["validated_answer_range_count"] == 1
    assert details_by_window["thread_001__window_002"]["raw_answer_range_count"] == 1
    totals_log = next(
        entry
        for entry in fetch_process_logs(conn, component="search.conversational_answer", limit=50)
        if entry.operation == "exhaustive_window_scan_windows_completed"
    )
    assert totals_log.details_json["raw_answer_range_count_total"] == scan_count
    assert totals_log.details_json["validated_answer_range_count_total"] == scan_count
    ledger_log = next(
        entry
        for entry in fetch_process_logs(conn, component="search.conversational_answer", limit=50)
        if entry.operation == "evidence_ledger_built"
    )
    assert ledger_log.details_json["entry_count"] == scan_count
    assert ledger_log.details_json["raw_answer_range_count_total"] == scan_count
    assert ledger_log.details_json["validated_answer_range_count_total"] == scan_count


def test_run_exhaustive_window_scan_answer_legacy_merge_path(answer_db) -> None:
    conn, logger, dataset_id = answer_db
    answer_settings = AnswerSettings(use_evidence_ledger_merge=False)
    nim_settings = NimSettings(
        context_window_tokens=1_000_000,
        max_output_tokens=4096,
        window_overlap_messages=2,
    )
    calls: list[tuple[str, dict, dict]] = []
    planned_windows = [
        TranscriptWindow(
            window_id="thread_001__window_001",
            source_thread_id="thread_001",
            start_message_id="msg_001",
            end_message_id="msg_003",
            message_ids=["msg_001", "msg_002", "msg_003"],
            estimated_tokens=200,
            text="window 1",
        ),
        TranscriptWindow(
            window_id="thread_001__window_002",
            source_thread_id="thread_001",
            start_message_id="msg_004",
            end_message_id="msg_006",
            message_ids=["msg_004", "msg_005", "msg_006"],
            estimated_tokens=200,
            text="window 2",
        ),
    ]

    scan_mock_count = 0

    def fake_run_nim_chat(_conn, _logger, _client, *, run_type, user_content=None, messages=None, dataset_id=None, **kwargs):
        nonlocal scan_mock_count
        if run_type == RUN_TYPE_EXHAUSTIVE_WINDOW_SCAN:
            payload = json.loads(user_content)
            calls.append((run_type, payload, kwargs))
            n = payload["messages_considered"]
            offset = scan_mock_count * 3
            ids = [f"msg_{offset + i + 1:03d}" for i in range(n)]
            scan_mock_count += 1
            return NimChatResult(
                content=json.dumps(
                    {
                        "answer": "Window inspected.",
                        "answer_summary": f"Findings for {payload['window_id']}.",
                        "cited_message_ids": [ids[1]],
                        "answer_ranges": [
                            {
                                "title": f"Evidence in {payload['window_id']}",
                                "summary": "Relevant evidence from this window.",
                                "display_text": "Relevant evidence from this window.",
                                "date_description": "On Jan 1",
                                "hit_message_id": ids[1],
                                "start_message_id": ids[0],
                                "end_message_id": ids[-1],
                            }
                        ],
                        "uncertainties": [],
                        "coverage_summary": {
                            "mode": "exhaustive_window_scan",
                            "messages_considered": n,
                            "source_thread_ids": [payload["source_thread_id"]],
                        },
                    }
                ),
                raw_response={},
                latency_ms=1,
            )

        assert run_type == RUN_TYPE_EXHAUSTIVE_WINDOW_MERGE
        payload = json.loads(user_content)
        calls.append((run_type, payload, kwargs))
        return NimChatResult(
            content=json.dumps(
                {
                    "answer": "Merged exhaustive scan answer.",
                    "cited_message_ids": [],
                    "candidate_evidence_blocks": [],
                    "uncertainties": [],
                    "coverage_summary": payload["coverage_summary"],
                }
            ),
            raw_response={},
            latency_ms=1,
        )

    router = router_with_role_models()
    with (
        patch(
            "message_evidence_workstation.search.conversational_answer.run_nim_chat",
            side_effect=fake_run_nim_chat,
        ),
        patch(
            "message_evidence_workstation.search.conversational_answer.collect_exhaustive_window_hints",
            return_value=EMPTY_HINT_COLLECTION,
        ),
        patch(
            "message_evidence_workstation.search.conversational_answer.build_token_bounded_windows_for_dataset",
            return_value=planned_windows,
        ),
    ):
        result = run_exhaustive_window_scan_answer(
            conn,
            logger,
            router,
            user_query="travel chess set",
            dataset_id=dataset_id,
            answer_settings=answer_settings,
            nim_settings=nim_settings,
            max_tokens=nim_settings.max_output_tokens,
        )

    assert any(call[0] == RUN_TYPE_EXHAUSTIVE_WINDOW_MERGE for call in calls)
    assert not any(call[0] == RUN_TYPE_EVIDENCE_LEDGER_SYNTHESIS for call in calls)
    assert result.mode == ANSWER_MODE_EXHAUSTIVE_WINDOW_SCAN


def test_exhaustive_window_scan_allows_empty_answer_for_no_evidence() -> None:
    result = parse_exhaustive_window_scan_response(
        json.dumps(
            {
                "answer": "",
                "cited_message_ids": [],
                "candidate_evidence_blocks": [],
                "uncertainties": ["No relevant evidence found in the provided window"],
                "coverage_summary": {
                    "mode": "exhaustive_window_scan",
                    "messages_considered": 1,
                    "source_thread_ids": ["thread_001"],
                },
            }
        ),
        valid_message_ids={"msg_001"},
        message_thread_by_id={"msg_001": "thread_001"},
        source_thread_ids=["thread_001"],
        messages_considered=1,
    )

    assert result.answer == ""
    assert result.candidate_evidence_blocks == []
    assert result.uncertainties == ["No relevant evidence found in the provided window"]


def test_whole_transcript_answer_passes_max_output_tokens(answer_db) -> None:
    conn, logger, dataset_id = answer_db
    transcript = build_dataset_transcript(conn, dataset_id)
    captured: dict[str, object] = {}

    def fake_run_nim_chat(_conn, _logger, _client, *, run_type, user_content=None, messages=None, dataset_id=None, **kwargs):
        captured["max_tokens"] = kwargs.get("max_tokens")
        return NimChatResult(
            content=json.dumps(
                {
                    "answer": "ok",
                    "cited_message_ids": [],
                    "candidate_evidence_blocks": [],
                    "uncertainties": [],
                    "coverage_summary": {
                        "mode": "whole_transcript",
                        "messages_considered": len(transcript.message_ids),
                        "source_thread_ids": [],
                    },
                }
            ),
            raw_response={},
            latency_ms=1,
        )

    router = router_with_role_models()
    with patch(
        "message_evidence_workstation.search.conversational_answer.run_nim_chat",
        side_effect=fake_run_nim_chat,
    ):
        run_whole_transcript_answer(
            conn,
            logger,
            router,
            user_query="allergy",
            dataset_id=dataset_id,
            transcript=transcript,
            max_tokens=8192,
        )
    assert captured["max_tokens"] == 8192


def test_answer_budget_log_written(answer_db) -> None:
    conn, logger, dataset_id = answer_db
    from message_evidence_workstation.search.conversational_answer import log_answer_budget_resolved

    stats = compute_dataset_budget_stats(conn, dataset_id)
    settings = AnswerSettings(answer_strategy=ANSWER_STRATEGY_WHOLE_TRANSCRIPT)
    budget = resolve_answer_budget(
        stats,
        settings,
        "test-model",
        nim_settings=NimSettings(context_window_tokens=1_000_000),
    )
    log_answer_budget_resolved(
        logger,
        budget=budget,
        dataset_id=dataset_id,
        strategy=settings.answer_strategy,
        stats=stats,
    )
    row = conn.execute(
        "SELECT operation FROM process_log WHERE operation = 'answer_budget_resolved' ORDER BY process_log_id DESC LIMIT 1"
    ).fetchone()
    assert row is not None


# ── T97: hit-only range repair ─────────────────────────────────────────────

def test_parse_answer_range_repairs_misordered_with_valid_hit() -> None:
    from message_evidence_workstation.search.conversational_answer import _parse_answer_range, RangeRepairRecord

    raw = {
        "title": "School Application",
        "summary": "Application discussion",
        "hit_message_id": "msg_003",
        "start_message_id": "msg_001",
        "end_message_id": "msg_002",
    }
    valid_ids = {"msg_001", "msg_002", "msg_003"}
    thread_by_id = {"msg_001": "t1", "msg_002": "t1", "msg_003": "t1"}
    order = {"t1": ["msg_001", "msg_002", "msg_003"]}

    answer_range, candidate, removed, repair = _parse_answer_range(
        raw, valid_ids=valid_ids, message_thread_by_id=thread_by_id, message_order_by_thread=order,
    )

    assert answer_range is not None
    assert answer_range.hit_message_id == "msg_003"
    assert answer_range.start_message_id == "msg_003"
    assert answer_range.end_message_id == "msg_003"
    assert answer_range.title == "School Application"
    assert candidate is not None
    assert candidate.core_message_id == "msg_003"
    assert candidate.relevant_start_message_id == "msg_003"
    assert candidate.relevant_end_message_id == "msg_003"
    assert isinstance(repair, RangeRepairRecord)
    assert repair.reason == "range_order"
    assert repair.original_start_message_id == "msg_001"
    assert repair.original_end_message_id == "msg_002"
    assert removed == []


def test_parse_answer_range_rejects_invented_hit_id() -> None:
    from message_evidence_workstation.search.conversational_answer import _parse_answer_range

    raw = {
        "title": "Fake",
        "summary": "Fake evidence",
        "hit_message_id": "msg_999",
        "start_message_id": "msg_001",
        "end_message_id": "msg_002",
    }
    valid_ids = {"msg_001", "msg_002"}
    answer_range, candidate, removed, repair = _parse_answer_range(
        raw, valid_ids=valid_ids, message_thread_by_id={}, message_order_by_thread=None,
    )

    assert answer_range is None
    assert candidate is None
    assert repair is None
    assert "msg_999" in removed


def test_parse_answer_range_rejects_cross_thread_hit() -> None:
    from message_evidence_workstation.search.conversational_answer import _parse_answer_range

    raw = {
        "title": "Cross",
        "summary": "Cross-thread evidence",
        "hit_message_id": "msg_003",
        "start_message_id": "msg_001",
        "end_message_id": "msg_002",
    }
    valid_ids = {"msg_001", "msg_002", "msg_003"}
    thread_by_id = {"msg_001": "t1", "msg_002": "t1", "msg_003": "t2"}  # hit in different thread

    answer_range, candidate, removed, repair = _parse_answer_range(
        raw, valid_ids=valid_ids, message_thread_by_id=thread_by_id, message_order_by_thread=None,
    )

    assert answer_range is None
    assert candidate is None
    assert repair is None
    assert any("cross_thread" in r for r in removed)


def test_run_exhaustive_scan_logs_repaired_and_rejected_counts(answer_db) -> None:
    """Integration: repair/reject logged per-window (not propagated to final result)."""
    conn, logger, dataset_id = answer_db
    from message_evidence_workstation.config.settings import NimSettings
    from message_evidence_workstation.search.conversational_answer import run_exhaustive_window_scan_answer
    from message_evidence_workstation.nim.client import NimChatResult

    loaded_router = router_with_role_models()
    nim = NimSettings(context_window_tokens=1_000_000, max_output_tokens=4096, window_overlap_messages=0)
    settings = AnswerSettings()

    planned = [
        TranscriptWindow(
            window_id="tw__window_001",
            source_thread_id="thread_001",
            start_message_id="msg_001",
            end_message_id="msg_003",
            message_ids=["msg_001", "msg_002", "msg_003"],
            estimated_tokens=100,
            text="window",
        ),
    ]

    def fake_nim(_conn, _logger, _client, *, run_type, user_content=None, messages=None, **kwargs):
        if run_type == RUN_TYPE_EXHAUSTIVE_WINDOW_SCAN:
            return NimChatResult(
                content=json.dumps({
                    "answer": "found evidence",
                    "answer_summary": "evidence",
                    "answer_ranges": [
                        {
                            "title": "Bad bracket",
                            "summary": "hit outside range",
                            "hit_message_id": "msg_003",
                            "start_message_id": "msg_001",
                            "end_message_id": "msg_002",
                        },
                        {
                            "title": "Good range",
                            "summary": "valid evidence",
                            "hit_message_id": "msg_002",
                            "start_message_id": "msg_001",
                            "end_message_id": "msg_003",
                        },
                    ],
                    "uncertainties": [],
                    "coverage_summary": {
                        "mode": "exhaustive_window_scan",
                        "messages_considered": 3,
                        "source_thread_ids": ["thread_001"],
                    },
                }),
                raw_response={},
                latency_ms=1,
            )
        return NimChatResult(
            content=json.dumps({
                "answer_summary": "merged",
                "answer": "merged answer",
                "themes": [],
                "notable_patterns": [],
                "contradictions_or_tensions": [],
                "uncertainties": [],
            }),
            raw_response={},
            latency_ms=1,
        )

    with (
        patch("message_evidence_workstation.search.conversational_answer.run_nim_chat", side_effect=fake_nim),
        patch(
            "message_evidence_workstation.search.conversational_answer.collect_exhaustive_window_hints",
            return_value=EMPTY_HINT_COLLECTION,
        ),
        patch("message_evidence_workstation.search.conversational_answer.build_token_bounded_windows_for_dataset", return_value=planned),
    ):
        run_exhaustive_window_scan_answer(
            conn, logger, loaded_router,
            user_query="school",
            dataset_id=dataset_id,
            answer_settings=settings,
            nim_settings=nim,
        )

    window_log = next(
        e for e in fetch_process_logs(conn, component="search.conversational_answer", limit=50)
        if e.operation == "exhaustive_window_scan_window_completed"
    )
    assert window_log.details_json["repaired_answer_range_count"] == 1
    assert window_log.details_json["rejected_answer_range_count"] == 0
    repair_log = next(
        e for e in fetch_process_logs(conn, component="search.conversational_answer", limit=50)
        if e.operation == "exhaustive_window_scan_window_repaired_ranges"
    )
    assert repair_log.details_json["repair_count"] == 1


# ── T98: granular recall ────────────────────────────────────────────────────

def test_exhaustive_scan_planning_uses_resolved_input_budget(answer_db) -> None:
    """Prompt hardening must not force a separate recall token cap."""
    conn, logger, dataset_id = answer_db
    from message_evidence_workstation.config.settings import NimSettings
    from message_evidence_workstation.search.conversational_answer import (
        resolve_answer_budget,
        run_exhaustive_window_scan_answer,
    )
    from message_evidence_workstation.search.dataset_budget import compute_dataset_budget_stats
    from message_evidence_workstation.nim.client import NimChatResult

    loaded_router = router_with_role_models()
    nim = NimSettings(context_window_tokens=1_000_000, max_output_tokens=4096, window_overlap_messages=0)
    answer_settings = AnswerSettings()
    expected_budget = resolve_answer_budget(
        compute_dataset_budget_stats(conn, dataset_id),
        answer_settings,
        loaded_router.writing_model_id() or "unknown-model",
        nim_settings=nim,
    )

    planned = [
        TranscriptWindow(
            window_id="tw__window_001",
            source_thread_id="thread_001",
            start_message_id="msg_001",
            end_message_id="msg_003",
            message_ids=["msg_001", "msg_002", "msg_003"],
            estimated_tokens=100,
            text="window",
        ),
    ]

    def fake_nim(_conn, _logger, _client, *, run_type, user_content=None, messages=None, **kwargs):
        if run_type == RUN_TYPE_EXHAUSTIVE_WINDOW_SCAN:
            return NimChatResult(
                content=json.dumps({
                    "answer": "found evidence",
                    "answer_summary": "evidence",
                    "answer_ranges": [
                        {
                            "title": "Range",
                            "summary": "evidence",
                            "hit_message_id": "msg_002",
                            "start_message_id": "msg_001",
                            "end_message_id": "msg_003",
                        },
                    ],
                    "uncertainties": [],
                    "coverage_summary": {
                        "mode": "exhaustive_window_scan",
                        "messages_considered": 3,
                        "source_thread_ids": ["thread_001"],
                    },
                }),
                raw_response={},
                latency_ms=1,
            )
        return NimChatResult(
            content=json.dumps({
                "answer_summary": "merged",
                "answer": "merged answer",
                "themes": [],
                "notable_patterns": [],
                "contradictions_or_tensions": [],
                "uncertainties": [],
            }),
            raw_response={},
            latency_ms=1,
        )

    with (
        patch("message_evidence_workstation.search.conversational_answer.run_nim_chat", side_effect=fake_nim),
        patch(
            "message_evidence_workstation.search.conversational_answer.collect_exhaustive_window_hints",
            return_value=EMPTY_HINT_COLLECTION,
        ),
        patch(
            "message_evidence_workstation.search.conversational_answer.build_token_bounded_windows_for_dataset",
            return_value=planned,
        ) as build_windows,
    ):
        run_exhaustive_window_scan_answer(
            conn, logger, loaded_router,
            user_query="school",
            dataset_id=dataset_id,
            nim_settings=nim,
            answer_settings=answer_settings,
        )

    assert build_windows.call_args.kwargs["target_tokens"] == expected_budget.usable_input_tokens
    preflight = next(
        e for e in fetch_process_logs(conn, component="search.conversational_answer", limit=50)
        if e.operation == "exhaustive_scan_preflight"
    )
    assert preflight.details_json["per_call_input_budget"] == expected_budget.usable_input_tokens
    assert "scan_window_target_tokens" not in preflight.details_json
    assert "planning_reason" not in preflight.details_json


# ── T102: scoped whole-transcript conversational ─────────────────────

def test_resolve_answer_budget_with_scoped_stats(answer_db) -> None:
    conn, _, dataset_id = answer_db
    stats = compute_dataset_budget_stats(
        conn, dataset_id,
        date_scope=MessageDateScope(end_timestamp="2024-01-02T23:59:59+00:00"),
    )
    budget = resolve_answer_budget(
        stats,
        AnswerSettings(answer_strategy=ANSWER_STRATEGY_WHOLE_TRANSCRIPT),
        "test-model",
        nim_settings=NimSettings(context_window_tokens=1_000_000),
    )
    assert budget.decision == ANSWER_MODE_WHOLE_TRANSCRIPT
    assert budget.transcript_tokens > 0


def test_build_dataset_transcript_scoped(answer_db) -> None:
    conn, _, dataset_id = answer_db
    full = build_dataset_transcript(conn, dataset_id)
    scope = MessageDateScope(end_timestamp="2024-01-02T23:59:59+00:00")
    scoped = build_dataset_transcript(conn, dataset_id, date_scope=scope)
    assert len(scoped.message_ids) < len(full.message_ids)
    assert len(scoped.message_ids) > 0
    for message_id in scoped.message_ids:
        assert message_id in full.message_ids


def test_whole_transcript_answer_rejects_out_of_scope_citations(answer_db) -> None:
    conn, logger, dataset_id = answer_db
    scope = MessageDateScope(end_timestamp="2024-01-02T23:59:59+00:00")
    scoped = build_dataset_transcript(conn, dataset_id, date_scope=scope)
    # Find a message ID that exists in full but not in scoped.
    full = build_dataset_transcript(conn, dataset_id)
    out_of_scope = next(
        message_id for message_id in full.message_ids
        if message_id not in scoped.message_ids
    )
    content = json.dumps({
        "answer": "Test",
        "cited_message_ids": [out_of_scope],
        "candidate_evidence_blocks": [],
        "uncertainties": [],
        "coverage_summary": {
            "mode": "whole_transcript",
            "messages_considered": len(scoped.message_ids),
            "source_thread_ids": [],
        },
    })
    result = parse_whole_transcript_answer_response(
        content,
        valid_message_ids=set(scoped.message_ids),
        message_thread_by_id={},
        source_thread_ids=[],
        messages_considered=len(scoped.message_ids),
    )
    assert out_of_scope in result.removed_invalid_citation_ids


def test_run_whole_transcript_answer_raises_on_empty_scope(answer_db) -> None:
    conn, logger, dataset_id = answer_db
    transcript = build_dataset_transcript(
        conn, dataset_id,
        date_scope=MessageDateScope(
            start_timestamp="2020-01-01T00:00:00+00:00",
            end_timestamp="2020-01-02T00:00:00+00:00",
        ),
    )
    assert transcript.message_ids == []
    from tests.router_helpers import router_with_role_models
    router = router_with_role_models()
    with pytest.raises(ConversationalAnswerParseError) as exc_info:
        run_whole_transcript_answer(
            conn, logger, router,
            user_query="test",
            dataset_id=dataset_id,
            transcript=transcript,
        )
    assert "No messages" in str(exc_info.value)
