"""Conversational search result synthesis (T18)."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.nim.client import NimClient
from message_evidence_workstation.nim.model_runs import run_nim_chat
from message_evidence_workstation.nim.prompts import RUN_TYPE_CONVERSATIONAL_SYNTHESIS
from message_evidence_workstation.search.result_models import GroupedSearchResult, SearchHit
from message_evidence_workstation.search.tool_runner import (
    ConversationalPlanExecution,
    PlannerParseError,
    SearchPlannerPlan,
    _extract_json_object,
)

MAX_GROUPS_FOR_SYNTHESIS = 25
MAX_HITS_PER_GROUP = 10


class SynthesisParseError(ValueError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.details = details or {}


@dataclass(slots=True)
class SynthesisCandidate:
    group_id: str
    title: str
    explanation: str
    confidence: str
    group: GroupedSearchResult | None = None


@dataclass(slots=True)
class ConversationalSynthesisResult:
    answer: str
    strategy_summary: str
    candidates: list[SynthesisCandidate] = field(default_factory=list)


def _hit_summary(hit: SearchHit) -> dict[str, Any]:
    return {
        "message_id": hit.message_id,
        "sender": hit.sender_display,
        "timestamp": hit.timestamp,
        "snippet": (hit.snippet or hit.body)[:200],
        "retrieval_method": hit.retrieval_method,
        "matched_term": hit.matched_term,
        "score": hit.score,
        "rank": hit.rank,
        "distance": hit.distance,
    }


def _group_payload(group: GroupedSearchResult) -> dict[str, Any]:
    return {
        "group_id": group.group_id,
        "source_thread_id": group.source_thread_id,
        "title": group.title,
        "snippet": group.snippet[:300],
        "primary_hit_message_id": group.primary_hit_message_id,
        "retrieval_methods": sorted(group.retrieval_methods),
        "hits": [_hit_summary(hit) for hit in group.hits[:MAX_HITS_PER_GROUP]],
    }


def _fallback_groups_from_hits(
    hits: list[SearchHit],
    *,
    max_groups: int,
) -> list[GroupedSearchResult]:
    from uuid import uuid4

    groups: list[GroupedSearchResult] = []
    for hit in hits[:max_groups]:
        snippet = hit.snippet or hit.body or hit.message_id
        groups.append(
            GroupedSearchResult(
                group_id=str(uuid4()),
                source_thread_id=hit.source_thread_id,
                primary_hit_message_id=hit.message_id,
                hits=[hit],
                title=snippet[:80],
                snippet=snippet[:160],
                retrieval_methods={hit.retrieval_method} | set(hit.extra_methods),
            )
        )
    return groups


def build_synthesis_user_content(
    user_query: str,
    plan: SearchPlannerPlan,
    execution: ConversationalPlanExecution,
    *,
    max_groups: int = MAX_GROUPS_FOR_SYNTHESIS,
) -> str:
    groups = list(execution.grouped_results)
    if not groups and execution.accumulated_hits:
        groups = _fallback_groups_from_hits(execution.accumulated_hits, max_groups=max_groups)
    groups = groups[:max_groups]
    methods = sorted(
        {hit.retrieval_method for hit in execution.accumulated_hits}
        | {method for hit in execution.accumulated_hits for method in hit.extra_methods}
    )
    payload = {
        "user_query": user_query,
        "planner_strategy_summary": plan.strategy_summary,
        "retrieval_summary": {
            "total_hits": len(execution.accumulated_hits),
            "group_count": len(execution.grouped_results) or len(groups),
            "retrieval_methods": methods,
            "failed_tools": [item.tool for item in execution.tool_results if not item.success],
        },
        "candidate_groups": [_group_payload(group) for group in groups],
    }
    return json.dumps(payload, indent=2)


def parse_synthesis_response(
    content: str,
    *,
    groups_by_id: dict[str, GroupedSearchResult],
    fallback_strategy_summary: str,
) -> ConversationalSynthesisResult:
    payload = _extract_json_object(content)
    answer = payload.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        raise SynthesisParseError("Synthesis output missing non-empty answer")
    strategy = payload.get("strategy_summary", fallback_strategy_summary)
    if not isinstance(strategy, str) or not strategy.strip():
        strategy = fallback_strategy_summary
    raw_candidates = payload.get("candidate_conversations", [])
    if raw_candidates is None:
        raw_candidates = []
    if not isinstance(raw_candidates, list):
        raise SynthesisParseError("candidate_conversations must be an array when provided")

    candidates: list[SynthesisCandidate] = []
    seen_group_ids: set[str] = set()
    for index, item in enumerate(raw_candidates):
        if not isinstance(item, dict):
            raise SynthesisParseError(f"candidate_conversations[{index}] must be an object")
        group_id = str(item.get("group_id", "")).strip()
        if not group_id:
            continue
        if group_id in seen_group_ids:
            continue
        group = groups_by_id.get(group_id)
        if group is None:
            continue
        seen_group_ids.add(group_id)
        title = str(item.get("title", group.title)).strip() or group.title
        explanation = str(item.get("explanation", "")).strip()
        confidence = str(item.get("confidence", "medium")).strip().lower()
        if confidence not in {"high", "medium", "low"}:
            confidence = "medium"
        candidates.append(
            SynthesisCandidate(
                group_id=group_id,
                title=title,
                explanation=explanation,
                confidence=confidence,
                group=group,
            )
        )

    if not candidates and groups_by_id:
        for group in list(groups_by_id.values())[:MAX_GROUPS_FOR_SYNTHESIS]:
            candidates.append(
                SynthesisCandidate(
                    group_id=group.group_id,
                    title=group.title,
                    explanation="",
                    confidence="medium",
                    group=group,
                )
            )

    return ConversationalSynthesisResult(
        answer=answer.strip(),
        strategy_summary=strategy.strip(),
        candidates=candidates,
    )


def groups_index(execution: ConversationalPlanExecution) -> dict[str, GroupedSearchResult]:
    groups = list(execution.grouped_results)
    if not groups and execution.accumulated_hits:
        groups = _fallback_groups_from_hits(
            execution.accumulated_hits,
            max_groups=MAX_GROUPS_FOR_SYNTHESIS,
        )
    return {group.group_id: group for group in groups}


def run_conversational_synthesis(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    client: NimClient,
    *,
    user_query: str,
    plan: SearchPlannerPlan,
    execution: ConversationalPlanExecution,
    dataset_id: int,
) -> ConversationalSynthesisResult:
    groups_by_id = groups_index(execution)
    user_content = build_synthesis_user_content(user_query, plan, execution)
    logger.info(
        component="search.synthesis",
        operation="synthesis_start",
        message="Calling NIM to synthesize conversational search results",
        details={
            "user_query": user_query,
            "group_count": len(groups_by_id),
            "hit_count": len(execution.accumulated_hits),
            "payload_chars": len(user_content),
        },
        dataset_id=dataset_id,
    )
    try:
        chat = run_nim_chat(
            conn,
            logger,
            client,
            run_type=RUN_TYPE_CONVERSATIONAL_SYNTHESIS,
            user_content=user_content,
            dataset_id=dataset_id,
        )
        result = parse_synthesis_response(
            chat.content,
            groups_by_id=groups_by_id,
            fallback_strategy_summary=plan.strategy_summary,
        )
    except (PlannerParseError, SynthesisParseError) as exc:
        logger.error(
            component="search.synthesis",
            operation="synthesis_parse_failed",
            message=str(exc),
            exc=exc,
            dataset_id=dataset_id,
        )
        raise
    logger.info(
        component="search.synthesis",
        operation="synthesis_complete",
        message="Conversational synthesis finished",
        details={
            "candidate_count": len(result.candidates),
            "answer_preview": result.answer[:200],
        },
        dataset_id=dataset_id,
    )
    return result
