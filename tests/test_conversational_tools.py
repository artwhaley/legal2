"""Conversational planner and tool runner tests."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.embeddings.adapters import FakeEmbeddingAdapter
from message_evidence_workstation.embeddings.index_jobs import build_message_embedding_index
from message_evidence_workstation.importers.normalized_loader import load_normalized_dataset
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.search.tool_runner import (
    PlannerParseError,
    SearchPlannerPlan,
    ToolRunnerDeps,
    _RunnerState,
    execute_full_search_harness,
    execute_plan,
    execute_tool_call,
    parse_planner_plan,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_dataset"


@pytest.fixture
def tool_db(tmp_path):
    conn = connect(tmp_path / "conv_tools.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    dataset_id = load_normalized_dataset(conn, logger, FIXTURE_DIR)
    rows = conn.execute(
        "SELECT message_id, sort_index FROM message WHERE dataset_id = ?",
        (dataset_id,),
    ).fetchall()
    sort_index = {row["message_id"]: row["sort_index"] for row in rows}
    return conn, logger, dataset_id, sort_index


def test_parse_valid_plan() -> None:
    content = json.dumps(
        {
            "strategy_summary": "Search allergy mentions",
            "tool_calls": [
                {"tool": "fts", "query": "allergy"},
                {"tool": "group_hits"},
            ],
        }
    )
    plan = parse_planner_plan(content)
    assert plan.strategy_summary == "Search allergy mentions"
    assert plan.extra_search_queries == ["allergy"]


def test_parse_strategy_only_plan() -> None:
    content = json.dumps(
        {
            "strategy_summary": "Cast a wide net for allergy paperwork",
            "extra_search_queries": ["allergic", "epipen"],
        }
    )
    plan = parse_planner_plan(content)
    assert plan.strategy_summary.startswith("Cast a wide net")
    assert plan.extra_search_queries == ["allergic", "epipen"]
    assert plan.tool_calls == []


def test_parse_malformed_plan_raises() -> None:
    with pytest.raises(PlannerParseError):
        parse_planner_plan("not json at all")


def test_parse_rejects_unknown_tool() -> None:
    content = json.dumps(
        {
            "strategy_summary": "bad",
            "tool_calls": [{"tool": "delete_database"}],
        }
    )
    with pytest.raises(PlannerParseError):
        parse_planner_plan(content)


def _tools_run(execution) -> list[str]:
    return [item.tool for item in execution.tool_results]


def test_full_harness_always_runs_all_retrieval_methods(tool_db) -> None:
    conn, logger, dataset_id, sort_index = tool_db
    plan = SearchPlannerPlan(strategy_summary="Recall-first harness")
    execution = execute_full_search_harness(
        conn,
        logger,
        dataset_id=dataset_id,
        user_query="allergy",
        plan=plan,
        deps=ToolRunnerDeps(),
        sort_index_by_message=sort_index,
    )
    tools = _tools_run(execution)
    assert tools.count("fts") >= 1
    assert "keyword_expansion" in tools
    assert "message_embedding" in tools
    assert "chunk_embedding" in tools
    assert "group_hits" in tools


def test_execute_fts_and_group_tools(tool_db) -> None:
    conn, logger, dataset_id, sort_index = tool_db
    plan = SearchPlannerPlan(
        strategy_summary="FTS then group",
        extra_search_queries=["allergy"],
    )
    execution = execute_plan(
        conn,
        logger,
        dataset_id=dataset_id,
        user_query="allergy",
        plan=plan,
        deps=ToolRunnerDeps(),
        sort_index_by_message=sort_index,
    )
    fts_results = [item for item in execution.tool_results if item.tool == "fts"]
    assert fts_results and all(item.success for item in fts_results)
    assert any(item.hit_count >= 1 for item in fts_results)
    group_result = next(item for item in execution.tool_results if item.tool == "group_hits")
    assert group_result.success
    assert group_result.group_count >= 1
    assert execution.grouped_results


def test_execute_fts_multi_token_planner_query(tool_db) -> None:
    conn, logger, dataset_id, sort_index = tool_db
    plan = SearchPlannerPlan(
        strategy_summary="Planner-style multi-word FTS",
        extra_search_queries=["allergies allergic allergy"],
    )
    execution = execute_plan(
        conn,
        logger,
        dataset_id=dataset_id,
        user_query="allergies",
        plan=plan,
        deps=ToolRunnerDeps(),
        sort_index_by_message=sort_index,
    )
    fts_results = [item for item in execution.tool_results if item.tool == "fts"]
    assert fts_results and all(item.success for item in fts_results)
    assert any(item.hit_count >= 1 for item in fts_results)
    assert any(hit.message_id == "msg_001" for hit in execution.accumulated_hits)


def test_embedding_tool_failure_is_visible(tool_db) -> None:
    conn, logger, dataset_id, sort_index = tool_db
    plan = SearchPlannerPlan(strategy_summary="Try vectors without adapter")
    execution = execute_plan(
        conn,
        logger,
        dataset_id=dataset_id,
        user_query="allergy",
        plan=plan,
        deps=ToolRunnerDeps(),
        sort_index_by_message=sort_index,
    )
    embedding_results = [
        item
        for item in execution.tool_results
        if item.tool in {"message_embedding", "chunk_embedding"}
    ]
    assert len(embedding_results) == 2
    assert all(not item.success for item in embedding_results)
    assert all(item.error for item in embedding_results)


def test_read_message_range_tool(tool_db) -> None:
    conn, logger, dataset_id, sort_index = tool_db
    state = _RunnerState()
    result = execute_tool_call(
        conn,
        logger,
        dataset_id=dataset_id,
        user_query="context",
        call={
            "tool": "read_message_range",
            "source_thread_id": "thread_001",
            "start_message_id": "msg_001",
            "end_message_id": "msg_002",
        },
        state=state,
        deps=ToolRunnerDeps(),
        sort_index_by_message=sort_index,
    )
    assert result.success
    assert result.message_count == 2


def test_mock_planner_output_executes_tools(tool_db) -> None:
    conn, logger, dataset_id, sort_index = tool_db
    adapter = FakeEmbeddingAdapter(model_name="fake-conv", dimensions=8)
    info = adapter.load()
    build_message_embedding_index(
        conn, logger, dataset_id=dataset_id, adapter=adapter, adapter_info=info
    )
    plan_json = json.dumps(
        {
            "strategy_summary": "Mocked planner",
            "extra_search_queries": ["school"],
        }
    )
    plan = parse_planner_plan(plan_json)
    execution = execute_plan(
        conn,
        logger,
        dataset_id=dataset_id,
        user_query="school",
        plan=plan,
        deps=ToolRunnerDeps(
            embedding_adapter=adapter,
            embedding_model_name="fake-conv",
        ),
        sort_index_by_message=sort_index,
    )
    assert any(item.tool == "message_embedding" and item.success for item in execution.tool_results)
    assert execution.grouped_results or execution.accumulated_hits


def test_run_conversational_planner_with_mock_nim(tool_db) -> None:
    conn, logger, dataset_id, sort_index = tool_db
    from message_evidence_workstation.nim.client import NimChatResult
    from message_evidence_workstation.search.tool_runner import run_conversational_planner

    plan_payload = {
        "strategy_summary": "From NIM",
        "extra_search_queries": ["allergy"],
    }
    mock_client = MagicMock()
    mock_client.settings.model = "test-model"
    with patch(
        "message_evidence_workstation.search.tool_runner.run_nim_chat",
        return_value=NimChatResult(
            content=json.dumps(plan_payload),
            raw_response={"choices": []},
            latency_ms=5,
        ),
    ):
        execution = run_conversational_planner(
            conn,
            logger,
            mock_client,
            user_query="allergy forms",
            dataset_id=dataset_id,
            deps=ToolRunnerDeps(),
            sort_index_by_message=sort_index,
        )
    assert execution.plan.strategy_summary == "From NIM"
    fts_results = [item for item in execution.tool_results if item.tool == "fts"]
    assert fts_results and all(item.success for item in fts_results)
