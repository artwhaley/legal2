"""Conversational answering."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from typing import Any

from message_evidence_workstation.config.settings import AnswerSettings, NimSettings, load_settings
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.llm.router import ModelRouter
from message_evidence_workstation.nim.model_context import resolve_model_context
from message_evidence_workstation.nim.message_roles import build_whole_transcript_cache_messages
from message_evidence_workstation.nim.model_runs import run_nim_chat
from message_evidence_workstation.nim.prompts import (
    RUN_TYPE_EVIDENCE_LEDGER_SYNTHESIS,
    RUN_TYPE_EXHAUSTIVE_WINDOW_MERGE,
    RUN_TYPE_EXHAUSTIVE_WINDOW_SCAN,
    RUN_TYPE_WHOLE_TRANSCRIPT_ANSWER,
    get_active_prompt,
)
from message_evidence_workstation.search.evidence_ledger import (
    assemble_ledger_result,
    build_evidence_ledger,
    build_evidence_ledger_synthesis_messages,
    batch_context_to_dicts,
    ledger_to_dicts,
    plan_ledger_budget,
)
from message_evidence_workstation.search.ledger_validator import (
    validate_assembled_ledger_output,
    validate_ledger_analysis_output,
)
from message_evidence_workstation.search.dataset_budget import (
    DatasetBudgetStats,
    compute_dataset_budget_stats,
    estimate_transcript_tokens_from_stats,
)
from message_evidence_workstation.search.exhaustive_hints import (
    ExhaustiveHintBlock,
    collect_exhaustive_window_hints,
)
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
    build_token_bounded_windows_for_dataset,
)

ANSWER_MODE_WHOLE_TRANSCRIPT = "whole_transcript"
ANSWER_MODE_EXHAUSTIVE_WINDOW_SCAN = "exhaustive_window_scan"

ANSWER_STRATEGY_WHOLE_TRANSCRIPT = "whole_transcript"
ANSWER_STRATEGY_EXHAUSTIVE_WINDOW_SCAN = "exhaustive_window_scan"

DEFAULT_TRANSCRIPT_WINDOW_PADDING = 2


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
class AnswerRangeDraft:
    title: str
    summary: str
    hit_message_id: str
    start_message_id: str
    end_message_id: str
    source_thread_id: str = ""
    date_description: str = ""
    display_text: str = ""


@dataclass(slots=True)
class CoverageSummary:
    mode: str
    messages_considered: int
    source_thread_ids: list[str]
    windows_inspected: int = 0
    retrieval_assists: list[dict[str, Any]] = field(default_factory=list)
    token_budget: dict[str, Any] | None = None


@dataclass(slots=True)
class AnswerBudget:
    model_id: str
    context_window_tokens: int
    context_source: str
    safety_ratio: float
    max_output_tokens: int
    prompt_overhead_tokens: int
    usable_input_tokens: int
    transcript_tokens: int
    transcript_token_method: str
    decision: str


def _clamp_safety_ratio(value: float) -> float:
    return max(0.25, min(0.90, value))


def resolve_answer_budget(
    stats: DatasetBudgetStats,
    answer_settings: AnswerSettings,
    model_id: str,
    *,
    nim_settings: NimSettings | None = None,
    provider_metadata: dict | None = None,
) -> AnswerBudget:
    nim = nim_settings or NimSettings()
    model_context = resolve_model_context(
        model_id,
        context_window_tokens=nim.context_window_tokens,
        provider_metadata=provider_metadata,
    )
    safety_ratio = _clamp_safety_ratio(nim.context_safety_ratio)
    max_output_tokens = max(1, nim.max_output_tokens)
    prompt_overhead = max(0, nim.prompt_overhead_tokens)
    usable_input = compute_usable_input_tokens(
        context_window_tokens=model_context.context_window_tokens,
        safety_ratio=safety_ratio,
        prompt_overhead_tokens=prompt_overhead,
        max_output_tokens=max_output_tokens,
    )
    token_estimate = estimate_transcript_tokens_from_stats(stats)
    strategy = answer_settings.answer_strategy
    if strategy == ANSWER_STRATEGY_EXHAUSTIVE_WINDOW_SCAN:
        decision = ANSWER_MODE_EXHAUSTIVE_WINDOW_SCAN
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
        max_output_tokens=max_output_tokens,
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
    stats: DatasetBudgetStats | None = None,
    window_count: int = 0,
    target_tokens: int = 0,
    overlap_messages: int = 0,
) -> None:
    details: dict[str, Any] = {
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
        "max_output_tokens": budget.max_output_tokens,
        "prompt_overhead_tokens": budget.prompt_overhead_tokens,
        "transcript_token_method": budget.transcript_token_method,
    }
    if stats is not None:
        token_estimate = estimate_transcript_tokens_from_stats(stats)
        details.update(
            {
                "message_count": stats.message_count,
                "thread_count": stats.thread_count,
                "total_body_chars": stats.total_body_chars,
                "total_body_normalized_chars": stats.total_body_normalized_chars,
                "largest_thread_message_count": stats.largest_thread_message_count,
                "estimator_safety_margin": token_estimate.safety_margin,
                "message_overhead_chars": token_estimate.message_overhead_chars,
                "thread_overhead_chars": token_estimate.thread_overhead_chars,
            }
        )
    logger.info(
        component="search.conversational_answer",
        operation="answer_budget_resolved",
        message="Resolved conversational answer token budget",
        details=details,
        dataset_id=dataset_id,
    )


@dataclass(slots=True)
class RangeRepairRecord:
    original_start_message_id: str
    original_hit_message_id: str
    original_end_message_id: str
    repaired_start_message_id: str
    repaired_end_message_id: str
    reason: str = "range_order"
    title: str = ""


@dataclass(slots=True)
class ConversationalAnswerResult:
    answer: str
    cited_message_ids: list[str]
    candidate_evidence_blocks: list[CandidateEvidenceBlockDraft]
    uncertainties: list[str]
    coverage_summary: CoverageSummary
    mode: str
    answer_ranges: list[AnswerRangeDraft] = field(default_factory=list)
    answer_summary: str = ""
    answer_format: str = "detailed"
    removed_invalid_citation_ids: list[str] = field(default_factory=list)
    removed_invalid_block_ids: list[str] = field(default_factory=list)
    repaired_answer_ranges: list[RangeRepairRecord] = field(default_factory=list)


def resolve_answer_mode(
    *,
    strategy: str,
    stats: DatasetBudgetStats,
    answer_settings: AnswerSettings | None = None,
    nim_settings: NimSettings | None = None,
    model_id: str = "",
    provider_metadata: dict | None = None,
) -> str:
    settings = answer_settings or AnswerSettings(answer_strategy=strategy)
    if strategy != settings.answer_strategy:
        settings = AnswerSettings(**{**asdict(settings), "answer_strategy": strategy})
    budget = resolve_answer_budget(
        stats,
        settings,
        model_id=model_id or "unknown-model",
        nim_settings=nim_settings,
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


def _message_order_by_thread_from_lines(lines) -> dict[str, list[str]]:  # noqa: ANN001
    order: dict[str, list[str]] = {}
    for line in lines:
        order.setdefault(line.source_thread_id, []).append(line.message_id)
    return order


def _message_order_by_thread_from_db(
    conn: sqlite3.Connection,
    dataset_id: int,
) -> dict[str, list[str]]:
    rows = conn.execute(
        """
        SELECT source_thread_id, message_id
        FROM message
        WHERE dataset_id = ?
        ORDER BY source_thread_id, sort_index
        """,
        (dataset_id,),
    ).fetchall()
    order: dict[str, list[str]] = {}
    for row in rows:
        order.setdefault(str(row["source_thread_id"]), []).append(str(row["message_id"]))
    return order


def build_whole_transcript_context_content(transcript: SerializedTranscript) -> str:
    """Stable transcript payload for cache-friendly requests (same per dataset)."""
    thread_ids = sorted({line.source_thread_id for line in transcript.lines})
    payload = {
        "transcript": transcript.text,
        "message_ids": transcript.message_ids,
        "source_thread_ids": thread_ids,
        "messages_considered": len(transcript.message_ids),
    }
    return json.dumps(payload, ensure_ascii=False)


def build_whole_transcript_query_content(user_query: str) -> str:
    """Per-request question payload appended after stable transcript context."""
    return json.dumps({"user_query": user_query}, ensure_ascii=False)


def build_whole_transcript_user_content(user_query: str, transcript: SerializedTranscript) -> str:
    """Legacy combined payload with stable fields before the question (query last)."""
    context = json.loads(build_whole_transcript_context_content(transcript))
    context["user_query"] = user_query
    return json.dumps(context, ensure_ascii=False)


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


def _thread_order(
    message_order_by_thread: dict[str, list[str]] | None,
    source_thread_id: str,
) -> list[str]:
    if message_order_by_thread is None:
        return []
    return message_order_by_thread.get(source_thread_id, [])


def _context_boundary_ids(
    ordered_ids: list[str],
    *,
    start_message_id: str,
    end_message_id: str,
    leading_count: int = 3,
    trailing_count: int = 3,
) -> tuple[str, str]:
    if not ordered_ids or start_message_id not in ordered_ids or end_message_id not in ordered_ids:
        return start_message_id, end_message_id
    start_index = ordered_ids.index(start_message_id)
    end_index = ordered_ids.index(end_message_id)
    return (
        ordered_ids[max(0, start_index - leading_count)],
        ordered_ids[min(len(ordered_ids) - 1, end_index + trailing_count)],
    )


def _parse_answer_range(
    raw: dict[str, Any],
    *,
    valid_ids: set[str],
    message_thread_by_id: dict[str, str],
    message_order_by_thread: dict[str, list[str]] | None,
) -> tuple[AnswerRangeDraft | None, CandidateEvidenceBlockDraft | None, list[str], RangeRepairRecord | None]:
    removed: list[str] = []
    hit_id = str(raw.get("hit_message_id", "")).strip()
    start_id = str(raw.get("start_message_id", "")).strip()
    end_id = str(raw.get("end_message_id", "")).strip()
    for field_name, message_id in (
        ("hit_message_id", hit_id),
        ("start_message_id", start_id),
        ("end_message_id", end_id),
    ):
        if not message_id:
            return None, None, [f"missing:{field_name}"], None
        if message_id not in valid_ids:
            removed.append(message_id)
    if removed:
        return None, None, removed, None

    thread_id = message_thread_by_id.get(hit_id, "")
    if not thread_id:
        return None, None, [hit_id], None
    if message_thread_by_id.get(start_id) != thread_id or message_thread_by_id.get(end_id) != thread_id:
        return None, None, [f"cross_thread:{start_id},{hit_id},{end_id}"], None

    title = str(raw.get("title", "")).strip() or "Evidence block"
    summary = str(raw.get("summary", "")).strip()
    date_description = str(raw.get("date_description", "")).strip()
    display_text = str(raw.get("display_text", "")).strip()

    ordered_ids = _thread_order(message_order_by_thread, thread_id)
    if ordered_ids:
        start_index = ordered_ids.index(start_id) if start_id in ordered_ids else -1
        hit_index = ordered_ids.index(hit_id) if hit_id in ordered_ids else -1
        end_index = ordered_ids.index(end_id) if end_id in ordered_ids else -1
        if start_index < 0 or hit_index < 0 or end_index < 0:
            return None, None, [f"missing_order:{start_id},{hit_id},{end_id}"], None
        if not (start_index <= hit_index <= end_index):
            _repair = RangeRepairRecord(
                original_start_message_id=start_id,
                original_hit_message_id=hit_id,
                original_end_message_id=end_id,
                repaired_start_message_id=hit_id,
                repaired_end_message_id=hit_id,
                reason="range_order",
                title=title,
            )
            answer_range = AnswerRangeDraft(
                title=title,
                summary=summary,
                hit_message_id=hit_id,
                start_message_id=hit_id,
                end_message_id=hit_id,
                source_thread_id=thread_id,
                date_description=date_description,
                display_text=display_text,
            )
            candidate = CandidateEvidenceBlockDraft(
                title=title,
                summary=summary,
                core_message_id=hit_id,
                relevant_start_message_id=hit_id,
                relevant_end_message_id=hit_id,
                leading_context_start_message_id=hit_id,
                trailing_context_end_message_id=hit_id,
                highlighted_message_ids=[hit_id],
                source_thread_id=thread_id,
            )
            return answer_range, candidate, [], _repair

    answer_range = AnswerRangeDraft(
        title=title,
        summary=summary,
        hit_message_id=hit_id,
        start_message_id=start_id,
        end_message_id=end_id,
        source_thread_id=thread_id,
        date_description=date_description,
        display_text=display_text,
    )
    context_start_id, context_end_id = _context_boundary_ids(
        ordered_ids,
        start_message_id=start_id,
        end_message_id=end_id,
    )
    candidate = CandidateEvidenceBlockDraft(
        title=title,
        summary=summary,
        core_message_id=hit_id,
        relevant_start_message_id=start_id,
        relevant_end_message_id=end_id,
        leading_context_start_message_id=context_start_id,
        trailing_context_end_message_id=context_end_id,
        highlighted_message_ids=[hit_id],
        source_thread_id=thread_id,
    )
    return answer_range, candidate, [], None


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
    message_order_by_thread: dict[str, list[str]] | None = None,
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
        message_order_by_thread=message_order_by_thread,
    )


def _parse_answer_payload(
    payload: dict[str, Any],
    *,
    valid_message_ids: set[str],
    message_thread_by_id: dict[str, str],
    source_thread_ids: list[str],
    messages_considered: int,
    mode: str,
    retrieval_assists: list[dict[str, Any]] | None = None,
    allow_empty_answer: bool = False,
    message_order_by_thread: dict[str, list[str]] | None = None,
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

    answer_ranges: list[AnswerRangeDraft] = []
    candidates: list[CandidateEvidenceBlockDraft] = []
    removed_block_ids: list[str] = []
    repair_records: list[RangeRepairRecord] = []
    ranges_raw = payload.get("answer_ranges") or []
    if not isinstance(ranges_raw, list):
        ranges_raw = []
    for item in ranges_raw:
        if not isinstance(item, dict):
            continue
        answer_range, candidate, removed, repair = _parse_answer_range(
            item,
            valid_ids=valid_message_ids,
            message_thread_by_id=message_thread_by_id,
            message_order_by_thread=message_order_by_thread,
        )
        removed_block_ids.extend(removed)
        if repair is not None:
            repair_records.append(repair)
        if answer_range is not None:
            answer_ranges.append(answer_range)
        if candidate is not None:
            candidates.append(candidate)

    blocks_raw = payload.get("candidate_evidence_blocks") or []
    if not answer_ranges and isinstance(blocks_raw, list):
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
                answer_ranges.append(
                    AnswerRangeDraft(
                        title=candidate.title,
                        summary=candidate.summary,
                        hit_message_id=candidate.core_message_id,
                        start_message_id=candidate.relevant_start_message_id,
                        end_message_id=candidate.relevant_end_message_id,
                        source_thread_id=candidate.source_thread_id,
                        display_text=candidate.summary,
                    )
                )

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
    if repair_records:
        uncertainties.append(
            f"Repaired {len(repair_records)} range(s) where the model supplied an invalid bracket: "
            f"{', '.join(record.title for record in repair_records)}."
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
        windows_inspected=int(coverage_raw.get("windows_inspected") or 0),
        retrieval_assists=list(retrieval_assists or coverage_raw.get("retrieval_assists") or []),
        token_budget=coverage_raw.get("token_budget"),
    )

    return ConversationalAnswerResult(
        answer=answer,
        cited_message_ids=cited_ids,
        answer_ranges=answer_ranges,
        answer_summary=str(payload.get("answer_summary", "")).strip() or answer,
        answer_format=(
            str(payload.get("answer_format", "detailed")).strip().lower()
            if str(payload.get("answer_format", "detailed")).strip().lower() in {"detailed", "brief"}
            else "detailed"
        ),
        candidate_evidence_blocks=candidates,
        uncertainties=uncertainties,
        coverage_summary=coverage,
        mode=mode,
        removed_invalid_citation_ids=removed_citations,
        removed_invalid_block_ids=sorted(set(removed_block_ids)),
        repaired_answer_ranges=repair_records,
    )


def run_whole_transcript_answer(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    router: ModelRouter,
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
    user_content = build_whole_transcript_query_content(user_query)
    prompt = get_active_prompt(conn, RUN_TYPE_WHOLE_TRANSCRIPT_ANSWER)
    if prompt is None:
        raise RuntimeError(f"No active prompt template for run_type={RUN_TYPE_WHOLE_TRANSCRIPT_ANSWER}")
    messages = build_whole_transcript_cache_messages(
        prompt["body"],
        transcript_context=build_whole_transcript_context_content(transcript),
        user_query_content=user_content,
    )
    result = run_nim_chat(
        conn,
        logger,
        router,
        run_type=RUN_TYPE_WHOLE_TRANSCRIPT_ANSWER,
        messages=messages,
        dataset_id=dataset_id,
        max_tokens=max_tokens,
    )
    parsed = parse_whole_transcript_answer_response(
        result.content,
        valid_message_ids=valid_ids,
        message_thread_by_id=message_thread_by_id,
        source_thread_ids=source_thread_ids,
        messages_considered=len(transcript.message_ids),
        message_order_by_thread=_message_order_by_thread_from_lines(transcript.lines),
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


def build_exhaustive_window_scan_user_content(
    user_query: str,
    *,
    window: TranscriptWindow,
    retrieval_hint_blocks: list[dict[str, Any]] | None = None,
) -> str:
    return json.dumps(
        {
            "user_query": user_query,
            "scan_instruction": (
                "Inspect this transcript window for the question. Return relevant findings "
                "with message IDs, or say this window contains no relevant evidence."
            ),
            "retrieval_hint_instruction": (
                "Retrieval hints are not exhaustive and are not answers. They identify "
                "message IDs or contiguous message ranges that lexical or vector search "
                "considered potentially relevant. Inspect the entire window. Return "
                "responsive ranges even if they are not listed as hints. Do not ignore "
                "hinted messages unless they are clearly incidental or non-responsive."
            ),
            "window_id": window.window_id,
            "source_thread_id": window.source_thread_id,
            "estimated_tokens": window.estimated_tokens,
            "messages_considered": len(window.message_ids),
            "retrieval_hints": list(retrieval_hint_blocks or []),
            "transcript": window.text,
        },
        ensure_ascii=False,
    )


def build_exhaustive_window_merge_user_content(
    user_query: str,
    *,
    source_thread_ids: list[str],
    window_results: list[dict[str, Any]],
    retrieval_assists: list[dict[str, Any]] | None = None,
    token_budget: dict[str, Any] | None = None,
) -> str:
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
        "source_thread_id": window.get("source_thread_id"),
        "message_ids": list(window.get("message_ids", [])),
        "estimated_tokens": window.get("estimated_tokens"),
        "answer_summary": window.get("answer_summary", ""),
        "answer_format": window.get("answer_format", "detailed"),
        "answer": window.get("answer", ""),
        "cited_message_ids": list(window.get("cited_message_ids", [])),
        "answer_ranges": list(window.get("answer_ranges", [])),
        "uncertainties": list(window.get("uncertainties", [])),
    }


def _serialize_hint_blocks_for_prompt(blocks: tuple[ExhaustiveHintBlock, ...]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for block in blocks:
        payload.append(
            {
                "source_thread_id": block.source_thread_id,
                "start_message_id": block.start_message_id,
                "end_message_id": block.end_message_id,
                "hit_message_ids": list(block.hit_message_ids),
                "terms": list(block.terms),
                "sources": list(block.sources),
            }
        )
    return payload


def _hint_source_counts(blocks: tuple[ExhaustiveHintBlock, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for block in blocks:
        for source in block.sources:
            counts[source] = counts.get(source, 0) + 1
    return counts


def _message_order_by_planned_windows(planned_windows: list[TranscriptWindow]) -> dict[str, list[str]]:
    ordered: dict[str, list[str]] = {}
    seen: dict[str, set[str]] = {}
    for window in planned_windows:
        bucket = ordered.setdefault(window.source_thread_id, [])
        seen_ids = seen.setdefault(window.source_thread_id, set())
        for message_id in window.message_ids:
            if message_id in seen_ids:
                continue
            seen_ids.add(message_id)
            bucket.append(message_id)
    return ordered


def _range_intersects_hint_blocks(
    answer_range: AnswerRangeDraft,
    blocks: tuple[ExhaustiveHintBlock, ...],
    *,
    message_order_by_thread: dict[str, list[str]],
    message_thread_by_id: dict[str, str],
) -> bool:
    thread_id = message_thread_by_id.get(answer_range.start_message_id) or message_thread_by_id.get(
        answer_range.hit_message_id
    )
    if not thread_id:
        return False
    ordered_ids = message_order_by_thread.get(thread_id)
    if not ordered_ids:
        return False
    positions = {message_id: index for index, message_id in enumerate(ordered_ids)}
    start_pos = positions.get(answer_range.start_message_id)
    end_pos = positions.get(answer_range.end_message_id)
    if start_pos is None or end_pos is None:
        return False
    low = min(start_pos, end_pos)
    high = max(start_pos, end_pos)
    for block in blocks:
        if block.source_thread_id != thread_id:
            continue
        block_start = positions.get(block.start_message_id)
        block_end = positions.get(block.end_message_id)
        if block_start is None or block_end is None:
            continue
        if max(low, min(block_start, block_end)) <= min(high, max(block_start, block_end)):
            return True
    return False


def _estimate_merge_user_content_tokens(
    user_query: str,
    *,
    source_thread_ids: list[str],
    window_results: list[dict[str, Any]],
    retrieval_assists: list[dict[str, Any]] | None,
    token_budget: dict[str, Any] | None,
    model_id: str,
) -> int:
    content = build_exhaustive_window_merge_user_content(
        user_query,
        source_thread_ids=source_thread_ids,
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
        "source_thread_id": source_thread_id,
        "message_ids": message_ids,
        "estimated_tokens": 0,
        "answer_summary": result.answer_summary,
        "answer_format": result.answer_format,
        "answer": result.answer,
        "cited_message_ids": list(result.cited_message_ids),
        "answer_ranges": [asdict(answer_range) for answer_range in result.answer_ranges],
        "uncertainties": list(result.uncertainties),
    }


def _run_evidence_ledger_window_merge(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    router: ModelRouter,
    *,
    user_query: str,
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
    logger.info(
        component="search.conversational_answer",
        operation="evidence_ledger_merge_selected",
        message="Evidence-ledger merge selected for exhaustive window scan",
        details={
            "use_evidence_ledger_merge": True,
            "window_count": len(window_results),
            "source_thread_count": len(source_thread_ids),
        },
        dataset_id=dataset_id,
    )

    entries, batch_ctx = build_evidence_ledger(window_results)
    entry_dicts = ledger_to_dicts(entries)
    batch_dicts = batch_context_to_dicts(batch_ctx)
    logger.info(
        component="search.conversational_answer",
        operation="evidence_ledger_built",
        message="Evidence ledger built from window results",
        details={
            "entry_count": len(entry_dicts),
            "batch_context_count": len(batch_dicts),
            "raw_answer_range_count_total": sum(
                int(window.get("raw_answer_range_count") or 0) for window in window_results
            ),
            "validated_answer_range_count_total": sum(
                len(window.get("answer_ranges") or []) for window in window_results
            ),
            "window_range_counts": [
                {
                    "window_id": str(window.get("window_id") or ""),
                    "source_thread_id": str(window.get("source_thread_id") or ""),
                    "raw_answer_range_count": window.get("raw_answer_range_count"),
                    "validated_answer_range_count": len(window.get("answer_ranges") or []),
                }
                for window in window_results
            ],
            "source_thread_ids": source_thread_ids,
        },
        dataset_id=dataset_id,
    )

    if not entry_dicts:
        logger.info(
            component="search.conversational_answer",
            operation="evidence_ledger_empty",
            message="Evidence ledger is empty; returning deterministic no-results",
            details={"window_count": len(window_results)},
            dataset_id=dataset_id,
        )
        return ConversationalAnswerResult(
            answer=(
                "Exhaustive Windowed Search examined the full selected data package "
                "and found no results. Please modify your search terms and try again."
            ),
            answer_summary=(
                "Exhaustive Windowed Search examined the full selected data package "
                "and found no results."
            ),
            cited_message_ids=[],
            candidate_evidence_blocks=[],
            uncertainties=[],
            coverage_summary=CoverageSummary(
                mode=ANSWER_MODE_EXHAUSTIVE_WINDOW_SCAN,
                messages_considered=len(valid_ids),
                source_thread_ids=source_thread_ids,
                windows_inspected=len(window_results),
                retrieval_assists=list(retrieval_assists or []),
                token_budget=token_budget,
            ),
            mode=ANSWER_MODE_EXHAUSTIVE_WINDOW_SCAN,
        )

    provisional = build_evidence_ledger_synthesis_messages(
        user_query, entry_dicts, batch_dicts, config=None,
    )
    config = plan_ledger_budget(
        entry_dicts, provisional,
        model_context_tokens=budget.context_window_tokens,
        max_output_tokens=max_tokens,
    )
    logger.info(
        component="search.conversational_answer",
        operation="evidence_ledger_budget_planned",
        message="Evidence-ledger budget planned",
        details={
            "mode": config.mode,
            "answer_format": config.answer_format,
            "estimated_input_tokens": config.estimated_input_tokens,
            "estimated_output_tokens": config.estimated_output_tokens,
            "available_input_tokens": config.available_input_tokens,
            "available_output_tokens": config.available_output_tokens,
            "overflow": config.overflow,
            "fallback_reason": config.fallback_reason,
        },
        dataset_id=dataset_id,
    )

    if config.overflow:
        logger.info(
            component="search.conversational_answer",
            operation="evidence_ledger_validation_failed",
            message="Budget overflow; cannot fit ledger in context window",
            details={
                "phase": "budget",
                "fallback_reason": config.fallback_reason,
                "entry_count": len(entry_dicts),
            },
            dataset_id=dataset_id,
        )
        raise ConversationalAnswerParseError(
            f"Evidence-ledger merge cannot fit within the available context budget: "
            f"{config.fallback_reason}. Multi-call splitting is not yet implemented."
        )

    messages = build_evidence_ledger_synthesis_messages(
        user_query, entry_dicts, batch_dicts, config,
    )
    logger.info(
        component="search.conversational_answer",
        operation="evidence_ledger_synthesis_start",
        message="Starting evidence-ledger synthesis model call",
        details={
            "run_type": RUN_TYPE_EVIDENCE_LEDGER_SYNTHESIS,
            "max_tokens": max_tokens,
            "ledger_entry_count": len(entry_dicts),
        },
        dataset_id=dataset_id,
    )

    result = run_nim_chat(
        conn, logger, router,
        run_type=RUN_TYPE_EVIDENCE_LEDGER_SYNTHESIS,
        messages=messages,
        dataset_id=dataset_id,
        max_tokens=max_tokens,
    )

    try:
        model_json = _extract_json_object(result.content)
    except PlannerParseError as exc:
        raise ConversationalAnswerParseError(
            f"Evidence-ledger synthesis response is not valid JSON: {exc}",
            details=exc.details,
        ) from exc
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        raise ConversationalAnswerParseError(
            f"Evidence-ledger synthesis response is not valid JSON: {exc}"
        ) from exc
    if not isinstance(model_json, dict):
        raise ConversationalAnswerParseError(
            "Evidence-ledger synthesis response must be a JSON object"
        )
    raw_validation = validate_ledger_analysis_output(model_json, entry_dicts)
    if not raw_validation.ok:
        logger.info(
            component="search.conversational_answer",
            operation="evidence_ledger_validation_failed",
            message="Raw model output validation failed",
            details={
                "phase": "raw",
                "issues": [i.code for i in raw_validation.issues],
            },
            dataset_id=dataset_id,
        )
        raise ConversationalAnswerParseError(
            f"Evidence-ledger raw model validation failed: "
            f"{', '.join(i.message for i in raw_validation.issues)}",
            details={"validation_issues": [{"code": i.code, "message": i.message} for i in raw_validation.issues]},
        )

    assembled = assemble_ledger_result(model_json, entry_dicts, config)
    assembly_validation = validate_assembled_ledger_output(assembled, entry_dicts)
    if not assembly_validation.ok:
        logger.info(
            component="search.conversational_answer",
            operation="evidence_ledger_validation_failed",
            message="Assembled payload validation failed",
            details={
                "phase": "assembled",
                "issues": [i.code for i in assembly_validation.issues],
            },
            dataset_id=dataset_id,
        )
        raise ConversationalAnswerParseError(
            f"Evidence-ledger assembly validation failed: "
            f"{', '.join(i.message for i in assembly_validation.issues)}",
            details={"validation_issues": [{"code": i.code, "message": i.message} for i in assembly_validation.issues]},
        )

    parsed = _parse_answer_payload(
        assembled,
        valid_message_ids=valid_ids,
        message_thread_by_id=message_thread_by_id,
        source_thread_ids=source_thread_ids,
        messages_considered=len(valid_ids),
        mode=ANSWER_MODE_EXHAUSTIVE_WINDOW_SCAN,
        retrieval_assists=retrieval_assists,
        message_order_by_thread=_message_order_by_thread_from_db(conn, dataset_id),
    )

    logger.info(
        component="search.conversational_answer",
        operation="evidence_ledger_merge_complete",
        message="Evidence-ledger merge complete",
        details={
            "answer_range_count": len(parsed.answer_ranges),
            "cited_message_count": len(parsed.cited_message_ids),
            "uncertainty_count": len(parsed.uncertainties),
        },
        dataset_id=dataset_id,
    )
    return parsed


def _run_bounded_exhaustive_window_merge(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    router: ModelRouter,
    *,
    user_query: str,
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
    message_order_by_thread = _message_order_by_thread_from_db(conn, dataset_id)

    def merge_batch(batch: list[dict[str, Any]], depth: int = 0) -> ConversationalAnswerResult:
        compact_batch = [_compact_window_result_for_merge(window) for window in batch]
        estimated_tokens = _estimate_merge_user_content_tokens(
            user_query,
            source_thread_ids=source_thread_ids,
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
            router,
            run_type=RUN_TYPE_EXHAUSTIVE_WINDOW_MERGE,
            user_content=build_exhaustive_window_merge_user_content(
                user_query,
                source_thread_ids=source_thread_ids,
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
            retrieval_assists=retrieval_assists if depth == 0 else [],
            message_order_by_thread=message_order_by_thread,
        )

    if not window_results:
        raise ConversationalAnswerParseError("No window findings available to merge")
    if len(window_results) == 1:
        only = window_results[0]
        return parse_exhaustive_window_merge_response(
            json.dumps(
                {
                    "answer": only.get("answer", ""),
                    "answer_summary": only.get("answer_summary", ""),
                    "answer_format": only.get("answer_format", "detailed"),
                    "cited_message_ids": only.get("cited_message_ids", []),
                    "answer_ranges": only.get("answer_ranges", []),
                    "uncertainties": only.get("uncertainties", []),
                }
            ),
            valid_message_ids=valid_ids,
            message_thread_by_id=message_thread_by_id,
            source_thread_ids=source_thread_ids,
            messages_considered=len(valid_ids),
            retrieval_assists=retrieval_assists,
            message_order_by_thread=message_order_by_thread,
        )
    return merge_batch(window_results)


def parse_exhaustive_window_scan_response(
    content: str,
    *,
    valid_message_ids: set[str],
    message_thread_by_id: dict[str, str],
    source_thread_ids: list[str],
    messages_considered: int,
    message_order_by_thread: dict[str, list[str]] | None = None,
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
        message_order_by_thread=message_order_by_thread,
    )


def _count_raw_answer_ranges(content: str) -> int | None:
    try:
        payload = _extract_json_object(content)
    except (PlannerParseError, json.JSONDecodeError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    ranges_raw = payload.get("answer_ranges")
    if not isinstance(ranges_raw, list):
        return 0
    return len(ranges_raw)


def parse_exhaustive_window_merge_response(
    content: str,
    *,
    valid_message_ids: set[str],
    message_thread_by_id: dict[str, str],
    source_thread_ids: list[str],
    messages_considered: int,
    retrieval_assists: list[dict[str, Any]] | None = None,
    message_order_by_thread: dict[str, list[str]] | None = None,
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
        retrieval_assists=retrieval_assists,
        message_order_by_thread=message_order_by_thread,
    )


def run_exhaustive_window_scan_answer(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    router: ModelRouter,
    *,
    user_query: str,
    dataset_id: int,
    deps: ToolRunnerDeps | None = None,
    answer_settings: AnswerSettings | None = None,
    nim_settings: NimSettings | None = None,
    model_id: str | None = None,
    provider_metadata: dict | None = None,
    max_tokens: int | None = None,
) -> ConversationalAnswerResult:
    logger.info(
        component="search.conversational_answer",
        operation="exhaustive_scan_pipeline_enter",
        message="Entered exhaustive window scan answer pipeline",
        details={
            "dataset_id": dataset_id,
            "model_id": model_id,
            "max_tokens_override": max_tokens,
        },
        dataset_id=dataset_id,
    )
    settings = answer_settings or load_settings().answer
    app_settings = load_settings()
    nim = nim_settings or app_settings.nim
    selected_model = model_id or router.writing_model_id() or "unknown-model"
    logger.info(
        component="search.conversational_answer",
        operation="exhaustive_scan_budgeting_start",
        message="Starting exhaustive window scan budgeting",
        details={
            "selected_model": selected_model,
            "window_overlap_messages": nim.window_overlap_messages,
        },
        dataset_id=dataset_id,
    )
    budget = resolve_answer_budget(
        compute_dataset_budget_stats(conn, dataset_id),
        settings,
        selected_model,
        nim_settings=nim,
        provider_metadata=provider_metadata,
    )
    logger.info(
        component="search.conversational_answer",
        operation="exhaustive_scan_budgeting_complete",
        message="Completed exhaustive window scan budgeting",
        details={
            "usable_input_tokens": budget.usable_input_tokens,
            "context_window_tokens": budget.context_window_tokens,
            "decision": budget.decision,
            "max_output_tokens": budget.max_output_tokens,
        },
        dataset_id=dataset_id,
    )
    logger.info(
        component="search.conversational_answer",
        operation="exhaustive_scan_window_build_start",
        message="Starting exhaustive window planning",
        details={
            "target_tokens": budget.usable_input_tokens,
            "window_overlap_messages": nim.window_overlap_messages,
            "selected_model": selected_model,
        },
        dataset_id=dataset_id,
    )
    planned_windows = build_token_bounded_windows_for_dataset(
        conn,
        dataset_id,
        target_tokens=budget.usable_input_tokens,
        overlap_messages=nim.window_overlap_messages,
        model_id=selected_model,
    )
    if not planned_windows:
        raise ConversationalAnswerParseError("No transcript windows available for exhaustive window scan")

    per_call_input_budget = budget.usable_input_tokens
    source_thread_ids = sorted({window.source_thread_id for window in planned_windows})
    logger.info(
        component="search.conversational_answer",
        operation="exhaustive_scan_preflight",
        message="Exhaustive window scan pre-flight",
        details={
            "context_window_tokens": budget.context_window_tokens,
            "per_call_input_budget": per_call_input_budget,
            "planned_window_count": len(planned_windows),
            "overlap_messages": nim.window_overlap_messages,
            "estimated_llm_calls": len(planned_windows) + 1,
            "model_id": selected_model,
        },
        dataset_id=dataset_id,
    )
    logger.info(
        component="search.conversational_answer",
        operation="window_plan_built",
        message="Built token-bounded transcript windows for exhaustive scan",
        details={
            "window_count": len(planned_windows),
            "target_tokens": per_call_input_budget,
            "overlap_messages": nim.window_overlap_messages,
            "windowing_mode": "token_bounded_thread",
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
        "window_target_tokens": per_call_input_budget,
        "context_window_tokens": budget.context_window_tokens,
        "context_source": budget.context_source,
        "safety_ratio": budget.safety_ratio,
    }

    hint_collection = collect_exhaustive_window_hints(
        conn,
        logger,
        router,
        dataset_id=dataset_id,
        user_query=user_query,
        planned_windows=planned_windows,
        deps=deps,
    )
    retrieval_assists: list[dict[str, Any]] = []
    window_results: list[dict[str, Any]] = []
    window_scan_counts: list[dict[str, Any]] = []
    valid_ids: set[str] = set()
    message_thread_by_id: dict[str, str] = {}
    scan_uncertainties: list[str] = []
    output_tokens = max_tokens if max_tokens is not None else budget.max_output_tokens
    merge_max_tokens = output_tokens

    for index, window in enumerate(planned_windows, start=1):
        window_valid_ids = set(window.message_ids)
        window_thread_by_id = {
            message_id: window.source_thread_id for message_id in window.message_ids
        }
        window_hint_blocks = hint_collection.window_blocks_by_id.get(window.window_id, ())
        scan = run_nim_chat(
            conn,
            logger,
            router,
            run_type=RUN_TYPE_EXHAUSTIVE_WINDOW_SCAN,
            user_content=build_exhaustive_window_scan_user_content(
                user_query,
                window=window,
                retrieval_hint_blocks=_serialize_hint_blocks_for_prompt(window_hint_blocks),
            ),
            dataset_id=dataset_id,
            max_tokens=output_tokens,
        )
        raw_answer_range_count = _count_raw_answer_ranges(scan.content)
        parsed_scan = parse_exhaustive_window_scan_response(
            scan.content,
            valid_message_ids=window_valid_ids,
            message_thread_by_id=window_thread_by_id,
            source_thread_ids=[window.source_thread_id],
            messages_considered=len(window.message_ids),
            message_order_by_thread={window.source_thread_id: list(window.message_ids)},
        )
        repaired_count = len(parsed_scan.repaired_answer_ranges)
        rejected_count = len(parsed_scan.removed_invalid_block_ids) + len(parsed_scan.removed_invalid_citation_ids)
        logger.info(
            component="search.conversational_answer",
            operation="exhaustive_window_scan_window_completed",
            message="Completed exhaustive window scan for planned window",
            details={
                "window_id": window.window_id,
                "window_index": index,
                "window_count": len(planned_windows),
                "source_thread_id": window.source_thread_id,
                "messages_considered": len(window.message_ids),
                "estimated_tokens": window.estimated_tokens,
                "raw_answer_range_count": raw_answer_range_count,
                "validated_answer_range_count": len(parsed_scan.answer_ranges),
                "repaired_answer_range_count": repaired_count,
                "rejected_answer_range_count": rejected_count,
                "removed_invalid_citation_count": len(parsed_scan.removed_invalid_citation_ids),
                "removed_invalid_block_count": len(parsed_scan.removed_invalid_block_ids),
                "retrieval_hint_block_count": len(window_hint_blocks),
                "retrieval_hint_source_counts": _hint_source_counts(window_hint_blocks),
            },
            dataset_id=dataset_id,
        )
        if parsed_scan.repaired_answer_ranges:
            logger.warning(
                component="search.conversational_answer",
                operation="exhaustive_window_scan_window_repaired_ranges",
                message="Repaired misordered ranges in exhaustive window scan result",
                details={
                    "window_id": window.window_id,
                    "repair_count": len(parsed_scan.repaired_answer_ranges),
                    "repair_records": [
                        asdict(r) for r in parsed_scan.repaired_answer_ranges
                    ],
                },
                dataset_id=dataset_id,
            )
        if parsed_scan.removed_invalid_citation_ids or parsed_scan.removed_invalid_block_ids:
            logger.warning(
                component="search.conversational_answer",
                operation="exhaustive_window_scan_window_validation_removed_ids",
                message="Removed invalid message IDs from exhaustive window scan result",
                details={
                    "window_id": window.window_id,
                    "removed_citations": parsed_scan.removed_invalid_citation_ids,
                    "removed_block_ids": parsed_scan.removed_invalid_block_ids,
                },
                dataset_id=dataset_id,
            )
        valid_ids.update(window.message_ids)
        message_thread_by_id.update(window_thread_by_id)
        scan_uncertainties.extend(parsed_scan.uncertainties)
        window_scan_counts.append(
            {
                "window_id": window.window_id,
                "window_index": index,
                "source_thread_id": window.source_thread_id,
                "raw_answer_range_count": raw_answer_range_count,
                "validated_answer_range_count": len(parsed_scan.answer_ranges),
                "repaired_answer_range_count": repaired_count,
                "rejected_answer_range_count": rejected_count,
                "retrieval_hint_block_count": len(window_hint_blocks),
                "retrieval_hint_source_counts": _hint_source_counts(window_hint_blocks),
            }
        )
        window_results.append(
            {
                "window_id": window.window_id,
                "source_thread_id": window.source_thread_id,
                "estimated_tokens": window.estimated_tokens,
                "message_ids": window.message_ids,
                "raw_answer_range_count": raw_answer_range_count,
                "answer": parsed_scan.answer,
                "answer_summary": parsed_scan.answer_summary,
                "answer_format": parsed_scan.answer_format,
                "cited_message_ids": parsed_scan.cited_message_ids,
                "answer_ranges": [asdict(answer_range) for answer_range in parsed_scan.answer_ranges],
                "uncertainties": parsed_scan.uncertainties,
            }
        )

    logger.info(
        component="search.conversational_answer",
        operation="exhaustive_window_scan_windows_completed",
        message="Completed exhaustive window scans for all planned windows",
        details={
            "window_count": len(planned_windows),
            "raw_answer_range_count_total": sum(
                count["raw_answer_range_count"] or 0 for count in window_scan_counts
            ),
            "validated_answer_range_count_total": sum(
                count["validated_answer_range_count"] for count in window_scan_counts
            ),
            "repaired_answer_range_count_total": sum(
                count["repaired_answer_range_count"] for count in window_scan_counts
            ),
            "rejected_answer_range_count_total": sum(
                count["rejected_answer_range_count"] for count in window_scan_counts
            ),
            "retrieval_hint_block_count_total": sum(
                count["retrieval_hint_block_count"] for count in window_scan_counts
            ),
            "window_range_counts": window_scan_counts,
        },
        dataset_id=dataset_id,
    )

    if settings.use_evidence_ledger_merge:
        parsed = _run_evidence_ledger_window_merge(
            conn,
            logger,
            router,
            user_query=user_query,
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
    else:
        parsed = _run_bounded_exhaustive_window_merge(
            conn,
            logger,
            router,
            user_query=user_query,
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
    message_order_by_thread = _message_order_by_planned_windows(planned_windows)
    hinted_final_ranges = sum(
        1
        for answer_range in parsed.answer_ranges
        if _range_intersects_hint_blocks(
            answer_range,
            hint_collection.all_blocks,
            message_order_by_thread=message_order_by_thread,
            message_thread_by_id=message_thread_by_id,
        )
    )
    logger.info(
        component="search.conversational_answer",
        operation="exhaustive_scan_hint_overlap_summary",
        message="Computed exhaustive scan retrieval-hint overlap with final answer ranges",
        details={
            "planner_term_count": len(hint_collection.planner_terms),
            "hint_block_count": len(hint_collection.all_blocks),
            "final_answer_range_count": len(parsed.answer_ranges),
            "hinted_final_answer_range_count": hinted_final_ranges,
        },
        dataset_id=dataset_id,
    )
    return parsed
