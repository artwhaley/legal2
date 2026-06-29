"""Conversational search planner validation and explicit retrieval tools."""

from __future__ import annotations

import json
import re
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any

from message_evidence_workstation.db import repositories
from message_evidence_workstation.domain.models import Message
from message_evidence_workstation.embeddings.adapters import EmbeddingAdapter
from message_evidence_workstation.config.settings import load_settings
from message_evidence_workstation.llm.router import ModelRouter
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.nim.client import NimClient
from message_evidence_workstation.nim.model_runs import run_nim_chat
from message_evidence_workstation.nim.prompts import RUN_TYPE_CONVERSATIONAL_PLANNER
from message_evidence_workstation.search import fts
from message_evidence_workstation.search.embedding_search import (
    EmbeddingIndexNotReadyError,
    search_chunk_embeddings,
    search_message_embeddings,
)
from message_evidence_workstation.search.fusion import fuse_hits
from message_evidence_workstation.search.grouping import group_hits
from message_evidence_workstation.search.keyword_expansion import expand_keywords
from message_evidence_workstation.search.result_models import GroupedSearchResult, SearchHit

PLANNER_TOOLS = frozenset(
    {
        "fts",
        "keyword_expansion",
        "message_embedding",
        "chunk_embedding",
        "read_source_thread",
        "read_message_range",
        "group_hits",
    }
)


class PlannerParseError(ValueError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.details = details or {}


@dataclass(slots=True)
class SearchPlannerPlan:
    strategy_summary: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    extra_search_queries: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ToolCallResult:
    tool: str
    arguments: dict[str, Any]
    success: bool
    error: str | None = None
    duration_ms: int = 0
    hit_count: int = 0
    message_count: int = 0
    group_count: int = 0
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ConversationalPlanExecution:
    plan: SearchPlannerPlan
    tool_results: list[ToolCallResult]
    accumulated_hits: list[SearchHit]
    grouped_results: list[GroupedSearchResult]


@dataclass(slots=True)
class ToolRunnerDeps:
    nim_client: NimClient | None = None
    embedding_adapter: EmbeddingAdapter | None = None
    embedding_model_name: str = ""


@dataclass
class _RunnerState:
    accumulated_hits: list[SearchHit] = field(default_factory=list)
    grouped_results: list[GroupedSearchResult] = field(default_factory=list)


def _extract_json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    if not text:
        raise PlannerParseError("Planner returned empty content")
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fence:
        text = fence.group(1)

    def _with_json_context(exc: json.JSONDecodeError, source: str) -> PlannerParseError:
        start = max(0, exc.pos - 240)
        end = min(len(source), exc.pos + 240)
        context = source[start:end]
        return PlannerParseError(
            f"Planner output is not valid JSON: {exc.msg} at char {exc.pos}",
            details={
                "error_position": exc.pos,
                "content_length": len(source),
                "content_preview": source[:500],
                "error_context": context,
                "possibly_truncated": exc.pos >= max(0, len(source) - 8),
            },
        )

    def _without_trailing_commas(source: str) -> str:
        return re.sub(r",\s*([}\]])", r"\1", source)

    decoder = json.JSONDecoder()
    last_error: json.JSONDecodeError | None = None
    candidates: list[str] = [text]
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        candidates.append(text[start : end + 1])
    for candidate in list(candidates):
        repaired = _without_trailing_commas(candidate)
        if repaired != candidate:
            candidates.append(repaired)

    for candidate in candidates:
        try:
            payload = json.loads(candidate)
            break
        except json.JSONDecodeError as exc:
            last_error = exc
        for index, char in enumerate(candidate):
            if char != "{":
                continue
            try:
                payload, _end = decoder.raw_decode(candidate[index:])
                break
            except json.JSONDecodeError as exc:
                last_error = exc
        else:
            continue
        break
    else:
        if last_error is not None:
            raise _with_json_context(last_error, text) from last_error
        raise PlannerParseError(
            "Planner output is not valid JSON: no JSON object found",
            details={"content_preview": content[:500], "content_length": len(content)},
        )
    if not isinstance(payload, dict):
        raise PlannerParseError("Planner output must be a JSON object")
    return payload


def parse_planner_plan(content: str) -> SearchPlannerPlan:
    payload = _extract_json_object(content)
    strategy = payload.get("strategy_summary")
    tool_calls = payload.get("tool_calls", [])
    if not isinstance(strategy, str) or not strategy.strip():
        raise PlannerParseError("Planner output missing non-empty strategy_summary")
    if not isinstance(tool_calls, list):
        raise PlannerParseError("tool_calls must be an array when provided")
    validated: list[dict[str, Any]] = []
    for index, call in enumerate(tool_calls):
        if not isinstance(call, dict):
            raise PlannerParseError(f"tool_calls[{index}] must be an object")
        tool = call.get("tool")
        if tool is not None and tool not in PLANNER_TOOLS:
            raise PlannerParseError(
                f"tool_calls[{index}] has unsupported tool '{tool}'",
                details={"allowed_tools": sorted(PLANNER_TOOLS)},
            )
        validated.append(dict(call))
    extra_queries: list[str] = []
    raw_extra = payload.get("extra_search_queries", [])
    if isinstance(raw_extra, list):
        extra_queries.extend(str(item).strip() for item in raw_extra if str(item).strip())
    for call in validated:
        if call.get("tool") == "fts":
            query = str(call.get("query", "")).strip()
            if query:
                extra_queries.append(query)
    return SearchPlannerPlan(
        strategy_summary=strategy.strip(),
        tool_calls=validated,
        extra_search_queries=extra_queries,
    )


def _message_details(conn: sqlite3.Connection, dataset_id: int, message_id: str) -> dict[str, str | int | None]:
    row = conn.execute(
        """
        SELECT sender_display, timestamp, body, thread_ordinal, sort_index
        FROM message
        WHERE dataset_id = ? AND message_id = ?
        """,
        (dataset_id, message_id),
    ).fetchone()
    if row is None:
        return {
            "sender_display": "",
            "timestamp": "",
            "body": "",
            "thread_ordinal": None,
            "sort_index": None,
        }
    thread_ordinal = row["thread_ordinal"]
    return {
        "sender_display": row["sender_display"],
        "timestamp": row["timestamp"],
        "body": row["body"],
        "thread_ordinal": int(thread_ordinal) if thread_ordinal is not None else None,
        "sort_index": int(row["sort_index"]),
    }


def _fts_to_hits(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    dataset_id: int,
    query: str,
) -> list[SearchHit]:
    results = fts.search_messages(conn, logger, dataset_id, query, limit=None)
    hits: list[SearchHit] = []
    for fts_hit in results["hits"]:
        details = _message_details(conn, dataset_id, fts_hit.message_id)
        retrieval_method = {
            "exact": "fts_exact",
            "partial": "fts_partial",
            "fuzzy": "spellfix_fuzzy",
        }[fts_hit.match_type]
        hits.append(
            SearchHit(
                message_id=fts_hit.message_id,
                source_thread_id=fts_hit.source_thread_id,
                match_type=fts_hit.match_type,
                retrieval_method=retrieval_method,
                query_text=query,
                matched_term=query,
                score=fts_hit.rank,
                sender_display=str(details["sender_display"]),
                timestamp=str(details["timestamp"]),
                body=str(details["body"]),
                snippet=str(details["body"])[:160],
                thread_ordinal=details["thread_ordinal"],  # type: ignore[arg-type]
                sort_index=details["sort_index"],  # type: ignore[arg-type]
            )
        )
    return fuse_hits(hits)


def _keyword_expansion_hits(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    client: NimClient,
    dataset_id: int,
    query: str,
) -> tuple[list[str], list[SearchHit]]:
    router = ModelRouter(load_settings())
    terms = expand_keywords(conn, logger, router, query, dataset_id=dataset_id)
    hits: list[SearchHit] = []
    for term in terms:
        for fts_hit in fts.search_exact(conn, logger, dataset_id, term):
            details = _message_details(conn, dataset_id, fts_hit.message_id)
            hits.append(
                SearchHit(
                    message_id=fts_hit.message_id,
                    source_thread_id=fts_hit.source_thread_id,
                    match_type="keyword",
                    retrieval_method="keyword_expansion",
                    query_text=query,
                    matched_term=term,
                    score=fts_hit.rank,
                    sender_display=details["sender_display"],
                    timestamp=details["timestamp"],
                    body=details["body"],
                    snippet=details["body"][:160],
                )
            )
    return terms, fuse_hits(hits)


def _messages_in_range(
    conn: sqlite3.Connection,
    dataset_id: int,
    source_thread_id: str,
    start_message_id: str,
    end_message_id: str,
) -> list[Message]:
    start_ordinal = repositories.message_ordinal(
        conn, dataset_id, source_thread_id, start_message_id
    )
    end_ordinal = repositories.message_ordinal(
        conn, dataset_id, source_thread_id, end_message_id
    )
    if start_ordinal is None or end_ordinal is None:
        return []
    if start_ordinal > end_ordinal:
        start_ordinal, end_ordinal = end_ordinal, start_ordinal
    return repositories.fetch_messages_for_slot_range(
        conn,
        dataset_id,
        source_thread_id,
        start_ordinal,
        end_ordinal + 1,
    )


def execute_tool_call(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    *,
    dataset_id: int,
    user_query: str,
    call: dict[str, Any],
    state: _RunnerState,
    deps: ToolRunnerDeps,
) -> ToolCallResult:
    tool = str(call["tool"])
    started = time.perf_counter()
    arguments = {key: value for key, value in call.items() if key != "tool"}
    try:
        if tool == "fts":
            query = str(arguments.get("query", "")).strip()
            if not query:
                raise ValueError("fts tool requires non-empty query")
            hits = _fts_to_hits(conn, logger, dataset_id, query)
            state.accumulated_hits = fuse_hits(state.accumulated_hits, hits)
            result = ToolCallResult(
                tool=tool,
                arguments=arguments,
                success=True,
                hit_count=len(hits),
                details={"query": query, "message_ids": [hit.message_id for hit in hits[:20]]},
            )
        elif tool == "keyword_expansion":
            query = str(arguments.get("query", user_query)).strip()
            if not query:
                raise ValueError("keyword_expansion tool requires non-empty query")
            if deps.nim_client is None:
                raise ValueError("NIM client is not configured for keyword_expansion")
            terms, hits = _keyword_expansion_hits(
                conn, logger, deps.nim_client, dataset_id, query
            )
            state.accumulated_hits = fuse_hits(state.accumulated_hits, hits)
            result = ToolCallResult(
                tool=tool,
                arguments=arguments,
                success=True,
                hit_count=len(hits),
                details={"query": query, "terms": terms},
            )
        elif tool == "message_embedding":
            query = str(arguments.get("query", user_query)).strip()
            top_k = int(arguments.get("top_k", 20))
            if not query:
                raise ValueError("message_embedding tool requires non-empty query")
            if deps.embedding_adapter is None or not deps.embedding_model_name:
                raise ValueError("Embedding adapter is not configured for message_embedding")
            hits = search_message_embeddings(
                conn,
                logger,
                dataset_id=dataset_id,
                query=query,
                model_name=deps.embedding_model_name,
                adapter=deps.embedding_adapter,
                top_k=top_k,
            )
            state.accumulated_hits = fuse_hits(state.accumulated_hits, hits)
            result = ToolCallResult(
                tool=tool,
                arguments=arguments,
                success=True,
                hit_count=len(hits),
                details={"query": query, "top_k": top_k},
            )
        elif tool == "chunk_embedding":
            query = str(arguments.get("query", user_query)).strip()
            top_k = int(arguments.get("top_k", 20))
            if not query:
                raise ValueError("chunk_embedding tool requires non-empty query")
            if deps.embedding_adapter is None or not deps.embedding_model_name:
                raise ValueError("Embedding adapter is not configured for chunk_embedding")
            hits = search_chunk_embeddings(
                conn,
                logger,
                dataset_id=dataset_id,
                query=query,
                model_name=deps.embedding_model_name,
                adapter=deps.embedding_adapter,
                top_k=top_k,
            )
            state.accumulated_hits = fuse_hits(state.accumulated_hits, hits)
            result = ToolCallResult(
                tool=tool,
                arguments=arguments,
                success=True,
                hit_count=len(hits),
                details={"query": query, "top_k": top_k},
            )
        elif tool == "read_source_thread":
            source_thread_id = str(arguments.get("source_thread_id", "")).strip()
            max_messages = int(arguments.get("max_messages", 50))
            if not source_thread_id:
                raise ValueError("read_source_thread requires source_thread_id")
            messages = repositories.fetch_messages_for_slot_range(
                conn, dataset_id, source_thread_id, 0, max_messages
            )
            selected = messages
            result = ToolCallResult(
                tool=tool,
                arguments=arguments,
                success=True,
                message_count=len(selected),
                details={
                    "source_thread_id": source_thread_id,
                    "message_ids": [message.message_id for message in selected[:20]],
                },
            )
        elif tool == "read_message_range":
            source_thread_id = str(arguments.get("source_thread_id", "")).strip()
            start_message_id = str(arguments.get("start_message_id", "")).strip()
            end_message_id = str(arguments.get("end_message_id", "")).strip()
            if not source_thread_id or not start_message_id or not end_message_id:
                raise ValueError(
                    "read_message_range requires source_thread_id, start_message_id, end_message_id"
                )
            selected = _messages_in_range(
                conn,
                dataset_id,
                source_thread_id,
                start_message_id,
                end_message_id,
            )
            if not selected:
                raise ValueError("Message range not found in source thread")
            result = ToolCallResult(
                tool=tool,
                arguments=arguments,
                success=True,
                message_count=len(selected),
                details={
                    "source_thread_id": source_thread_id,
                    "message_ids": [message.message_id for message in selected],
                },
            )
        elif tool == "group_hits":
            groups = group_hits(
                state.accumulated_hits,
                logger=logger,
                dataset_id=dataset_id,
            )
            state.grouped_results = groups
            result = ToolCallResult(
                tool=tool,
                arguments=arguments,
                success=True,
                group_count=len(groups),
                details={"group_ids": [group.group_id for group in groups[:20]]},
            )
        else:
            raise ValueError(f"Unsupported tool '{tool}'")
    except (ValueError, EmbeddingIndexNotReadyError, RuntimeError, sqlite3.OperationalError) as exc:
        result = ToolCallResult(
            tool=tool,
            arguments=arguments,
            success=False,
            error=str(exc),
        )
        logger.error(
            component="search.tool_runner",
            operation="tool_failed",
            message=f"Tool {tool} failed",
            details={"tool": tool, "arguments": arguments, "error": str(exc)},
            exc=exc,
            dataset_id=dataset_id,
        )
    result.duration_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        component="search.tool_runner",
        operation="tool_complete",
        message=f"Tool {tool} finished",
        details={
            "tool": tool,
            "arguments": arguments,
            "success": result.success,
            "duration_ms": result.duration_ms,
            "hit_count": result.hit_count,
            "message_count": result.message_count,
            "group_count": result.group_count,
            "error": result.error,
        },
        dataset_id=dataset_id,
    )
    return result


def execute_full_search_harness(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    *,
    dataset_id: int,
    user_query: str,
    plan: SearchPlannerPlan,
    deps: ToolRunnerDeps,
) -> ConversationalPlanExecution:
    """Run every retrieval method, fuse, then group. Recall-first; never skip a channel."""
    logger.info(
        component="search.tool_runner",
        operation="search_harness_start",
        message="Running full conversational search harness (all retrieval methods)",
        details={
            "user_query": user_query,
            "strategy_summary": plan.strategy_summary,
            "extra_search_queries": plan.extra_search_queries,
        },
        dataset_id=dataset_id,
    )
    state = _RunnerState()
    tool_results: list[ToolCallResult] = []

    fts_queries: list[str] = [user_query]
    seen_queries = {user_query.casefold()}
    for extra in plan.extra_search_queries:
        key = extra.casefold()
        if key not in seen_queries:
            seen_queries.add(key)
            fts_queries.append(extra)

    for fts_query in fts_queries:
        tool_results.append(
            execute_tool_call(
                conn,
                logger,
                dataset_id=dataset_id,
                user_query=user_query,
                call={"tool": "fts", "query": fts_query},
                state=state,
                deps=deps,
            )
        )

    if deps.nim_client is not None:
        tool_results.append(
            execute_tool_call(
                conn,
                logger,
                dataset_id=dataset_id,
                user_query=user_query,
                call={"tool": "keyword_expansion", "query": user_query},
                state=state,
                deps=deps,
            )
        )
    else:
        tool_results.append(
            ToolCallResult(
                tool="keyword_expansion",
                arguments={"query": user_query},
                success=False,
                error="NIM not configured — keyword expansion skipped",
            )
        )

    tool_results.append(
        execute_tool_call(
            conn,
            logger,
            dataset_id=dataset_id,
            user_query=user_query,
            call={"tool": "message_embedding", "query": user_query},
            state=state,
            deps=deps,
        )
    )
    tool_results.append(
        execute_tool_call(
            conn,
            logger,
            dataset_id=dataset_id,
            user_query=user_query,
            call={"tool": "chunk_embedding", "query": user_query},
            state=state,
            deps=deps,
        )
    )

    if state.accumulated_hits:
        tool_results.append(
            execute_tool_call(
                conn,
                logger,
                dataset_id=dataset_id,
                user_query=user_query,
                call={"tool": "group_hits"},
                state=state,
                deps=deps,
            )
        )

    execution = ConversationalPlanExecution(
        plan=plan,
        tool_results=tool_results,
        accumulated_hits=state.accumulated_hits,
        grouped_results=state.grouped_results,
    )
    logger.info(
        component="search.tool_runner",
        operation="search_harness_complete",
        message="Full search harness finished",
        details={
            "steps": len(tool_results),
            "failed_steps": [item.tool for item in tool_results if not item.success],
            "hit_count": len(state.accumulated_hits),
            "group_count": len(state.grouped_results),
            "retrieval_methods": sorted(
                {hit.retrieval_method for hit in state.accumulated_hits}
                | {method for hit in state.accumulated_hits for method in hit.extra_methods}
            ),
        },
        dataset_id=dataset_id,
    )
    return execution


def execute_plan(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    *,
    dataset_id: int,
    user_query: str,
    plan: SearchPlannerPlan,
    deps: ToolRunnerDeps,
) -> ConversationalPlanExecution:
    return execute_full_search_harness(
        conn,
        logger,
        dataset_id=dataset_id,
        user_query=user_query,
        plan=plan,
        deps=deps,
    )


def fetch_conversational_plan(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    client: NimClient,
    *,
    user_query: str,
    dataset_id: int,
) -> SearchPlannerPlan:
    chat = run_nim_chat(
        conn,
        logger,
        client,
        run_type=RUN_TYPE_CONVERSATIONAL_PLANNER,
        user_content=user_query,
        dataset_id=dataset_id,
    )
    plan = parse_planner_plan(chat.content)
    logger.info(
        component="search.tool_runner",
        operation="plan_parsed",
        message="Planner output validated",
        details={
            "strategy_summary": plan.strategy_summary,
            "extra_search_queries": plan.extra_search_queries,
        },
        dataset_id=dataset_id,
    )
    return plan


def run_conversational_planner(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    client: NimClient,
    *,
    user_query: str,
    dataset_id: int,
    deps: ToolRunnerDeps,
) -> ConversationalPlanExecution:
    plan = fetch_conversational_plan(
        conn, logger, client, user_query=user_query, dataset_id=dataset_id
    )
    return execute_plan(
        conn,
        logger,
        dataset_id=dataset_id,
        user_query=user_query,
        plan=plan,
        deps=deps,
    )
