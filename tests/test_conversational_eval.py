"""Conversational recall evaluation tests (T10)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from message_evidence_workstation.config.settings import AnswerSettings, NimSettings
from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.importers.normalized_loader import load_normalized_dataset
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.search.dataset_budget import compute_dataset_budget_stats
from tests.router_helpers import router_with_role_models
from message_evidence_workstation.nim.client import NimChatResult
from message_evidence_workstation.search.conversational_answer import (
    build_dataset_transcript,
    build_whole_transcript_user_content,
    resolve_answer_mode,
    run_whole_transcript_answer,
)
from message_evidence_workstation.search.conversational_eval import (
    EVAL_QUESTIONS,
    score_conversational_answer,
)
from message_evidence_workstation.search.result_models import SearchHit
from message_evidence_workstation.search.synthesis import build_synthesis_user_content
from message_evidence_workstation.search.tool_runner import (
    ConversationalPlanExecution,
    SearchPlannerPlan,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_dataset"


@pytest.fixture
def eval_db(tmp_path):
    conn = connect(tmp_path / "eval.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    dataset_id = load_normalized_dataset(conn, logger, FIXTURE_DIR)
    return conn, logger, dataset_id


def test_whole_transcript_mode_selected_for_sample_fixture(eval_db) -> None:
    conn, _, dataset_id = eval_db
    stats = compute_dataset_budget_stats(conn, dataset_id)
    settings = AnswerSettings()
    mode = resolve_answer_mode(
        strategy="auto",
        stats=stats,
        answer_settings=settings,
        nim_settings=NimSettings(context_window_tokens=500_000),
    )
    assert mode == "whole_transcript"


def test_whole_transcript_payload_contains_late_scattered_message(eval_db) -> None:
    conn, _, dataset_id = eval_db
    transcript = build_dataset_transcript(conn, dataset_id)
    payload = json.loads(build_whole_transcript_user_content("travel chess set", transcript))
    assert "msg_098" in payload["transcript"]
    assert "travel chess set" in payload["transcript"]


def test_regression_whole_transcript_finds_answer_top_k_would_miss(eval_db) -> None:
    conn, logger, dataset_id = eval_db
    transcript = build_dataset_transcript(conn, dataset_id)
    clipped_execution = ConversationalPlanExecution(
        plan=SearchPlannerPlan(strategy_summary="top-k only"),
        tool_results=[],
        accumulated_hits=[
            SearchHit(
                message_id="msg_001",
                source_thread_id="thread_001",
                match_type="exact",
                retrieval_method="fts_exact",
                query_text="travel chess set",
                body="allergy form",
                snippet="allergy form",
            )
        ],
        grouped_results=[],
    )
    synthesis_payload = json.loads(
        build_synthesis_user_content("travel chess set", clipped_execution.plan, clipped_execution)
    )
    assert "msg_098" not in json.dumps(synthesis_payload)

    def fake_run_nim_chat(_conn, _logger, _client, *, run_type, user_content=None, messages=None, dataset_id=None, **kwargs):
        assert messages is not None
        assert "msg_098" in messages[1]["content"]
        return NimChatResult(
            content=json.dumps(
                {
                    "answer": "Jane asked to add the travel chess set for the cabin trip.",
                    "cited_message_ids": ["msg_098"],
                    "candidate_evidence_blocks": [],
                    "uncertainties": [],
                    "coverage_summary": {
                        "mode": "whole_transcript",
                        "messages_considered": 100,
                        "source_thread_ids": ["thread_001"],
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
            user_query="travel chess set",
            dataset_id=dataset_id,
            transcript=transcript,
        )
    score = score_conversational_answer(
        result,
        question="travel chess set",
        expected_message_ids=["msg_098"],
    )
    assert score.passed
    assert "msg_098" in score.recall_hits


@pytest.mark.parametrize("case", EVAL_QUESTIONS)
def test_eval_fixture_shape(case: dict) -> None:
    assert "question" in case
    assert "expected_message_ids" in case
    assert "expects_insufficient_evidence" in case


def test_score_insufficient_evidence_case() -> None:
    from message_evidence_workstation.search.conversational_answer import (
        ConversationalAnswerResult,
        CoverageSummary,
    )

    result = ConversationalAnswerResult(
        answer="There is not enough evidence in the transcript to answer that question.",
        cited_message_ids=[],
        candidate_evidence_blocks=[],
        uncertainties=["No election content in messages."],
        coverage_summary=CoverageSummary(
            mode="whole_transcript",
            messages_considered=100,
            source_thread_ids=["thread_001"],
        ),
        mode="whole_transcript",
    )
    score = score_conversational_answer(
        result,
        question="Who won the 2032 presidential election?",
        expected_message_ids=[],
        expects_insufficient_evidence=True,
    )
    assert score.passed
