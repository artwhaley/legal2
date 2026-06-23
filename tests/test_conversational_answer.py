"""Coverage-aware conversational answer tests (T2-T3)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.importers.normalized_loader import load_normalized_dataset
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.config.settings import NimSettings
from message_evidence_workstation.nim.client import NimChatResult, NimClient
from message_evidence_workstation.config.settings import AnswerSettings
from message_evidence_workstation.nim.prompts import (
    RUN_TYPE_EXHAUSTIVE_WINDOW_MERGE,
    RUN_TYPE_EXHAUSTIVE_WINDOW_SCAN,
    RUN_TYPE_WHOLE_TRANSCRIPT_ANSWER,
)
from message_evidence_workstation.search.conversational_answer import (
    ANSWER_MODE_EXHAUSTIVE_WINDOW_SCAN,
    ANSWER_MODE_RETRIEVAL_FALLBACK,
    ANSWER_MODE_SESSION_COVERAGE,
    ANSWER_MODE_WHOLE_TRANSCRIPT,
    ANSWER_STRATEGY_AUTO,
    ANSWER_STRATEGY_EXHAUSTIVE_WINDOW_SCAN,
    ANSWER_STRATEGY_SESSION_COVERAGE,
    ANSWER_STRATEGY_RETRIEVAL_FALLBACK,
    ConversationalAnswerParseError,
    build_dataset_transcript,
    build_whole_transcript_user_content,
    build_exhaustive_window_merge_user_content,
    parse_whole_transcript_answer_response,
    resolve_answer_budget,
    resolve_answer_mode,
    run_exhaustive_window_scan_answer,
    run_whole_transcript_answer,
)
from message_evidence_workstation.search.transcript import serialize_thread_transcript

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_dataset"


@pytest.fixture
def answer_db(tmp_path):
    conn = connect(tmp_path / "answer.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    dataset_id = load_normalized_dataset(conn, logger, FIXTURE_DIR)
    return conn, logger, dataset_id


def test_resolve_answer_budget_auto_selects_whole_transcript_when_tokens_fit(answer_db) -> None:
    conn, _, dataset_id = answer_db
    transcript = build_dataset_transcript(conn, dataset_id)
    settings = AnswerSettings(answer_strategy=ANSWER_STRATEGY_AUTO, context_window_override_tokens=1_000_000)
    budget = resolve_answer_budget(transcript, settings, "test-model")
    assert budget.decision == ANSWER_MODE_WHOLE_TRANSCRIPT


def test_resolve_answer_budget_auto_selects_exhaustive_when_tokens_do_not_fit(answer_db) -> None:
    conn, _, dataset_id = answer_db
    transcript = build_dataset_transcript(conn, dataset_id)
    settings = AnswerSettings(
        answer_strategy=ANSWER_STRATEGY_AUTO,
        context_window_override_tokens=500,
        reserved_output_tokens=100,
        prompt_overhead_tokens=100,
    )
    budget = resolve_answer_budget(transcript, settings, "test-model")
    assert budget.decision == ANSWER_MODE_EXHAUSTIVE_WINDOW_SCAN


def test_resolve_answer_mode_auto_selects_whole_transcript_when_fits(answer_db) -> None:
    conn, _, dataset_id = answer_db
    transcript = build_dataset_transcript(conn, dataset_id)
    settings = AnswerSettings(answer_strategy=ANSWER_STRATEGY_AUTO, context_window_override_tokens=1_000_000)
    mode = resolve_answer_mode(
        strategy=ANSWER_STRATEGY_AUTO,
        transcript=transcript,
        answer_settings=settings,
        model_id="test-model",
    )
    assert mode == ANSWER_MODE_WHOLE_TRANSCRIPT


def test_resolve_answer_mode_auto_selects_exhaustive_window_scan_when_too_large(answer_db) -> None:
    conn, _, dataset_id = answer_db
    transcript = build_dataset_transcript(conn, dataset_id)
    settings = AnswerSettings(
        answer_strategy=ANSWER_STRATEGY_AUTO,
        context_window_override_tokens=500,
        reserved_output_tokens=100,
        prompt_overhead_tokens=100,
    )
    mode = resolve_answer_mode(
        strategy=ANSWER_STRATEGY_AUTO,
        transcript=transcript,
        answer_settings=settings,
        model_id="test-model",
    )
    assert mode == ANSWER_MODE_EXHAUSTIVE_WINDOW_SCAN


def test_char_limit_no_longer_controls_auto(answer_db) -> None:
    conn, _, dataset_id = answer_db
    transcript = build_dataset_transcript(conn, dataset_id)
    settings = AnswerSettings(answer_strategy=ANSWER_STRATEGY_AUTO, context_window_override_tokens=1_000_000)
    mode = resolve_answer_mode(
        strategy=ANSWER_STRATEGY_AUTO,
        transcript=transcript,
        answer_settings=settings,
        model_id="test-model",
        max_chars=10,
    )
    assert mode == ANSWER_MODE_WHOLE_TRANSCRIPT


def test_resolve_answer_mode_explicit_strategies_still_work(answer_db) -> None:
    conn, _, dataset_id = answer_db
    transcript = build_dataset_transcript(conn, dataset_id)
    settings = AnswerSettings(context_window_override_tokens=1_000_000)
    assert (
        resolve_answer_mode(
            strategy=ANSWER_STRATEGY_SESSION_COVERAGE,
            transcript=transcript,
            answer_settings=settings,
            model_id="test-model",
        )
        == ANSWER_MODE_SESSION_COVERAGE
    )
    assert (
        resolve_answer_mode(
            strategy=ANSWER_STRATEGY_RETRIEVAL_FALLBACK,
            transcript=transcript,
            answer_settings=settings,
            model_id="test-model",
        )
        == ANSWER_MODE_RETRIEVAL_FALLBACK
    )
    assert (
        resolve_answer_mode(
            strategy=ANSWER_STRATEGY_EXHAUSTIVE_WINDOW_SCAN,
            transcript=transcript,
            answer_settings=settings,
            model_id="test-model",
        )
        == ANSWER_MODE_EXHAUSTIVE_WINDOW_SCAN
    )


def test_build_whole_transcript_user_content_includes_full_transcript(answer_db) -> None:
    conn, _, dataset_id = answer_db
    transcript = build_dataset_transcript(conn, dataset_id)
    payload = json.loads(build_whole_transcript_user_content("allergy forms", transcript))
    assert payload["user_query"] == "allergy forms"
    assert payload["transcript"] == transcript.text
    assert len(payload["message_ids"]) == len(transcript.message_ids)
    assert "[msg_001]" in payload["transcript"]
    assert "[msg_100]" in payload["transcript"]


def test_build_exhaustive_window_merge_user_content_reports_full_coverage(answer_db) -> None:
    conn, logger, dataset_id = answer_db
    from message_evidence_workstation.search.session_map import list_sessions, rebuild_dataset_sessions

    sessions = rebuild_dataset_sessions(conn, logger, dataset_id, gap_minutes=30)
    payload = json.loads(
        build_exhaustive_window_merge_user_content(
            "travel chess set",
            sessions=sessions,
            window_results=[
                {
                    "session_id": session.session_id,
                    "source_thread_id": session.source_thread_id,
                    "message_ids": [session.start_message_id, session.end_message_id],
                    "answer": "No relevant evidence.",
                    "cited_message_ids": [],
                    "candidate_evidence_blocks": [],
                    "uncertainties": [],
                }
                for session in sessions
            ],
        )
    )
    assert payload["coverage_summary"]["mode"] == ANSWER_MODE_EXHAUSTIVE_WINDOW_SCAN
    assert payload["coverage_summary"]["sessions_considered"] == len(sessions)
    assert payload["coverage_summary"]["sessions_inspected"] == len(sessions)
    assert payload["coverage_summary"]["sessions_skipped"] == 0


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
    captured: dict[str, str] = {}

    def fake_run_nim_chat(_conn, _logger, _client, *, run_type, user_content, dataset_id=None, **kwargs):
        captured["run_type"] = run_type
        captured["user_content"] = user_content
        payload = json.loads(user_content)
        return NimChatResult(
            content=json.dumps(
                {
                    "answer": "Found allergy paperwork references.",
                    "cited_message_ids": ["msg_002"],
                    "candidate_evidence_blocks": [],
                    "uncertainties": [],
                    "coverage_summary": {
                        "mode": "whole_transcript",
                        "messages_considered": len(payload["message_ids"]),
                        "source_thread_ids": payload["source_thread_ids"],
                    },
                }
            ),
            raw_response={},
            latency_ms=1,
        )

    client = NimClient(NimSettings(model="test-model", api_key="key"))
    with patch(
        "message_evidence_workstation.search.conversational_answer.run_nim_chat",
        side_effect=fake_run_nim_chat,
    ):
        result = run_whole_transcript_answer(
            conn,
            logger,
            client,
            user_query="allergy paperwork",
            dataset_id=dataset_id,
            transcript=transcript,
        )
    assert captured["run_type"] == RUN_TYPE_WHOLE_TRANSCRIPT_ANSWER
    payload = json.loads(captured["user_content"])
    assert payload["transcript"] == transcript.text
    assert len(payload["transcript"].splitlines()) == 100
    assert result.mode == ANSWER_MODE_WHOLE_TRANSCRIPT
    assert result.cited_message_ids == ["msg_002"]


def test_run_session_coverage_answer_considers_all_sessions(answer_db) -> None:
    conn, logger, dataset_id = answer_db
    from message_evidence_workstation.search.session_map import list_sessions, rebuild_dataset_sessions

    rebuild_dataset_sessions(conn, logger, dataset_id, gap_minutes=30)
    assert list_sessions(conn, dataset_id)
    call_index = {"count": 0}

    def fake_run_nim_chat(_conn, _logger, _client, *, run_type, user_content, dataset_id=None, **kwargs):
        call_index["count"] += 1
        if run_type.endswith("session_summary"):
            return NimChatResult(
                content=json.dumps(
                    {
                        "topics": ["topic"],
                        "people": [],
                        "events": [],
                        "commitments": [],
                        "conflicts": [],
                        "appointments": [],
                        "money": [],
                        "parenting_school": [],
                        "medical": [],
                        "travel": [],
                        "notable_quotes": [],
                    }
                ),
                raw_response={},
                latency_ms=1,
            )
        if run_type.endswith("session_classification"):
            payload = json.loads(user_content)
            classifications = [
                {
                    "session_id": item["session_id"],
                    "classification": "relevant" if index == 0 else "not_relevant",
                    "reason": "test",
                }
                for index, item in enumerate(payload["session_summaries"])
            ]
            return NimChatResult(
                content=json.dumps({"session_classifications": classifications}),
                raw_response={},
                latency_ms=1,
            )
        if run_type.endswith("coverage_audit"):
            return NimChatResult(
                content=json.dumps(
                    {
                        "additional_session_ids": [],
                        "residual_uncertainties": [],
                        "audit_notes": "",
                    }
                ),
                raw_response={},
                latency_ms=1,
            )
        payload = json.loads(user_content)
        assert payload["inspected_transcript_windows"]
        assert "[msg_" in payload["inspected_transcript_windows"][0]["transcript"]
        return NimChatResult(
            content=json.dumps(
                {
                    "answer": "Coverage answer from inspected session windows.",
                    "cited_message_ids": ["msg_001"],
                    "candidate_evidence_blocks": [],
                    "uncertainties": [],
                    "coverage_summary": {
                        "mode": "session_coverage",
                        "messages_considered": 10,
                        "source_thread_ids": ["thread_001"],
                        "sessions_considered": len(payload["session_summaries"]),
                        "sessions_inspected": len(payload["inspected_transcript_windows"]),
                        "sessions_skipped": len(payload["session_summaries"])
                        - len(payload["inspected_transcript_windows"]),
                    },
                }
            ),
            raw_response={},
            latency_ms=1,
        )

    from message_evidence_workstation.search.conversational_answer import run_session_coverage_answer

    client = NimClient(NimSettings(model="test-model", api_key="key"))
    with (
        patch(
            "message_evidence_workstation.search.conversational_answer.run_nim_chat",
            side_effect=fake_run_nim_chat,
        ),
        patch(
            "message_evidence_workstation.search.coverage_audit.run_nim_chat",
            side_effect=fake_run_nim_chat,
        ),
        patch(
            "message_evidence_workstation.search.session_summaries.run_nim_chat",
            side_effect=fake_run_nim_chat,
        ),
    ):
        result = run_session_coverage_answer(
            conn,
            logger,
            client,
            user_query="allergy paperwork",
            dataset_id=dataset_id,
            max_inspected_sessions=12,
        )
    assert result.mode == ANSWER_MODE_SESSION_COVERAGE
    rebuilt_sessions = list_sessions(conn, dataset_id)
    assert result.coverage_summary.sessions_considered == len(rebuilt_sessions)
    assert result.coverage_summary.sessions_inspected >= 1
    assert call_index["count"] >= 2


def test_run_exhaustive_window_scan_answer_inspects_every_planned_window(answer_db) -> None:
    conn, logger, dataset_id = answer_db
    from message_evidence_workstation.config.settings import AnswerSettings
    from message_evidence_workstation.nim.prompts import (
        RUN_TYPE_EXHAUSTIVE_WINDOW_MERGE,
        RUN_TYPE_EXHAUSTIVE_WINDOW_SCAN,
    )

    answer_settings = AnswerSettings(window_target_tokens=12_000, window_overlap_messages=2)
    calls: list[tuple[str, dict, dict]] = []
    scan_count = 0

    def fake_run_nim_chat(_conn, _logger, _client, *, run_type, user_content, dataset_id=None, **kwargs):
        nonlocal scan_count
        payload = json.loads(user_content)
        calls.append((run_type, payload, kwargs))
        if run_type == RUN_TYPE_EXHAUSTIVE_WINDOW_SCAN:
            scan_count += 1
            assert "window_id" in payload
            assert "estimated_tokens" in payload
            return NimChatResult(
                content=json.dumps(
                    {
                        "answer": "Window inspected.",
                        "cited_message_ids": [],
                        "candidate_evidence_blocks": [],
                        "uncertainties": [],
                        "coverage_summary": {
                            "mode": "exhaustive_window_scan",
                            "messages_considered": len(payload["message_ids"]),
                            "source_thread_ids": [payload["source_thread_id"]],
                        },
                    }
                ),
                raw_response={},
                latency_ms=1,
            )
        assert run_type == RUN_TYPE_EXHAUSTIVE_WINDOW_MERGE
        assert scan_count > 0
        assert len(payload["window_findings"]) == scan_count
        assert payload["coverage_summary"]["windows_inspected"] == scan_count
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

    client = NimClient(NimSettings(model="test-model", api_key="key"))
    with patch(
        "message_evidence_workstation.search.conversational_answer.run_nim_chat",
        side_effect=fake_run_nim_chat,
    ):
        result = run_exhaustive_window_scan_answer(
            conn,
            logger,
            client,
            user_query="travel chess set",
            dataset_id=dataset_id,
            answer_settings=answer_settings,
            max_tokens=answer_settings.reserved_output_tokens,
        )

    scan_calls = [call for call in calls if call[0] == RUN_TYPE_EXHAUSTIVE_WINDOW_SCAN]
    assert len(scan_calls) == scan_count
    assert scan_count > 0
    assert all(call[2].get("max_tokens") == answer_settings.reserved_output_tokens for call in scan_calls)
    merge_call = next(call for call in calls if call[0] == RUN_TYPE_EXHAUSTIVE_WINDOW_MERGE)
    assert merge_call[2].get("max_tokens") >= 4096
    assert result.mode == ANSWER_MODE_EXHAUSTIVE_WINDOW_SCAN
    assert result.coverage_summary.windows_inspected == scan_count
    assert result.coverage_summary.token_budget is not None


def test_whole_transcript_answer_passes_reserved_output_tokens(answer_db) -> None:
    conn, logger, dataset_id = answer_db
    transcript = build_dataset_transcript(conn, dataset_id)
    captured: dict[str, object] = {}

    def fake_run_nim_chat(_conn, _logger, _client, *, run_type, user_content, dataset_id=None, **kwargs):
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

    client = NimClient(NimSettings(model="test-model", api_key="key"))
    with patch(
        "message_evidence_workstation.search.conversational_answer.run_nim_chat",
        side_effect=fake_run_nim_chat,
    ):
        run_whole_transcript_answer(
            conn,
            logger,
            client,
            user_query="allergy",
            dataset_id=dataset_id,
            transcript=transcript,
            max_tokens=8192,
        )
    assert captured["max_tokens"] == 8192


def test_answer_budget_log_written(answer_db) -> None:
    conn, logger, dataset_id = answer_db
    from message_evidence_workstation.search.conversational_answer import log_answer_budget_resolved

    transcript = build_dataset_transcript(conn, dataset_id)
    settings = AnswerSettings(answer_strategy=ANSWER_STRATEGY_AUTO, context_window_override_tokens=1_000_000)
    budget = resolve_answer_budget(transcript, settings, "test-model")
    log_answer_budget_resolved(
        logger,
        budget=budget,
        dataset_id=dataset_id,
        strategy=settings.answer_strategy,
    )
    row = conn.execute(
        "SELECT operation FROM process_log WHERE operation = 'answer_budget_resolved' ORDER BY process_log_id DESC LIMIT 1"
    ).fetchone()
    assert row is not None
