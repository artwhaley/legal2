"""Conversational synthesis tests (T18)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.db.repositories import create_category
from message_evidence_workstation.db.evidence_blocks import (
    create_evidence_block_from_conversational_candidate,
    list_evidence_blocks,
)
from message_evidence_workstation.importers.normalized_loader import load_normalized_dataset
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.nim.client import NimChatResult
from message_evidence_workstation.nim.prompts import RUN_TYPE_CONVERSATIONAL_SYNTHESIS
from message_evidence_workstation.search.grouping import group_hits
from message_evidence_workstation.search.result_models import SearchHit
from message_evidence_workstation.search.synthesis import (
    SynthesisParseError,
    build_synthesis_user_content,
    parse_synthesis_response,
    run_conversational_synthesis,
)
from message_evidence_workstation.search.tool_runner import (
    ConversationalPlanExecution,
    SearchPlannerPlan,
    ToolRunnerDeps,
    execute_full_search_harness,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_dataset"


@pytest.fixture
def synthesis_db(tmp_path):
    conn = connect(tmp_path / "synthesis.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    dataset_id = load_normalized_dataset(conn, logger, FIXTURE_DIR)
    return conn, logger, dataset_id


def _sample_execution(conn, logger, dataset_id) -> ConversationalPlanExecution:
    plan = SearchPlannerPlan(strategy_summary="Look for allergy paperwork")
    return execute_full_search_harness(
        conn,
        logger,
        dataset_id=dataset_id,
        user_query="allergy",
        plan=plan,
        deps=ToolRunnerDeps(),
    )


def test_build_synthesis_payload_includes_groups(synthesis_db) -> None:
    conn, logger, dataset_id = synthesis_db
    execution = _sample_execution(conn, logger, dataset_id)
    plan = execution.plan
    payload = json.loads(build_synthesis_user_content("allergy", plan, execution))
    assert payload["user_query"] == "allergy"
    assert payload["planner_strategy_summary"] == plan.strategy_summary
    assert payload["candidate_groups"]
    assert payload["candidate_groups"][0]["group_id"]


def test_parse_synthesis_response_resolves_candidates() -> None:
    group = group_hits(
        [
            SearchHit(
                message_id="msg_001",
                source_thread_id="thread_001",
                match_type="exact",
                retrieval_method="fts_exact",
                query_text="allergy",
                snippet="allergy form",
                thread_ordinal=0,
            )
        ],
    )[0]
    content = json.dumps(
        {
            "answer": "Found allergy paperwork mentions.",
            "strategy_summary": "Searched allergy terms across the dataset.",
            "candidate_conversations": [
                {
                    "group_id": group.group_id,
                    "title": "Allergy form",
                    "explanation": "Direct mention of allergy paperwork.",
                    "confidence": "high",
                }
            ],
        }
    )
    result = parse_synthesis_response(
        content,
        groups_by_id={group.group_id: group},
        fallback_strategy_summary="fallback",
    )
    assert "allergy" in result.answer.lower()
    assert len(result.candidates) == 1
    assert result.candidates[0].group is group
    assert result.candidates[0].confidence == "high"


def test_parse_synthesis_rejects_missing_answer() -> None:
    with pytest.raises(SynthesisParseError):
        parse_synthesis_response(
            json.dumps({"candidate_conversations": []}),
            groups_by_id={},
            fallback_strategy_summary="fallback",
        )


def test_run_conversational_synthesis_creates_model_run(synthesis_db) -> None:
    conn, logger, dataset_id = synthesis_db
    execution = _sample_execution(conn, logger, dataset_id)
    plan = execution.plan
    group = execution.grouped_results[0]
    synthesis_payload = {
        "answer": "There is an allergy form discussion.",
        "strategy_summary": "Used allergy search terms.",
        "candidate_conversations": [
            {
                "group_id": group.group_id,
                "title": group.title,
                "explanation": "Mentions allergy paperwork.",
                "confidence": "high",
            }
        ],
    }
    mock_client = MagicMock()
    mock_client.settings.model = "test-model"
    with patch(
        "message_evidence_workstation.search.synthesis.run_nim_chat",
        return_value=NimChatResult(
            content=json.dumps(synthesis_payload),
            raw_response={"choices": []},
            latency_ms=7,
        ),
    ) as mock_chat:
        result = run_conversational_synthesis(
            conn,
            logger,
            mock_client,
            user_query="allergy",
            plan=plan,
            execution=execution,
            dataset_id=dataset_id,
        )
    assert result.candidates
    mock_chat.assert_called_once()
    assert mock_chat.call_args.kwargs["run_type"] == RUN_TYPE_CONVERSATIONAL_SYNTHESIS


def test_user_add_candidate_creates_evidence_block(synthesis_db) -> None:
    conn, logger, dataset_id = synthesis_db
    execution = _sample_execution(conn, logger, dataset_id)
    group = execution.grouped_results[0]
    category = create_category(conn, logger, dataset_id, "medical")
    ordered_message_ids = [hit.message_id for hit in group.hits]
    create_evidence_block_from_conversational_candidate(
        conn,
        logger,
        dataset_id=dataset_id,
        source_thread_id=group.source_thread_id,
        ordered_message_ids=ordered_message_ids,
        title=group.title,
        summary="Candidate from synthesis.",
        core_message_id=group.primary_hit_message_id,
        leading_context_start_message_id=ordered_message_ids[0],
        relevant_start_message_id=ordered_message_ids[0],
        relevant_end_message_id=ordered_message_ids[-1],
        trailing_context_end_message_id=ordered_message_ids[-1],
        category_id=category.category_id,
    )
    stored = list_evidence_blocks(conn, dataset_id, category_id=category.category_id)
    assert len(stored) == 1
    assert stored[0].title == group.title
