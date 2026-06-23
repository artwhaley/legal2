"""Coverage-aware conversational answering."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from typing import Any

from message_evidence_workstation.config.settings import AnswerSettings, load_settings
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.embeddings.chunking import config_from_mapping
from message_evidence_workstation.nim.client import NimClient
from message_evidence_workstation.nim.model_context import resolve_model_context
from message_evidence_workstation.nim.model_runs import run_nim_chat
from message_evidence_workstation.nim.prompts import (
    RUN_TYPE_COVERAGE_SESSION_ANSWER,
    RUN_TYPE_EXHAUSTIVE_WINDOW_MERGE,
    RUN_TYPE_EXHAUSTIVE_WINDOW_SCAN,
    RUN_TYPE_SESSION_CLASSIFICATION,
    RUN_TYPE_WHOLE_TRANSCRIPT_ANSWER,
)
from message_evidence_workstation.search.coverage_audit import run_coverage_audit
from message_evidence_workstation.search.retrieval_assist import (
    collect_retrieval_assists,
    promote_sessions_from_retrieval_assists,
)
from message_evidence_workstation.search.session_map import (
    TranscriptSession,
    list_sessions,
    rebuild_dataset_sessions,
    serialize_session_transcript,
)
from message_evidence_workstation.search.session_summaries import ensure_session_summaries
from message_evidence_workstation.search.tool_runner import (
    PlannerParseError,
    ToolRunnerDeps,
    _extract_json_object,
)
from message_evidence_workstation.search.transcript import (
    SerializedTranscript,
    load_dataset_messages,
    serialize_messages,
)
from message_evidence_workstation.search.token_budget import compute_usable_input_tokens, estimate_tokens
from message_evidence_workstation.search.window_planner import (
    TranscriptWindow,
    build_token_bounded_windows,
)

ANSWER_MODE_WHOLE_TRANSCRIPT = "whole_transcript"
ANSWER_MODE_EXHAUSTIVE_WINDOW_SCAN = "exhaustive_window_scan"
ANSWER_MODE_SESSION_COVERAGE = "session_coverage"
ANSWER_MODE_RETRIEVAL_FALLBACK = "retrieval_fallback"

ANSWER_STRATEGY_AUTO = "auto"
ANSWER_STRATEGY_WHOLE_TRANSCRIPT = "whole_transcript"
ANSWER_STRATEGY_EXHAUSTIVE_WINDOW_SCAN = "exhaustive_window_scan"
ANSWER_STRATEGY_SESSION_COVERAGE = "session_coverage"
ANSWER_STRATEGY_RETRIEVAL_FALLBACK = "retrieval_fallback"

DEFAULT_WHOLE_TRANSCRIPT_MAX_CHARS = 200_000
DEFAULT_MAX_INSPECTED_SESSIONS = 12
DEFAULT_TRANSCRIPT_WINDOW_PADDING = 2

SESSION_CLASS_RELEVANT = "relevant"
SESSION_CLASS_POSSIBLY_RELEVANT = "possibly_relevant"
SESSION_CLASS_NOT_RELEVANT = "not_relevant"
VALID_SESSION_CLASSIFICATIONS = frozenset(
    {SESSION_CLASS_RELEVANT, SESSION_CLASS_POSSIBLY_RELEVANT, SESSION_CLASS_NOT_RELEVANT}
)


class ConversationalAnswerParseError(ValueError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.details = details or {}


@dataclass(slots=True)
class CandidateEvidenceBlockDraft:
    title: str
    summary: str
    core_message_id: str
    relevant_start_message_id: str
    relevant_end_message_id: str
    leading_context_start_message_id: str
    trailing_context_end_message_id: str
    highlighted_message_ids: list[str]
    source_thread_id: str = ""


@dataclass(slots=True)
class CoverageSummary:
    mode: str
    messages_considered: int
    source_thread_ids: list[str]
    sessions_considered: int = 0
    sessions_inspected: int = 0
    sessions_skipped: int = 0
    windows_inspected: int = 0
    retrieval_assists: list[dict[str, Any]] = field(default_factory=list)
    token_budget: dict[str, Any] | None = None


@dataclass(slots=True)
class AnswerBudget:
    model_id: str
    context_window_tokens: int
    context_source: str
    safety_ratio: float
    reserved_output_tokens: int
    effective_reserved_output_tokens: int
    prompt_overhead_tokens: int
    usable_input_tokens: int
    transcript_tokens: int
    transcript_token_method: str
    decision: str


def _clamp_safety_ratio(value: float) -> float:
    return max(0.25, min(0.90, value))


def resolve_answer_budget(
    transcript: SerializedTranscript,
    answer_settings: AnswerSettings,
    model_id: str,
    provider_metadata: dict | None = None,
) -> AnswerBudget:
    override = answer_settings.context_window_override_tokens
    user_override = override if override > 0 else None
    model_context = resolve_model_context(
        model_id,
        provider_metadata=provider_metadata,
        user_override_tokens=user_override,
    )
    safety_ratio = _clamp_safety_ratio(answer_settings.context_safety_ratio)
    requested_output = max(1, answer_settings.reserved_output_tokens)
    prompt_overhead = max(0, answer_settings.prompt_overhead_tokens)
    usable_input, effective_output = compute_usable_input_tokens(
        context_window_tokens=model_context.context_window_tokens,
        safety_ratio=safety_ratio,
        reserved_output_tokens=requested_output,
        prompt_overhead_tokens=prompt_overhead,
    )
    token_estimate = estimate_tokens(transcript.text, model_id)
    strategy = answer_settings.answer_strategy
    if strategy == ANSWER_STRATEGY_RETRIEVAL_FALLBACK:
        decision = ANSWER_MODE_RETRIEVAL_FALLBACK
    elif strategy == ANSWER_STRATEGY_SESSION_COVERAGE:
        decision = ANSWER_MODE_SESSION_COVERAGE
    elif strategy == ANSWER_STRATEGY_EXHAUSTIVE_WINDOW_SCAN:
        decision = ANSWER_MODE_EXHAUSTIVE_WINDOW_SCAN
    elif strategy == ANSWER_STRATEGY_WHOLE_TRANSCRIPT:
        decision = (
            ANSWER_MODE_WHOLE_TRANSCRIPT
            if token_estimate.estimated_tokens <= usable_input
            else ANSWER_MODE_EXHAUSTIVE_WINDOW_SCAN
        )
    else:
        decision = (
            ANSWER_MODE_WHOLE_TRANSCRIPT
            if token_estimate.estimated_tokens <= usable_input
            else ANSWER_MODE_EXHAUSTIVE_WINDOW_SCAN
        )
    return AnswerBudget(
        model_id=model_id,
        context_window_tokens=model_context.context_window_tokens,
        context_source=model_context.source,
        safety_ratio=safety_ratio,
        reserved_output_tokens=requested_output,
        effective_reserved_output_tokens=effective_output,
        prompt_overhead_tokens=prompt_overhead,
        usable_input_tokens=usable_input,
        transcript_tokens=token_estimate.estimated_tokens,
        transcript_token_method=token_estimate.method,
        decision=decision,
    )


def log_answer_budget_resolved(
    logger: ProcessLogger,
    *,
    budget: AnswerBudget,
    dataset_id: int | None,
    strategy: str,
    window_count: int = 0,
    target_tokens: int = 0,
    overlap_messages: int = 0,
) -> None:
    logger.info(
        component="search.conversational_answer",
        operation="answer_budget_resolved",
        message="Resolved conversational answer token budget",
        details={
            "model_id": budget.model_id,
            "context_window_tokens": budget.context_window_tokens,
            "context_source": budget.context_source,
            "transcript_tokens": budget.transcript_tokens,
            "usable_input_tokens": budget.usable_input_tokens,
            "decision": budget.decision,
            "strategy": strategy,
            "window_count": window_count,
            "target_tokens": target_tokens,
            "overlap_messages": overlap_messages,
            "reserved_output_tokens": budget.reserved_output_tokens,
            "effective_reserved_output_tokens": budget.effective_reserved_output_tokens,
            "prompt_overhead_tokens": budget.prompt_overhead_tokens,
            "transcript_token_method": budget.transcript_token_method,
        },
        dataset_id=dataset_id,
    )


@dataclass(slots=True)
class ConversationalAnswerResult:
    answer: str
    cited_message_ids: list[str]
    candidate_evidence_blocks: list[CandidateEvidenceBlockDraft]
    uncertainties: list[str]
    coverage_summary: CoverageSummary
    mode: str
    removed_invalid_citation_ids: list[str] = field(default_factory=list)
    removed_invalid_block_ids: list[str] = field(default_factory=list)


def resolve_answer_mode(
    *,
    strategy: str,
    transcript: SerializedTranscript,
    answer_settings: AnswerSettings | None = None,
    model_id: str = "",
    provider_metadata: dict | None = None,
    max_chars: int = DEFAULT_WHOLE_TRANSCRIPT_MAX_CHARS,
) -> str:
    del max_chars  # retained for backward compatibility; auto no longer uses char limits
    settings = answer_settings or AnswerSettings(answer_strategy=strategy)
    if strategy != settings.answer_strategy:
        settings = AnswerSettings(**{**asdict(settings), "answer_strategy": strategy})
    budget = resolve_answer_budget(
        transcript,
        settings,
        model_id=model_id or "unknown-model",
        provider_metadata=provider_metadata,
    )
    return budget.decision


def build_dataset_transcript(
    conn: sqlite3.Connection,
    dataset_id: int,
) -> SerializedTranscript:
    messages = load_dataset_messages(conn, dataset_id)
    thread_ids = sorted({message.source_thread_id for message in messages})
    transcript = serialize_messages(messages)
    transcript.source_thread_id = thread_ids[0] if len(thread_ids) == 1 else ""
    return transcript


def build_whole_transcript_user_content(user_query: str, transcript: SerializedTranscript) -> str:
    thread_ids = sorted({line.source_thread_id for line in transcript.lines})
    payload = {
        "user_query": user_query,
        "transcript": transcript.text,
        "message_ids": transcript.message_ids,
        "source_thread_ids": thread_ids,
        "messages_considered": len(transcript.message_ids),
    }
    return json.dumps(payload, ensure_ascii=False)


def _filter_valid_ids(ids: list[str], valid_ids: set[str]) -> tuple[list[str], list[str]]:
    kept: list[str] = []
    removed: list[str] = []
    for message_id in ids:
        if message_id in valid_ids:
            if message_id not in kept:
                kept.append(message_id)
        else:
            removed.append(message_id)
    return kept, removed


def _parse_candidate_block(
    raw: dict[str, Any],
    *,
    valid_ids: set[str],
    message_thread_by_id: dict[str, str],
) -> tuple[CandidateEvidenceBlockDraft | None, list[str]]:
    removed: list[str] = []
    boundary_fields = (
        "core_message_id",
        "relevant_start_message_id",
        "relevant_end_message_id",
        "leading_context_start_message_id",
        "trailing_context_end_message_id",
    )
    values: dict[str, str] = {}
    for field_name in boundary_fields:
        value = str(raw.get(field_name, "")).strip()
        if not value:
            return None, [f"missing:{field_name}"]
        if value not in valid_ids:
            removed.append(value)
            return None, removed
        values[field_name] = value
    highlighted_raw = raw.get("highlighted_message_ids") or []
    if not isinstance(highlighted_raw, list):
        highlighted_raw = []
    highlighted, highlight_removed = _filter_valid_ids(
        [str(item).strip() for item in highlighted_raw if str(item).strip()],
        valid_ids,
    )
    removed.extend(highlight_removed)
    core_id = values["core_message_id"]
    return CandidateEvidenceBlockDraft(
        title=str(raw.get("title", "")).strip() or "Evidence block",
        summary=str(raw.get("summary", "")).strip(),
        core_message_id=core_id,
        relevant_start_message_id=values["relevant_start_message_id"],
        relevant_end_message_id=values["relevant_end_message_id"],
        leading_context_start_message_id=values["leading_context_start_message_id"],
        trailing_context_end_message_id=values["trailing_context_end_message_id"],
        highlighted_message_ids=highlighted or [core_id],
        source_thread_id=message_thread_by_id.get(core_id, ""),
    ), removed


def parse_whole_transcript_answer_response(
    content: str,
    *,
    valid_message_ids: set[str],
    message_thread_by_id: dict[str, str],
    source_thread_ids: list[str],
    messages_considered: int,
) -> ConversationalAnswerResult:
    try:
        payload = _extract_json_object(content)
    except PlannerParseError as exc:
        raise ConversationalAnswerParseError(
            f"Model response is not valid JSON: {exc}",
            details=exc.details,
        ) from exc
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        raise ConversationalAnswerParseError(f"Model response is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ConversationalAnswerParseError("Model response must be a JSON object")
    return _parse_answer_payload(
        payload,
        valid_message_ids=valid_message_ids,
        message_thread_by_id=message_thread_by_id,
        source_thread_ids=source_thread_ids,
        messages_considered=messages_considered,
        mode=ANSWER_MODE_WHOLE_TRANSCRIPT,
    )


def parse_coverage_session_answer_response(
    content: str,
    *,
    valid_message_ids: set[str],
    message_thread_by_id: dict[str, str],
    source_thread_ids: list[str],
    messages_considered: int,
    sessions_considered: int,
    sessions_inspected: int,
    sessions_skipped: int,
    retrieval_assists: list[dict[str, Any]] | None = None,
) -> ConversationalAnswerResult:
    try:
        payload = _extract_json_object(content)
    except PlannerParseError as exc:
        raise ConversationalAnswerParseError(
            f"Model response is not valid JSON: {exc}",
            details=exc.details,
        ) from exc
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        raise ConversationalAnswerParseError(f"Model response is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ConversationalAnswerParseError("Model response must be a JSON object")
    return _parse_answer_payload(
        payload,
        valid_message_ids=valid_message_ids,
        message_thread_by_id=message_thread_by_id,
        source_thread_ids=source_thread_ids,
        messages_considered=messages_considered,
        mode=ANSWER_MODE_SESSION_COVERAGE,
        sessions_considered=sessions_considered,
        sessions_inspected=sessions_inspected,
        sessions_skipped=sessions_skipped,
        retrieval_assists=retrieval_assists,
    )


def _parse_answer_payload(
    payload: dict[str, Any],
    *,
    valid_message_ids: set[str],
    message_thread_by_id: dict[str, str],
    source_thread_ids: list[str],
    messages_considered: int,
    mode: str,
    sessions_considered: int = 0,
    sessions_inspected: int = 0,
    sessions_skipped: int = 0,
    retrieval_assists: list[dict[str, Any]] | None = None,
    allow_empty_answer: bool = False,
) -> ConversationalAnswerResult:
    answer = str(payload.get("answer", "")).strip()
    if not answer and not allow_empty_answer:
        raise ConversationalAnswerParseError("Model response missing non-empty answer")

    cited_raw = payload.get("cited_message_ids") or []
    if not isinstance(cited_raw, list):
        cited_raw = []
    cited_ids, removed_citations = _filter_valid_ids(
        [str(item).strip() for item in cited_raw if str(item).strip()],
        valid_message_ids,
    )

    candidates: list[CandidateEvidenceBlockDraft] = []
    removed_block_ids: list[str] = []
    blocks_raw = payload.get("candidate_evidence_blocks") or []
    if not isinstance(blocks_raw, list):
        blocks_raw = []
    for item in blocks_raw:
        if not isinstance(item, dict):
            continue
        candidate, removed = _parse_candidate_block(
            item,
            valid_ids=valid_message_ids,
            message_thread_by_id=message_thread_by_id,
        )
        removed_block_ids.extend(removed)
        if candidate is not None:
            candidates.append(candidate)

    uncertainties_raw = payload.get("uncertainties") or []
    if not isinstance(uncertainties_raw, list):
        uncertainties_raw = []
    uncertainties = [str(item).strip() for item in uncertainties_raw if str(item).strip()]
    if removed_citations:
        uncertainties.append(
            f"Removed {len(removed_citations)} invented or unknown cited message ID(s)."
        )
    if removed_block_ids:
        uncertainties.append(
            f"Skipped candidate evidence block(s) with invalid message ID(s): "
            f"{', '.join(sorted(set(removed_block_ids)))}"
        )

    coverage_raw = payload.get("coverage_summary") or {}
    if not isinstance(coverage_raw, dict):
        coverage_raw = {}
    coverage = CoverageSummary(
        mode=str(coverage_raw.get("mode") or mode),
        messages_considered=int(coverage_raw.get("messages_considered") or messages_considered),
        source_thread_ids=[
            str(item)
            for item in (coverage_raw.get("source_thread_ids") or source_thread_ids)
            if str(item).strip()
        ]
        or list(source_thread_ids),
        sessions_considered=int(coverage_raw.get("sessions_considered") or sessions_considered),
        sessions_inspected=int(coverage_raw.get("sessions_inspected") or sessions_inspected),
        sessions_skipped=int(coverage_raw.get("sessions_skipped") or sessions_skipped),
        windows_inspected=int(coverage_raw.get("windows_inspected") or 0),
        retrieval_assists=list(retrieval_assists or coverage_raw.get("retrieval_assists") or []),
        token_budget=coverage_raw.get("token_budget"),
    )

    return ConversationalAnswerResult(
        answer=answer,
        cited_message_ids=cited_ids,
        candidate_evidence_blocks=candidates,
        uncertainties=uncertainties,
        coverage_summary=coverage,
        mode=mode,
        removed_invalid_citation_ids=removed_citations,
        removed_invalid_block_ids=sorted(set(removed_block_ids)),
    )


def run_whole_transcript_answer(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    client: NimClient,
    *,
    user_query: str,
    dataset_id: int,
    transcript: SerializedTranscript | None = None,
    max_tokens: int | None = None,
) -> ConversationalAnswerResult:
    transcript = transcript or build_dataset_transcript(conn, dataset_id)
    valid_ids = set(transcript.message_ids)
    message_thread_by_id = {line.message_id: line.source_thread_id for line in transcript.lines}
    source_thread_ids = sorted({line.source_thread_id for line in transcript.lines})
    user_content = build_whole_transcript_user_content(user_query, transcript)
    result = run_nim_chat(
        conn,
        logger,
        client,
        run_type=RUN_TYPE_WHOLE_TRANSCRIPT_ANSWER,
        user_content=user_content,
        dataset_id=dataset_id,
        max_tokens=max_tokens,
    )
    parsed = parse_whole_transcript_answer_response(
        result.content,
        valid_message_ids=valid_ids,
        message_thread_by_id=message_thread_by_id,
        source_thread_ids=source_thread_ids,
        messages_considered=len(transcript.message_ids),
    )
    if parsed.removed_invalid_citation_ids or parsed.removed_invalid_block_ids:
        logger.warning(
            component="search.conversational_answer",
            operation="invalid_message_ids_removed",
            message="Removed invented or unknown message IDs from model response",
            details={
                "removed_citations": parsed.removed_invalid_citation_ids,
                "removed_block_ids": parsed.removed_invalid_block_ids,
            },
            dataset_id=dataset_id,
        )
    return parsed


def build_session_classification_user_content(
    user_query: str,
    sessions: list[TranscriptSession],
) -> str:
    summaries = [
        {
            "session_id": session.session_id,
            "source_thread_id": session.source_thread_id,
            "calendar_date": session.calendar_date,
            "title": session.title,
            "participants": session.participants,
            "message_count": session.message_count,
            "summary": session.summary_json or {},
        }
        for session in sessions
    ]
    return json.dumps(
        {"user_query": user_query, "session_summaries": summaries},
        ensure_ascii=False,
    )


def parse_session_classifications(
    content: str,
    expected_session_ids: list[str],
) -> tuple[dict[str, str], list[str]]:
    payload = _extract_json_object(content)
    if not isinstance(payload, dict):
        raise ConversationalAnswerParseError("Session classification response must be a JSON object")
    rows = payload.get("session_classifications") or []
    if not isinstance(rows, list):
        rows = []
    classifications: dict[str, str] = {}
    uncertainties: list[str] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        session_id = str(item.get("session_id", "")).strip()
        classification = str(item.get("classification", "")).strip()
        if not session_id or classification not in VALID_SESSION_CLASSIFICATIONS:
            continue
        classifications[session_id] = classification
    for session_id in expected_session_ids:
        if session_id not in classifications:
            classifications[session_id] = SESSION_CLASS_NOT_RELEVANT
            uncertainties.append(
                f"Session {session_id} was not classified by the model; treated as not_relevant."
            )
    return classifications, uncertainties


def classify_sessions_for_query(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    client: NimClient,
    *,
    user_query: str,
    dataset_id: int,
    sessions: list[TranscriptSession],
) -> tuple[dict[str, str], list[str]]:
    expected_ids = [session.session_id for session in sessions]
    result = run_nim_chat(
        conn,
        logger,
        client,
        run_type=RUN_TYPE_SESSION_CLASSIFICATION,
        user_content=build_session_classification_user_content(user_query, sessions),
        dataset_id=dataset_id,
    )
    return parse_session_classifications(result.content, expected_ids)


def _select_sessions_for_inspection(
    sessions: list[TranscriptSession],
    classifications: dict[str, str],
    *,
    max_inspected_sessions: int,
) -> tuple[list[TranscriptSession], list[TranscriptSession]]:
    relevant = [
        session
        for session in sessions
        if classifications.get(session.session_id) == SESSION_CLASS_RELEVANT
    ]
    possibly = [
        session
        for session in sessions
        if classifications.get(session.session_id) == SESSION_CLASS_POSSIBLY_RELEVANT
    ]
    inspected = (relevant + possibly)[: max(1, max_inspected_sessions)]
    inspected_ids = {session.session_id for session in inspected}
    skipped = [session for session in sessions if session.session_id not in inspected_ids]
    return inspected, skipped


def build_session_coverage_user_content(
    user_query: str,
    *,
    sessions: list[TranscriptSession],
    classifications: dict[str, str],
    inspected_windows: list[dict[str, Any]],
) -> str:
    return json.dumps(
        {
            "user_query": user_query,
            "session_summaries": [
                {
                    "session_id": session.session_id,
                    "classification": classifications.get(session.session_id, SESSION_CLASS_NOT_RELEVANT),
                    "title": session.title,
                    "summary": session.summary_json or {},
                }
                for session in sessions
            ],
            "inspected_transcript_windows": inspected_windows,
        },
        ensure_ascii=False,
    )


def build_exhaustive_window_scan_user_content(
    user_query: str,
    *,
    window: TranscriptWindow,
) -> str:
    return json.dumps(
        {
            "user_query": user_query,
            "scan_instruction": (
                "Inspect this transcript window for the question. Return relevant findings "
                "with message IDs, or say this window contains no relevant evidence."
            ),
            "window_id": window.window_id,
            "session_id": window.session_id,
            "source_thread_id": window.source_thread_id,
            "estimated_tokens": window.estimated_tokens,
            "message_ids": window.message_ids,
            "messages_considered": len(window.message_ids),
            "transcript": window.text,
        },
        ensure_ascii=False,
    )


def build_exhaustive_window_merge_user_content(
    user_query: str,
    *,
    sessions: list[TranscriptSession],
    window_results: list[dict[str, Any]],
    retrieval_assists: list[dict[str, Any]] | None = None,
    token_budget: dict[str, Any] | None = None,
) -> str:
    source_thread_ids = sorted({session.source_thread_id for session in sessions})
    messages_considered = len(
        {
            message_id
            for window in window_results
            for message_id in window.get("message_ids", [])
        }
    )
    return json.dumps(
        {
            "user_query": user_query,
            "merge_instruction": (
                "Every window listed here was inspected. Merge the findings into one final "
                "answer. Do not invent message IDs."
            ),
            "coverage_summary": {
                "mode": ANSWER_MODE_EXHAUSTIVE_WINDOW_SCAN,
                "messages_considered": messages_considered,
                "source_thread_ids": source_thread_ids,
                "sessions_considered": len(sessions),
                "sessions_inspected": len({window.get("session_id") for window in window_results}),
                "sessions_skipped": max(
                    0,
                    len(sessions) - len({window.get("session_id") for window in window_results}),
                ),
                "windows_inspected": len(window_results),
                "retrieval_assists": list(retrieval_assists or []),
                "token_budget": token_budget or {},
            },
            "window_findings": window_results,
        },
        ensure_ascii=False,
    )


def _compact_window_result_for_merge(window: dict[str, Any]) -> dict[str, Any]:
    return {
        "window_id": window.get("window_id"),
        "session_id": window.get("session_id"),
        "source_thread_id": window.get("source_thread_id"),
        "message_ids": list(window.get("message_ids", [])),
        "estimated_tokens": window.get("estimated_tokens"),
        "answer": window.get("answer", ""),
        "cited_message_ids": list(window.get("cited_message_ids", [])),
        "candidate_evidence_blocks": list(window.get("candidate_evidence_blocks", [])),
        "uncertainties": list(window.get("uncertainties", [])),
    }


def _estimate_merge_user_content_tokens(
    user_query: str,
    *,
    sessions: list[TranscriptSession],
    window_results: list[dict[str, Any]],
    retrieval_assists: list[dict[str, Any]] | None,
    token_budget: dict[str, Any] | None,
    model_id: str,
) -> int:
    content = build_exhaustive_window_merge_user_content(
        user_query,
        sessions=sessions,
        window_results=[_compact_window_result_for_merge(window) for window in window_results],
        retrieval_assists=retrieval_assists,
        token_budget=token_budget,
    )
    return estimate_tokens(content, model_id).estimated_tokens


def _interim_window_from_answer(
    result: ConversationalAnswerResult,
    *,
    window_id: str,
    message_ids: list[str],
    source_thread_id: str,
) -> dict[str, Any]:
    return {
        "window_id": window_id,
        "session_id": "merged_batch",
        "source_thread_id": source_thread_id,
        "message_ids": message_ids,
        "estimated_tokens": 0,
        "answer": result.answer,
        "cited_message_ids": list(result.cited_message_ids),
        "candidate_evidence_blocks": [asdict(candidate) for candidate in result.candidate_evidence_blocks],
        "uncertainties": list(result.uncertainties),
    }


def _run_bounded_exhaustive_window_merge(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    client: NimClient,
    *,
    user_query: str,
    sessions: list[TranscriptSession],
    window_results: list[dict[str, Any]],
    retrieval_assists: list[dict[str, Any]] | None,
    token_budget: dict[str, Any] | None,
    budget: AnswerBudget,
    dataset_id: int,
    max_tokens: int,
    model_id: str,
    valid_ids: set[str],
    message_thread_by_id: dict[str, str],
    source_thread_ids: list[str],
) -> ConversationalAnswerResult:
    def merge_batch(batch: list[dict[str, Any]], depth: int = 0) -> ConversationalAnswerResult:
        compact_batch = [_compact_window_result_for_merge(window) for window in batch]
        estimated_tokens = _estimate_merge_user_content_tokens(
            user_query,
            sessions=sessions,
            window_results=compact_batch,
            retrieval_assists=retrieval_assists if depth == 0 else [],
            token_budget=token_budget if depth == 0 else None,
            model_id=model_id,
        )
        if estimated_tokens > budget.usable_input_tokens and len(batch) > 1:
            mid = max(1, len(batch) // 2)
            logger.info(
                component="search.conversational_answer",
                operation="exhaustive_window_merge_chunked",
                message="Merge payload exceeded budget; splitting window findings",
                details={
                    "estimated_tokens": estimated_tokens,
                    "usable_input_tokens": budget.usable_input_tokens,
                    "batch_size": len(batch),
                    "depth": depth,
                },
                dataset_id=dataset_id,
            )
            left = merge_batch(batch[:mid], depth + 1)
            right = merge_batch(batch[mid:], depth + 1)
            left_ids = sorted(
                {
                    message_id
                    for window in batch[:mid]
                    for message_id in window.get("message_ids", [])
                }
            )
            right_ids = sorted(
                {
                    message_id
                    for window in batch[mid:]
                    for message_id in window.get("message_ids", [])
                }
            )
            interim_batch = [
                _interim_window_from_answer(
                    left,
                    window_id=f"merged_left_{depth}",
                    message_ids=left_ids,
                    source_thread_id=source_thread_ids[0] if source_thread_ids else "",
                ),
                _interim_window_from_answer(
                    right,
                    window_id=f"merged_right_{depth}",
                    message_ids=right_ids,
                    source_thread_id=source_thread_ids[0] if source_thread_ids else "",
                ),
            ]
            return merge_batch(interim_batch, depth + 1)

        merge = run_nim_chat(
            conn,
            logger,
            client,
            run_type=RUN_TYPE_EXHAUSTIVE_WINDOW_MERGE,
            user_content=build_exhaustive_window_merge_user_content(
                user_query,
                sessions=sessions,
                window_results=compact_batch,
                retrieval_assists=retrieval_assists if depth == 0 else [],
                token_budget=token_budget if depth == 0 else None,
            ),
            dataset_id=dataset_id,
            max_tokens=max_tokens,
        )
        return parse_exhaustive_window_merge_response(
            merge.content,
            valid_message_ids=valid_ids,
            message_thread_by_id=message_thread_by_id,
            source_thread_ids=source_thread_ids,
            messages_considered=len(valid_ids),
            sessions_considered=len(sessions),
            sessions_inspected=len({window.get("session_id") for window in window_results}),
            sessions_skipped=max(
                0,
                len(sessions) - len({window.get("session_id") for window in window_results}),
            ),
            retrieval_assists=retrieval_assists if depth == 0 else [],
        )

    if not window_results:
        raise ConversationalAnswerParseError("No window findings available to merge")
    if len(window_results) == 1:
        only = window_results[0]
        return parse_exhaustive_window_merge_response(
            json.dumps(
                {
                    "answer": only.get("answer", ""),
                    "cited_message_ids": only.get("cited_message_ids", []),
                    "candidate_evidence_blocks": only.get("candidate_evidence_blocks", []),
                    "uncertainties": only.get("uncertainties", []),
                }
            ),
            valid_message_ids=valid_ids,
            message_thread_by_id=message_thread_by_id,
            source_thread_ids=source_thread_ids,
            messages_considered=len(valid_ids),
            sessions_considered=len(sessions),
            sessions_inspected=len({window.get("session_id") for window in window_results}),
            sessions_skipped=max(
                0,
                len(sessions) - len({window.get("session_id") for window in window_results}),
            ),
            retrieval_assists=retrieval_assists,
        )
    return merge_batch(window_results)


def parse_exhaustive_window_scan_response(
    content: str,
    *,
    valid_message_ids: set[str],
    message_thread_by_id: dict[str, str],
    source_thread_ids: list[str],
    messages_considered: int,
) -> ConversationalAnswerResult:
    try:
        payload = _extract_json_object(content)
    except PlannerParseError as exc:
        raise ConversationalAnswerParseError(
            f"Window scan response is not valid JSON: {exc}",
            details=exc.details,
        ) from exc
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        raise ConversationalAnswerParseError(f"Window scan response is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ConversationalAnswerParseError("Window scan response must be a JSON object")
    return _parse_answer_payload(
        payload,
        valid_message_ids=valid_message_ids,
        message_thread_by_id=message_thread_by_id,
        source_thread_ids=source_thread_ids,
        messages_considered=messages_considered,
        mode=ANSWER_MODE_EXHAUSTIVE_WINDOW_SCAN,
        allow_empty_answer=True,
    )


def parse_exhaustive_window_merge_response(
    content: str,
    *,
    valid_message_ids: set[str],
    message_thread_by_id: dict[str, str],
    source_thread_ids: list[str],
    messages_considered: int,
    sessions_considered: int,
    sessions_inspected: int,
    sessions_skipped: int,
    retrieval_assists: list[dict[str, Any]] | None = None,
) -> ConversationalAnswerResult:
    try:
        payload = _extract_json_object(content)
    except PlannerParseError as exc:
        raise ConversationalAnswerParseError(
            f"Window merge response is not valid JSON: {exc}",
            details=exc.details,
        ) from exc
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        raise ConversationalAnswerParseError(f"Window merge response is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ConversationalAnswerParseError("Window merge response must be a JSON object")
    return _parse_answer_payload(
        payload,
        valid_message_ids=valid_message_ids,
        message_thread_by_id=message_thread_by_id,
        source_thread_ids=source_thread_ids,
        messages_considered=messages_considered,
        mode=ANSWER_MODE_EXHAUSTIVE_WINDOW_SCAN,
        sessions_considered=sessions_considered,
        sessions_inspected=sessions_inspected,
        sessions_skipped=sessions_skipped,
        retrieval_assists=retrieval_assists,
    )


def run_exhaustive_window_scan_answer(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    client: NimClient,
    *,
    user_query: str,
    dataset_id: int,
    transcript_window_padding: int = DEFAULT_TRANSCRIPT_WINDOW_PADDING,
    session_gap_minutes: int = 120,
    deps: ToolRunnerDeps | None = None,
    answer_settings: AnswerSettings | None = None,
    model_id: str | None = None,
    provider_metadata: dict | None = None,
    max_tokens: int | None = None,
) -> ConversationalAnswerResult:
    settings = answer_settings or load_settings().answer
    selected_model = model_id or client.settings.model or "unknown-model"
    chunking_config = config_from_mapping(load_settings().chunking)
    chunking_config.session_gap_hours = max(1, session_gap_minutes) / 60.0
    sessions = rebuild_dataset_sessions(
        conn,
        logger,
        dataset_id,
        gap_minutes=session_gap_minutes,
        chunking_config=chunking_config,
        use_semantic_chunks=True,
    )
    if not sessions:
        raise ConversationalAnswerParseError("No transcript sessions available for exhaustive window scan")

    budget = resolve_answer_budget(
        build_dataset_transcript(conn, dataset_id),
        settings,
        selected_model,
        provider_metadata=provider_metadata,
    )
    planned_windows = build_token_bounded_windows(
        conn,
        dataset_id,
        sessions,
        target_tokens=min(settings.window_target_tokens, budget.usable_input_tokens),
        overlap_messages=settings.window_overlap_messages,
        model_id=selected_model,
    )
    logger.info(
        component="search.conversational_answer",
        operation="window_plan_built",
        message="Built token-bounded transcript windows for exhaustive scan",
        details={
            "window_count": len(planned_windows),
            "target_tokens": settings.window_target_tokens,
            "overlap_messages": settings.window_overlap_messages,
            "sessions_considered": len(sessions),
        },
        dataset_id=dataset_id,
    )
    logger.info(
        component="search.conversational_answer",
        operation="exhaustive_window_scan_selected",
        message="Running exhaustive window scan over planned windows",
        details={
            "window_count": len(planned_windows),
            "model_id": selected_model,
            "context_window_tokens": budget.context_window_tokens,
            "context_source": budget.context_source,
        },
        dataset_id=dataset_id,
    )
    token_budget = {
        "window_target_tokens": settings.window_target_tokens,
        "context_window_tokens": budget.context_window_tokens,
        "context_source": budget.context_source,
        "safety_ratio": budget.safety_ratio,
    }

    retrieval_assists = collect_retrieval_assists(
        conn,
        logger,
        dataset_id=dataset_id,
        user_query=user_query,
        sessions=sessions,
        deps=deps,
    )
    window_results: list[dict[str, Any]] = []
    valid_ids: set[str] = set()
    message_thread_by_id: dict[str, str] = {}
    source_thread_ids = sorted({session.source_thread_id for session in sessions})
    scan_uncertainties: list[str] = []
    output_tokens = max_tokens if max_tokens is not None else budget.effective_reserved_output_tokens
    merge_max_tokens = max(output_tokens, min(4096, budget.effective_reserved_output_tokens))

    for window in planned_windows:
        session_valid_ids = set(window.message_ids)
        session_thread_by_id = {
            message_id: window.source_thread_id for message_id in window.message_ids
        }
        scan = run_nim_chat(
            conn,
            logger,
            client,
            run_type=RUN_TYPE_EXHAUSTIVE_WINDOW_SCAN,
            user_content=build_exhaustive_window_scan_user_content(user_query, window=window),
            dataset_id=dataset_id,
            max_tokens=output_tokens,
        )
        parsed_scan = parse_exhaustive_window_scan_response(
            scan.content,
            valid_message_ids=session_valid_ids,
            message_thread_by_id=session_thread_by_id,
            source_thread_ids=[window.source_thread_id],
            messages_considered=len(window.message_ids),
        )
        valid_ids.update(window.message_ids)
        message_thread_by_id.update(session_thread_by_id)
        scan_uncertainties.extend(parsed_scan.uncertainties)
        window_results.append(
            {
                "window_id": window.window_id,
                "session_id": window.session_id,
                "source_thread_id": window.source_thread_id,
                "estimated_tokens": window.estimated_tokens,
                "message_ids": window.message_ids,
                "answer": parsed_scan.answer,
                "cited_message_ids": parsed_scan.cited_message_ids,
                "candidate_evidence_blocks": [
                    asdict(candidate)
                    for candidate in parsed_scan.candidate_evidence_blocks
                ],
                "uncertainties": parsed_scan.uncertainties,
            }
        )

    parsed = _run_bounded_exhaustive_window_merge(
        conn,
        logger,
        client,
        user_query=user_query,
        sessions=sessions,
        window_results=window_results,
        retrieval_assists=retrieval_assists,
        token_budget=token_budget,
        budget=budget,
        dataset_id=dataset_id,
        max_tokens=merge_max_tokens,
        model_id=selected_model,
        valid_ids=valid_ids,
        message_thread_by_id=message_thread_by_id,
        source_thread_ids=source_thread_ids,
    )
    parsed.coverage_summary.windows_inspected = len(planned_windows)
    parsed.coverage_summary.token_budget = token_budget
    parsed.uncertainties = scan_uncertainties + parsed.uncertainties
    return parsed


def run_session_coverage_answer(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    client: NimClient,
    *,
    user_query: str,
    dataset_id: int,
    max_inspected_sessions: int = DEFAULT_MAX_INSPECTED_SESSIONS,
    transcript_window_padding: int = DEFAULT_TRANSCRIPT_WINDOW_PADDING,
    session_gap_minutes: int = 120,
    deps: ToolRunnerDeps | None = None,
    max_tokens: int | None = None,
) -> ConversationalAnswerResult:
    chunking_config = config_from_mapping(load_settings().chunking)
    chunking_config.session_gap_hours = max(1, session_gap_minutes) / 60.0
    sessions = rebuild_dataset_sessions(
        conn,
        logger,
        dataset_id,
        gap_minutes=session_gap_minutes,
        chunking_config=chunking_config,
        use_semantic_chunks=True,
    )
    if not sessions:
        raise ConversationalAnswerParseError("No transcript sessions available for session-coverage mode")
    sessions = ensure_session_summaries(conn, logger, client, dataset_id)
    classifications, classification_uncertainties = classify_sessions_for_query(
        conn,
        logger,
        client,
        user_query=user_query,
        dataset_id=dataset_id,
        sessions=sessions,
    )
    retrieval_assists = collect_retrieval_assists(
        conn,
        logger,
        dataset_id=dataset_id,
        user_query=user_query,
        sessions=sessions,
        deps=deps,
    )
    classifications, assist_notes = promote_sessions_from_retrieval_assists(
        classifications,
        retrieval_assists,
        inspected_session_ids=set(),
    )
    inspected_sessions, skipped_sessions = _select_sessions_for_inspection(
        sessions,
        classifications,
        max_inspected_sessions=max_inspected_sessions,
    )
    audit = run_coverage_audit(
        conn,
        logger,
        client,
        user_query=user_query,
        dataset_id=dataset_id,
        sessions=sessions,
        classifications=classifications,
        inspected_session_ids=[session.session_id for session in inspected_sessions],
        skipped_sessions=skipped_sessions,
        retrieval_assists=retrieval_assists,
    )
    if audit.additional_session_ids:
        inspected_ids = {session.session_id for session in inspected_sessions}
        for session in sessions:
            if session.session_id in audit.additional_session_ids and session.session_id not in inspected_ids:
                inspected_sessions.append(session)
                inspected_ids.add(session.session_id)
        skipped_sessions = [session for session in sessions if session.session_id not in inspected_ids]
    inspected_windows: list[dict[str, Any]] = []
    valid_ids: set[str] = set()
    message_thread_by_id: dict[str, str] = {}
    for session in inspected_sessions:
        transcript_text, message_ids = serialize_session_transcript(
            conn,
            dataset_id,
            session,
            padding=transcript_window_padding,
        )
        inspected_windows.append(
            {
                "session_id": session.session_id,
                "source_thread_id": session.source_thread_id,
                "classification": classifications.get(session.session_id),
                "transcript": transcript_text,
                "message_ids": message_ids,
            }
        )
        valid_ids.update(message_ids)
        for message_id in message_ids:
            message_thread_by_id[message_id] = session.source_thread_id
    user_content = build_session_coverage_user_content(
        user_query,
        sessions=sessions,
        classifications=classifications,
        inspected_windows=inspected_windows,
    )
    result = run_nim_chat(
        conn,
        logger,
        client,
        run_type=RUN_TYPE_COVERAGE_SESSION_ANSWER,
        user_content=user_content,
        dataset_id=dataset_id,
        max_tokens=max_tokens,
    )
    source_thread_ids = sorted({session.source_thread_id for session in sessions})
    parsed = parse_coverage_session_answer_response(
        result.content,
        valid_message_ids=valid_ids,
        message_thread_by_id=message_thread_by_id,
        source_thread_ids=source_thread_ids,
        messages_considered=len(valid_ids),
        sessions_considered=len(sessions),
        sessions_inspected=len(inspected_sessions),
        sessions_skipped=len(skipped_sessions),
        retrieval_assists=retrieval_assists,
    )
    parsed.uncertainties = (
        classification_uncertainties + assist_notes + audit.residual_uncertainties + parsed.uncertainties
    )
    if audit.audit_notes:
        parsed.uncertainties.append(audit.audit_notes)
    return parsed
