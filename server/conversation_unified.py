"""Server-owned planned analysis, extraction, ledger, and synthesis."""

from __future__ import annotations

import asyncio
import bisect
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from server.config import OperationConfig
from server.contracts import (
    ConversationalAnalysisRequest,
    LedgerCompactionOutput,
    LedgerSynthesisOutput,
    AnalysisContext,
    EmbeddingMetadata,
    SCHEMA_REGISTRY,
    WindowEvidenceEnvelope,
    SearchPolicy,
    parse_ndjson_event,
)
from server.evidence_ledger import (
    EvidenceRangeRecord,
    LedgerBudgetExceeded,
    LedgerError,
    NoUsableWindowOutput,
    WindowLedgerInput,
    build_ledger,
    partition_records,
    salvage_window_evidence,
    validate_window_evidence,
)
from server.result_validation import assemble_synthesis_result, inspect_synthesis_content
from server.model_runtime import RawModelOutput, UsageCollector, WorkloadTooLarge, run_model_operation
from server.observability import map_error
from server.provider import ProviderError
from server.token_accounting import (
    build_provider_payload,
    canonical_json,
    count_provider_payload,
    count_text_tokens,
    count_texts_tokens,
)


@dataclass(frozen=True, slots=True)
class WindowCompletedOutcome:
    index: int
    validated: Any
    usage: Any


@dataclass(frozen=True, slots=True)
class WindowUnavailableOutcome:
    index: int
    code: str
    attempts: int


class ModelInvocation:
    def __init__(
        self,
        task: asyncio.Task[Any],
        queue: asyncio.Queue[tuple[str, dict[str, Any]]],
        *,
        operation: str,
        heartbeat_seconds: float,
    ):
        self.task = task
        self.queue = queue
        self.operation = operation
        self.heartbeat_seconds = heartbeat_seconds
        self.started_at = asyncio.get_running_loop().time()

    async def progress(self):
        try:
            while not self.task.done() or not self.queue.empty():
                if not self.queue.empty():
                    yield self.queue.get_nowait()
                    continue
                progress_task = asyncio.create_task(self.queue.get())
                done, _ = await asyncio.wait(
                    {self.task, progress_task},
                    timeout=self.heartbeat_seconds,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if progress_task in done:
                    yield progress_task.result()
                else:
                    progress_task.cancel()
                    await asyncio.gather(progress_task, return_exceptions=True)
                    if not done:
                        yield (
                            "heartbeat",
                            {
                                "operation": self.operation,
                                "elapsed_ms": int(
                                    (asyncio.get_running_loop().time() - self.started_at)
                                    * 1000
                                ),
                                "completed_windows": 0,
                                "active_windows": 0,
                                "window_count": 0,
                            },
                        )
        finally:
            if not self.task.done():
                self.task.cancel()
                await asyncio.gather(self.task, return_exceptions=True)

    def result(self):
        return self.task.result()


class UnsplittableMessage(ValueError):
    code = "UNSPLITTABLE_MESSAGE"


class AnalysisPlanStale(ValueError):
    code = "ANALYSIS_PLAN_STALE"


class RetrievalGeometryMismatch(ValueError):
    code = "RETRIEVAL_GEOMETRY_MISMATCH"


class Sequencer:
    def __init__(self, request_id: str, config_version: int, endpoint: str):
        self.request_id = request_id
        self.config_version = config_version
        self.endpoint = endpoint
        self.sequence = 0

    def event(
        self,
        name: str,
        *,
        data: dict[str, Any] | None = None,
        result: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> str:
        self.sequence += 1
        envelope: dict[str, Any] = {
            "request_id": self.request_id,
            "sequence": self.sequence,
            "event": name,
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "config_version": self.config_version,
        }
        if name == "failed":
            envelope["error"] = error
        elif name == "completed":
            envelope["result"] = result
        else:
            envelope["data"] = data or {}
        parse_ndjson_event(envelope, endpoint=self.endpoint)
        return json.dumps(envelope, ensure_ascii=False, separators=(",", ":")) + "\n"


def _message_dict(message: Any) -> dict[str, str]:
    return {
        "message_id": message.message_id,
        "thread_id": message.thread_id,
        "timestamp": message.timestamp,
        "sender": message.sender,
        "text": message.text,
    }


def _user(task: str, **fields: Any) -> dict[str, Any]:
    return {"task": task, **fields}


def _input_target(operation: OperationConfig, configured_target: int | None = None) -> int:
    hard = operation.context_window_tokens - operation.max_output_tokens - operation.safety_margin_tokens
    candidates = [hard]
    if operation.target_input_tokens is not None:
        candidates.append(operation.target_input_tokens)
    if configured_target is not None:
        candidates.append(configured_target)
    return min(candidates)


def _window_input_target(operation: OperationConfig, utilization_percent: float) -> tuple[int, int]:
    if not 1.0 <= utilization_percent <= 100.0:
        raise ValueError("window input utilization must be between 1 and 100 percent")
    hard = _input_target(operation)
    target = math.floor(hard * utilization_percent / 100.0)
    if target <= 0:
        raise UnsplittableMessage("window input budget is not positive")
    return hard, target


def _payload_fits(
    operation_name: str,
    operation: OperationConfig,
    user_object: dict[str, Any],
    schema: dict[str, Any],
    *,
    target: int | None = None,
) -> bool:
    wire = [
        {"role": "system", "content": operation.system_prompt},
        {"role": "user", "content": canonical_json(user_object)},
    ]
    payload = build_provider_payload(
        operation,
        operation=operation_name,
        messages=wire,
        user_object=user_object,
        response_schema=schema,
    )
    accounting = count_provider_payload(payload, operation)
    return accounting.fits and accounting.input_tokens <= _input_target(operation, target)


def count_working_corpus_tokens(
    messages: Sequence[Mapping[str, Any]], operation: OperationConfig
) -> int:
    transcript = "\n".join(
        f"[{message['message_id']}] {message['timestamp']} | "
        f"{message['sender']}: {str(message['text']).strip() or '(empty message)'}"
        for message in messages
    )
    return count_text_tokens(transcript, operation)


def plan_windows(
    messages: Sequence[Mapping[str, Any]],
    *,
    question: str,
    analysis_plan: Mapping[str, Any],
    retrieval_queries: list[Mapping[str, Any]],
    retrieval_reservation_ranges: list[Mapping[str, Any]] | None = None,
    operation: OperationConfig,
    utilization_percent: float,
) -> list[WindowLedgerInput]:
    """Pack every message exactly once into balanced chronological windows."""
    reservation_ranges = list(retrieval_reservation_ranges or [])
    _, target = _window_input_target(operation, utilization_percent)
    windows: list[WindowLedgerInput] = []

    def payload_tokens(candidate: Sequence[Mapping[str, Any]], window_id: str) -> int:
        user_object = _user(
            "window_evidence_extraction",
            question=question,
            analysis_plan=dict(analysis_plan),
            retrieval_queries=list(retrieval_queries),
            suggestion_ranges=reservation_ranges,
            window_id=window_id,
            messages=list(candidate),
        )
        wire = [
            {"role": "system", "content": operation.system_prompt},
            {"role": "user", "content": canonical_json(user_object)},
        ]
        payload = build_provider_payload(
            operation,
            operation="window_evidence_extraction",
            messages=wire,
            user_object=user_object,
            response_schema=SCHEMA_REGISTRY["window_evidence_extraction"]["model_output"],
        )
        accounting = count_provider_payload(payload, operation)
        return accounting.input_tokens if accounting.fits else operation.context_window_tokens + 1

    def balanced_ranges(weights: list[int], count: int) -> list[tuple[int, int]]:
        if not 1 <= count <= len(weights):
            raise ValueError("balanced window count is outside message range")
        cumulative = [0]
        for weight in weights:
            cumulative.append(cumulative[-1] + weight)
        boundaries = [0]
        for part in range(1, count):
            ideal = cumulative[-1] * part / count
            minimum = boundaries[-1] + 1
            maximum = len(weights) - (count - part)
            insertion = bisect.bisect_left(cumulative, ideal, lo=minimum, hi=maximum + 1)
            candidates = {
                max(minimum, min(maximum, insertion)),
                max(minimum, min(maximum, insertion - 1)),
            }
            boundary = min(candidates, key=lambda item: (abs(cumulative[item] - ideal), item))
            boundaries.append(boundary)
        boundaries.append(len(weights))
        return list(zip(boundaries, boundaries[1:]))

    def exact_ranges_fit(
        thread_messages: Sequence[Mapping[str, Any]],
        ranges: list[tuple[int, int]],
        *,
        first_window_number: int,
    ) -> tuple[bool, int | None]:
        for offset, (start, end) in enumerate(ranges):
            if payload_tokens(thread_messages[start:end], f"w{first_window_number + offset:06d}") > target:
                return False, start if end - start == 1 else None
        return True, None

    runs: list[list[Mapping[str, Any]]] = []
    for message in messages:
        if not runs or str(runs[-1][0]["thread_id"]) != str(message["thread_id"]):
            runs.append([])
        runs[-1].append(message)
    expected_ids = [str(message["message_id"]) for message in messages]
    if len(expected_ids) != len(set(expected_ids)):
        raise RuntimeError("window planner requires unique message IDs")

    for thread_messages in runs:
        first_window_number = len(windows) + 1
        weights = [
            max(1, count)
            for count in count_texts_tokens(
                [canonical_json(message) + "," for message in thread_messages], operation
            )
        ]
        overhead = payload_tokens([], f"w{first_window_number:06d}")
        content_capacity = target - overhead
        if content_capacity <= 0:
            raise UnsplittableMessage("window prompt and response schema consume the entire input budget")
        window_count = max(1, math.ceil(sum(weights) / content_capacity))
        window_count = min(window_count, len(thread_messages))
        while True:
            ranges = balanced_ranges(weights, window_count)
            fits, failed_index = exact_ranges_fit(
                thread_messages, ranges, first_window_number=first_window_number
            )
            if fits:
                if window_count > 1:
                    fewer_ranges = balanced_ranges(weights, window_count - 1)
                    fewer_fit, _ = exact_ranges_fit(
                        thread_messages, fewer_ranges, first_window_number=first_window_number
                    )
                    if fewer_fit:
                        window_count -= 1
                        continue
                break
            if failed_index is not None:
                raise UnsplittableMessage(
                    f"message {thread_messages[failed_index]['message_id']} cannot fit a configured window"
                )
            if window_count == len(thread_messages):
                raise UnsplittableMessage("one or more messages cannot fit a configured window")
            window_count += 1
        for start, end in ranges:
            window_id = f"w{len(windows) + 1:06d}"
            windows.append(WindowLedgerInput(window_id, tuple(thread_messages[start:end])))

    flattened_ids = [str(item["message_id"]) for window in windows for item in window.messages]
    if (
        len(flattened_ids) != len(expected_ids)
        or len(flattened_ids) != len(set(flattened_ids))
        or set(flattened_ids) != set(expected_ids)
    ):
        raise RuntimeError("window planner changed message identity or coverage")
    for window in windows:
        if len({str(item["thread_id"]) for item in window.messages}) != 1:
            raise RuntimeError("window planner crossed a thread boundary")
    return windows


def _analysis_search_policy(snapshot, mode: str) -> dict[str, Any]:
    return {
        "mode": mode,
        "top_k_per_query": snapshot.global_config.retrieval_top_k_per_query,
        "fusion_method": "reciprocal_rank_fusion",
        "rrf_constant": snapshot.global_config.retrieval_rrf_constant,
        "maximum_prompt_suggestion_messages": snapshot.global_config.retrieval_maximum_prompt_suggestion_messages,
    }


def _embedding_dict(embedding: EmbeddingMetadata | None) -> dict[str, Any] | None:
    return None if embedding is None else embedding.model_dump()


def _analysis_fingerprint(snapshot, *, question: str, context: AnalysisContext) -> str:
    payload = {
        "question": question.strip(),
        "analysis_plan": context.analysis_plan.model_dump(),
        "queries": [query.model_dump() for query in context.retrieval_queries],
        "analysis_planning_operation": snapshot.operations["analysis_planning"].to_dict(include_secret=False),
        "embedding": _embedding_dict(context.embedding),
        "search_policy": context.search_policy.model_dump(),
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


async def _validate_analysis_context(app, snapshot, request, messages) -> tuple[str, AnalysisContext]:
    context = request.analysis_context
    mode = context.search_policy.mode
    if context.compatibility_fingerprint != _analysis_fingerprint(
        snapshot, question=request.question, context=context
    ):
        raise AnalysisPlanStale("analysis plan compatibility fingerprint is stale")
    expected_policy = SearchPolicy(**_analysis_search_policy(snapshot, mode))
    if context.search_policy != expected_policy:
        raise AnalysisPlanStale("analysis plan search policy is stale")
    if mode == "semantic_ranges":
        profile = await app.state.embedding.prepare()
        if context.embedding is None or (
            context.embedding.embedding_profile_id != profile.profile_id
            or context.embedding.artifact_fingerprint != profile.artifact_fingerprint
            or context.embedding.dimensions != profile.dimensions
            or context.embedding.normalization != profile.normalization
        ):
            raise RetrievalGeometryMismatch("retrieval embedding geometry does not match the active server")
    message_ids = [str(message["message_id"]) for message in messages]
    if len(message_ids) != len(set(message_ids)):
        raise AnalysisPlanStale("working-corpus message IDs are not unique")
    message_id_set = set(message_ids)
    query_counts: dict[str, int] = {}
    query_ids = {query.query_id for query in context.retrieval_queries}
    for hit in context.hits:
        if hit.query_id not in query_ids:
            raise AnalysisPlanStale("retrieval candidate references an unknown query")
        if hit.message_id not in message_id_set:
            raise AnalysisPlanStale("retrieval candidate is outside the supplied corpus")
        query_counts[hit.query_id] = query_counts.get(hit.query_id, 0) + 1
    top_k = snapshot.global_config.retrieval_top_k_per_query
    if any(count > top_k for count in query_counts.values()) or len(context.hits) > len(context.retrieval_queries) * top_k:
        raise AnalysisPlanStale("retrieval candidate count exceeds top-k policy")
    return mode, context


def _fuse_candidates(messages, context: AnalysisContext, snapshot) -> tuple[list[str], dict[str, dict[str, Any]], dict[str, int]]:
    ordinal = {str(message["message_id"]): index for index, message in enumerate(messages)}
    by_message: dict[str, dict[str, Any]] = {}
    for hit in context.hits:
        item = by_message.setdefault(
            hit.message_id,
            {"rrf_score": 0.0, "best_distance": float("inf"), "query_ids": set()},
        )
        item["rrf_score"] += 1.0 / (snapshot.global_config.retrieval_rrf_constant + hit.rank)
        item["best_distance"] = min(item["best_distance"], hit.distance)
        item["query_ids"].add(hit.query_id)
    ordered = sorted(
        by_message,
        key=lambda message_id: (
            -by_message[message_id]["rrf_score"],
            by_message[message_id]["best_distance"],
            ordinal[message_id],
            message_id,
        ),
    )
    selected = ordered[: snapshot.global_config.retrieval_maximum_prompt_suggestion_messages]
    return selected, by_message, {
        "raw_hit_count": len(context.hits),
        "unique_candidate_message_count": len(ordered),
    }


def _suggestion_ranges(windows, selected_message_ids, candidate_by_message, queries):
    selected = set(selected_message_ids)
    query_order = {str(query["query_id"]): index for index, query in enumerate(queries)}
    result: dict[str, list[dict[str, Any]]] = {}
    for window in windows:
        ranges: list[dict[str, Any]] = []
        current: list[Mapping[str, Any]] = []

        def finish() -> None:
            if not current:
                return
            ids = [str(message["message_id"]) for message in current]
            matched = sorted(
                {
                    query_id
                    for message_id in ids
                    for query_id in candidate_by_message[message_id]["query_ids"]
                },
                key=lambda query_id: query_order[query_id],
            )
            ranges.append(
                {
                    "thread_id": str(current[0]["thread_id"]),
                    "start_message_id": ids[0],
                    "end_message_id": ids[-1],
                    "hit_message_ids": ids,
                    "matched_query_ids": matched,
                }
            )
            current.clear()

        previous_index = -2
        previous_thread = None
        for index, message in enumerate(window.messages):
            message_id = str(message["message_id"])
            thread_id = str(message["thread_id"])
            if message_id not in selected:
                finish()
                previous_index = -2
                previous_thread = None
                continue
            if current and (index != previous_index + 1 or thread_id != previous_thread):
                finish()
            current.append(message)
            previous_index = index
            previous_thread = thread_id
        finish()
        result[window.window_id] = ranges
    return result


def _reservation_shape(
    queries: Sequence[Mapping[str, Any]],
    messages: Sequence[Mapping[str, Any]],
    maximum_messages: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Reserve the largest suggestion shape possible for this request.

    The reservation uses the request's actual query and message identifiers rather
    than synthetic maximum-length identifiers.  This keeps the reservation
    conservative over the real corpus while avoiding an impossible prompt budget
    for every ordinary request merely because the wire contract permits long IDs.
    """
    query_values = [dict(query) for query in queries]
    if not messages or not query_values or maximum_messages <= 0:
        return query_values, []
    ranges = []
    for message in list(messages)[:maximum_messages]:
        message_id = str(message["message_id"])
        ranges.append(
            {
                "thread_id": str(message["thread_id"]),
                "start_message_id": message_id,
                "end_message_id": message_id,
                "hit_message_ids": [message_id],
                "matched_query_ids": [str(query["query_id"]) for query in query_values],
            }
        )
    return queries, ranges


def _window_plan_hash(windows: Sequence[WindowLedgerInput]) -> str:
    payload = [
        {
            "window_id": window.window_id,
            "message_ids": [str(message["message_id"]) for message in window.messages],
        }
        for window in windows
    ]
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _overlap_diagnostics(records, selected_message_ids, cited_range_ids: set[str] | None = None) -> dict[str, int]:
    selected = set(selected_message_ids)
    final_overlap = final_outside = answer_overlap = answer_outside = 0
    evidenced: set[str] = set()
    for record in records:
        overlap = bool({str(message["message_id"]) for message in record.messages} & selected)
        if overlap:
            final_overlap += 1
            evidenced.update(
                {str(message["message_id"]) for message in record.messages} & selected
            )
        else:
            final_outside += 1
        if cited_range_ids is None or record.range_id in cited_range_ids:
            if overlap:
                answer_overlap += 1
            else:
                answer_outside += 1
    return {
        "final_ranges_overlapping_suggestions": final_overlap,
        "final_ranges_outside_suggestions": final_outside,
        "answer_relevant_ranges_overlapping_suggestions": answer_overlap,
        "answer_relevant_ranges_outside_suggestions": answer_outside,
        "suggestions_without_final_evidence": len(selected - evidenced),
    }


def _record_payload(record: EvidenceRangeRecord) -> dict[str, Any]:
    return {
        "range_id": record.range_id,
        "window_id": record.window_id,
        "source_range_index": record.source_range_index,
        "thread_id": record.thread_id,
        "start_message_id": record.start_message_id,
        "end_message_id": record.end_message_id,
        "summary": record.summary,
        "relevance": record.relevance,
        "normalizations": list(record.normalizations),
        "messages": [dict(message) for message in record.messages],
        "uncertainties": list(record.uncertainties),
    }


def _original_range_ids(items: Sequence[Mapping[str, Any]]) -> list[str]:
    result: list[str] = []
    for item in items:
        if "range_id" in item:
            ids = [str(item["range_id"])]
        else:
            raw_ids = item.get("covered_range_ids")
            if not isinstance(raw_ids, list):
                raise LedgerError("compaction input has no original range coverage")
            ids = [str(value) for value in raw_ids]
        if any(not value or value in result for value in ids):
            raise LedgerError("compaction input has duplicate or blank range coverage")
        result.extend(ids)
    return result


async def run_conversational_stream(app, raw_body: dict[str, Any]) -> StreamingResponse:
    snapshot = app.state.config_service.snapshot()
    request = ConversationalAnalysisRequest.model_validate(raw_body)
    raw_size = len(json.dumps(raw_body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    if raw_size > snapshot.global_config.maximum_product_request_bytes:
        raise WorkloadTooLarge("conversational request body exceeds configured ceiling")
    endpoint = "/v1/conversational-analysis"
    messages = [_message_dict(message) for message in request.working_corpus.messages]
    window_operation = snapshot.operations["window_evidence_extraction"]
    corpus_tokens = count_working_corpus_tokens(messages, window_operation)
    if corpus_tokens > snapshot.global_config.maximum_conversational_corpus_tokens:
        raise WorkloadTooLarge("working corpus exceeds configured conversational ceiling")
    retrieval_mode, context = await _validate_analysis_context(
        app, snapshot, request, messages
    )
    selected_ids, candidates, candidate_counts = _fuse_candidates(messages, context, snapshot)
    query_objects = [query.model_dump() for query in context.retrieval_queries]
    analysis_plan = context.analysis_plan.model_dump()
    app.state.debug_capture.record_for_request(
        request.request_id,
        "retrieval_candidates_received",
        {
            "mode": retrieval_mode,
            "queries": query_objects,
            "candidates": [hit.model_dump() for hit in context.hits],
        },
    )
    app.state.debug_capture.record_for_request(
        request.request_id,
        "retrieval_candidate_fusion",
        {
            "selected_message_ids": selected_ids,
            "unselected_message_ids": [
                message_id for message_id in candidates if message_id not in set(selected_ids)
            ],
        },
    )
    reservation_queries, reservation_ranges = _reservation_shape(
        query_objects,
        messages,
        snapshot.global_config.retrieval_maximum_prompt_suggestion_messages,
    ) if context.hits else (query_objects, [])
    windows = plan_windows(
        messages,
        question=request.question,
        analysis_plan=analysis_plan,
        retrieval_queries=reservation_queries,
        retrieval_reservation_ranges=reservation_ranges,
        operation=window_operation,
        utilization_percent=snapshot.global_config.window_input_utilization_percent,
    )
    suggestions_by_window = _suggestion_ranges(
        windows, selected_ids, candidates, query_objects
    )
    app.state.debug_capture.record_for_request(
        request.request_id,
        "retrieval_suggestion_ranges",
        {"ranges_by_window": suggestions_by_window},
    )
    for window in windows:
        actual_user = _user(
                    "window_evidence_extraction",
                        question=request.question,
                        analysis_plan=analysis_plan,
            retrieval_queries=query_objects,
            suggestion_ranges=suggestions_by_window[window.window_id],
            window_id=window.window_id,
            messages=list(window.messages),
        )
        if not _payload_fits(
            "window_evidence_extraction",
            window_operation,
            actual_user,
            SCHEMA_REGISTRY["window_evidence_extraction"]["model_output"],
            target=_window_input_target(
                window_operation,
                snapshot.global_config.window_input_utilization_percent,
            )[1],
        ):
            raise WorkloadTooLarge("actual extraction payload exceeds its reserved window budget")
    strategy = "single_window_ledger" if len(windows) == 1 else "multi_window_ledger"
    hard_target, target = _window_input_target(
        window_operation, snapshot.global_config.window_input_utilization_percent
    )
    retrieval_reserve_tokens = 0
    if context.hits:
        base_user = _user(
            "window_evidence_extraction",
            question=request.question,
            analysis_plan=analysis_plan,
            retrieval_queries=reservation_queries,
            suggestion_ranges=[],
            window_id="w000001",
            messages=[],
        )
        reserved_user = dict(base_user)
        reserved_user["suggestion_ranges"] = reservation_ranges
        base_payload = build_provider_payload(
            window_operation,
            operation="window_evidence_extraction",
            messages=[
                {"role": "system", "content": window_operation.system_prompt},
                {"role": "user", "content": canonical_json(base_user)},
            ],
            user_object=base_user,
            response_schema=SCHEMA_REGISTRY["window_evidence_extraction"]["model_output"],
        )
        reserved_payload = build_provider_payload(
            window_operation,
            operation="window_evidence_extraction",
            messages=[
                {"role": "system", "content": window_operation.system_prompt},
                {"role": "user", "content": canonical_json(reserved_user)},
            ],
            user_object=reserved_user,
            response_schema=SCHEMA_REGISTRY["window_evidence_extraction"]["model_output"],
        )
        retrieval_reserve_tokens = max(
            0,
            count_provider_payload(reserved_payload, window_operation).input_tokens
            - count_provider_payload(base_payload, window_operation).input_tokens,
        )
    window_hash = _window_plan_hash(windows)
    sequencer = Sequencer(request.request_id, snapshot.config_version, endpoint)
    collector = UsageCollector()

    def model_call(operation: str, user_object: dict[str, Any], output_model, observability=None, **runtime_options):
        progress_queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()
        task = asyncio.create_task(
            run_model_operation(
                app,
                snapshot=snapshot,
                request_id=request.request_id,
                product_endpoint=endpoint,
                operation_name=operation,
                user_object=user_object,
                response_schema=SCHEMA_REGISTRY[operation]["model_output"],
                output_model=output_model,
                collector=collector,
                progress_queue=progress_queue,
                observability=observability,
                **runtime_options,
            )
        )
        return ModelInvocation(
            task,
            progress_queue,
            operation=operation,
            heartbeat_seconds=snapshot.global_config.stream_heartbeat_seconds,
        )

    async def stream():
        active_tasks: set[asyncio.Task[Any]] = set()
        stream_started_at = asyncio.get_running_loop().time()
        completed_window_count = 0
        compaction_in_progress = False

        def logged(name: str, **fields: Any) -> None:
            app.state.events.emit(
                name,
                request_id=request.request_id,
                config_version=snapshot.config_version,
                product_endpoint=endpoint,
                strategy=strategy,
                **fields,
            )

        async def forward(invocation: ModelInvocation):
            async for progress_name, progress_data in invocation.progress():
                if progress_name == "heartbeat":
                    logged("heartbeat", **progress_data)
                yield sequencer.event(progress_name, data=progress_data)

        try:
            logged("request_accepted")
            yield sequencer.event(
                "accepted",
                data={
                    "endpoint": endpoint,
                    "scope_id": request.working_corpus.scope_id,
                    "message_count": len(messages),
                },
            )
            yield sequencer.event(
                "accounting_completed",
                data={
                    "corpus_tokens": corpus_tokens,
                    "analysis_input_tokens": corpus_tokens + retrieval_reserve_tokens,
                    "context_window_tokens": window_operation.context_window_tokens,
                    "reserved_output_tokens": window_operation.max_output_tokens,
                    "safety_margin_tokens": window_operation.safety_margin_tokens,
                    "strategy": strategy,
                },
            )
            fingerprint = context.compatibility_fingerprint
            yield sequencer.event(
                "analysis_plan_accepted",
                data={
                    "analysis_plan_id": context.analysis_plan_id,
                    "compatibility_fingerprint": fingerprint,
                    "concept_count": len(context.analysis_plan.concepts),
                    "retrieval_query_count": len(query_objects),
                    "retrieval_mode": retrieval_mode,
                },
            )
            yield sequencer.event(
                "retrieval_suggestions_built",
                data={
                    "unique_candidate_message_count": candidate_counts["unique_candidate_message_count"],
                    "selected_suggestion_message_count": len(selected_ids),
                    "suggestion_range_count": sum(len(value) for value in suggestions_by_window.values()),
                    "unselected_candidate_message_count": max(
                        0,
                        candidate_counts["unique_candidate_message_count"] - len(selected_ids),
                    ),
                },
            )
            logged(
                "window_plan_created",
                internal_operation="window_evidence_extraction",
                window_count=len(windows),
                message_count=len(messages),
                hard_input_tokens=hard_target,
                target_input_tokens=target,
                utilization_percent=snapshot.global_config.window_input_utilization_percent,
            )
            yield sequencer.event(
                "window_plan_created",
                data={
                    "strategy": strategy,
                    "window_count": len(windows),
                    "message_count": len(messages),
                    "hard_input_tokens": hard_target,
                    "target_input_tokens": target,
                    "utilization_percent": snapshot.global_config.window_input_utilization_percent,
                    "retrieval_reserve_tokens": retrieval_reserve_tokens,
                    "window_plan_hash": window_hash,
                },
            )
            outputs: list[Any | None] = [None] * len(windows)
            unavailable: list[WindowUnavailableOutcome] = []

            async def run_window(index: int, window: WindowLedgerInput, progress_queue):
                def unusable(content: str) -> bool:
                    try:
                        value = json.loads(content.strip())
                    except (TypeError, ValueError, json.JSONDecodeError):
                        return True
                    return not isinstance(value, dict) or value.get("window_id") != window.window_id or not isinstance(value.get("evidence_ranges"), list)

                try:
                    output, usage = await run_model_operation(
                        app,
                        snapshot=snapshot,
                        request_id=request.request_id,
                        product_endpoint=endpoint,
                        operation_name="window_evidence_extraction",
                        user_object=_user(
                            "window_evidence_extraction",
                            question=request.question,
                            analysis_plan=analysis_plan,
                            retrieval_queries=query_objects,
                            suggestion_ranges=suggestions_by_window[window.window_id],
                            window_id=window.window_id,
                            messages=list(window.messages),
                        ),
                        response_schema=SCHEMA_REGISTRY["window_evidence_extraction"]["model_output"],
                        output_model=WindowEvidenceEnvelope,
                        collector=collector,
                        progress_queue=progress_queue,
                        observability={
                            "window_id": window.window_id,
                            "window_index": index,
                            "window_count": len(windows),
                        },
                        preserve_raw_output=True,
                        retry_unusable_output=True,
                        unusable_output=unusable,
                    )
                    assert isinstance(output, RawModelOutput)
                    raw = json.loads(output.content.strip())
                    validated = salvage_window_evidence(window, raw)
                    app.state.debug_capture.record_for_request(
                        request.request_id,
                        "window_evidence_validation",
                        {
                            "window_id": validated.window_id,
                            "accepted_ranges": [
                                {
                                    "source_range_index": item.source_range_index,
                                    "thread_id": item.thread_id,
                                    "start_message_id": item.start_message_id,
                                    "end_message_id": item.end_message_id,
                                    "summary": item.summary,
                                    "relevance": item.relevance,
                                    "normalizations": list(item.normalizations),
                                }
                                for item in validated.accepted_ranges
                            ],
                            "rejected_ranges": [item.model_dump() for item in validated.rejected_ranges],
                            "normalizations": [item.model_dump() for item in validated.normalizations],
                            "warning_count": len(validated.warnings),
                        },
                    )
                    return WindowCompletedOutcome(index, validated, usage)
                except ProviderError as exc:
                    return WindowUnavailableOutcome(index, exc.code, window_operation.max_attempts)
                except LedgerError as exc:
                    if (exc.details or {}).get("reason") == "WINDOW_OUTPUT_UNUSABLE":
                        return WindowUnavailableOutcome(index, "WINDOW_OUTPUT_UNUSABLE", window_operation.max_attempts)
                    raise

            maximum = snapshot.global_config.maximum_concurrent_windows
            for start in range(0, len(windows), maximum):
                batch = windows[start : start + maximum]
                batch_progress: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()
                for offset, window in enumerate(batch):
                    index = start + offset
                    suggestion_count = len(suggestions_by_window[window.window_id])
                    logged(
                        "window_started",
                        internal_operation="window_evidence_extraction",
                        window_id=window.window_id,
                        window_index=index,
                        window_count=len(windows),
                        message_count=len(window.messages),
                    )
                    yield sequencer.event(
                        "window_started",
                        data={
                            "window_id": window.window_id,
                            "window_index": index,
                            "window_count": len(windows),
                            "message_count": len(window.messages),
                            "suggestion_range_count": suggestion_count,
                        },
                    )
                    active_tasks.add(asyncio.create_task(run_window(index, window, batch_progress)))
                try:
                    while active_tasks:
                        progress_task = asyncio.create_task(batch_progress.get())
                        done, _ = await asyncio.wait(
                            active_tasks | {progress_task},
                            timeout=snapshot.global_config.stream_heartbeat_seconds,
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                        if not done:
                            progress_task.cancel()
                            await asyncio.gather(progress_task, return_exceptions=True)
                            heartbeat = {
                                "operation": "window_evidence_extraction",
                                "elapsed_ms": int((asyncio.get_running_loop().time() - stream_started_at) * 1000),
                                "completed_windows": completed_window_count,
                                "active_windows": len(active_tasks),
                                "window_count": len(windows),
                            }
                            logged("heartbeat", **heartbeat)
                            yield sequencer.event("heartbeat", data=heartbeat)
                            continue
                        if progress_task in done:
                            progress_name, progress_data = progress_task.result()
                            yield sequencer.event(progress_name, data=progress_data)
                        else:
                            progress_task.cancel()
                            await asyncio.gather(progress_task, return_exceptions=True)
                        for finished_task in [task for task in done if task in active_tasks]:
                            active_tasks.remove(finished_task)
                            outcome = finished_task.result()
                            if isinstance(outcome, WindowCompletedOutcome):
                                index = outcome.index
                                output = outcome.validated
                                usage = outcome.usage
                                outputs[index] = output
                            else:
                                index = outcome.index
                                unavailable.append(outcome)
                            completed_window_count += 1
                            if isinstance(outcome, WindowCompletedOutcome):
                                logged(
                                    "window_completed",
                                    internal_operation="window_evidence_extraction",
                                    window_id=windows[index].window_id,
                                    window_index=index,
                                    window_count=len(windows),
                                    accepted_range_count=output.accepted_range_count,
                                    rejected_range_count=output.rejected_range_count,
                                    normalized_range_count=output.normalized_range_count,
                                    validation_status=output.status,
                                    completed_windows=completed_window_count,
                                )
                                yield sequencer.event(
                                    "window_completed",
                                    data={
                                        "window_id": windows[index].window_id,
                                        "window_index": index,
                                        "window_count": len(windows),
                                        "accepted_range_count": output.accepted_range_count,
                                        "rejected_range_count": output.rejected_range_count,
                                        "normalized_range_count": output.normalized_range_count,
                                        "validation_status": output.status,
                                        "input_tokens": usage.input_tokens,
                                        "output_tokens": usage.output_tokens,
                                        "usage_source": usage.source,
                                        "estimated_cost": usage.cost,
                                    },
                                )
                            else:
                                logged(
                                    "window_unavailable",
                                    severity="WARNING",
                                    internal_operation="window_evidence_extraction",
                                    window_id=windows[index].window_id,
                                    window_index=index,
                                    window_count=len(windows),
                                    attempts=outcome.attempts,
                                    error_code=outcome.code,
                                    completed_windows=completed_window_count,
                                )
                                yield sequencer.event(
                                    "window_output_unusable",
                                    data={
                                        "window_id": windows[index].window_id,
                                        "window_index": index,
                                        "window_count": len(windows),
                                        "attempt": outcome.attempts,
                                        "code": outcome.code,
                                    },
                                )
                                yield sequencer.event(
                                    "window_unavailable",
                                    data={
                                        "window_id": windows[index].window_id,
                                        "window_index": index,
                                        "window_count": len(windows),
                                        "attempts": outcome.attempts,
                                        "code": outcome.code,
                                    },
                                )
                    while not batch_progress.empty():
                        progress_name, progress_data = batch_progress.get_nowait()
                        yield sequencer.event(progress_name, data=progress_data)
                except BaseException:
                    for task in active_tasks:
                        task.cancel()
                    await asyncio.gather(*active_tasks, return_exceptions=True)
                    active_tasks.clear()
                    raise

            completed_windows = [window for index, window in enumerate(windows) if outputs[index] is not None]
            completed_outputs = [output for output in outputs if output is not None]
            if not completed_windows:
                raise NoUsableWindowOutput("no window produced a usable extraction envelope")
            ledger = build_ledger(completed_windows, completed_outputs)
            evidence_validation = ledger.validation
            evidence_validation.update({
                "planned_window_count": len(windows),
                "usable_window_count": len(completed_windows),
                "unavailable_window_count": len(unavailable),
                "unavailable_windows": [
                    {
                        "window_id": windows[item.index].window_id,
                        "window_index": item.index,
                        "window_count": len(windows),
                        "attempts": item.attempts,
                        "code": item.code,
                    }
                    for item in sorted(unavailable, key=lambda value: value.index)
                ],
            })
            evidence_validation["status"] = "partial" if evidence_validation["rejected_range_count"] or evidence_validation["unavailable_window_count"] else "complete"
            app.state.debug_capture.record_for_request(
                request.request_id,
                "evidence_validation_completed",
                {
                    "status": evidence_validation["status"],
                    "accepted_range_count": evidence_validation["accepted_range_count"],
                    "rejected_range_count": evidence_validation["rejected_range_count"],
                    "normalized_range_count": evidence_validation["normalized_range_count"],
                    "unavailable_window_count": evidence_validation["unavailable_window_count"],
                },
            )
            yield sequencer.event(
                "evidence_validation_completed",
                data={
                    "planned_window_count": len(windows),
                    "usable_window_count": len(completed_windows),
                    "unavailable_window_count": len(unavailable),
                    "accepted_range_count": evidence_validation["accepted_range_count"],
                    "rejected_range_count": evidence_validation["rejected_range_count"],
                    "normalized_range_count": evidence_validation["normalized_range_count"],
                    "status": evidence_validation["status"],
                },
            )
            yield sequencer.event(
                "ledger_built",
                data={"window_count": len(windows), "evidence_range_count": len(ledger.records)},
            )
            metadata = [
                {
                    "range_id": record.range_id,
                    "window_id": record.window_id,
                    "source_range_index": record.source_range_index,
                    "thread_id": record.thread_id,
                    "start_message_id": record.start_message_id,
                    "end_message_id": record.end_message_id,
                    "summary": record.summary,
                    "relevance": record.relevance,
                    "normalizations": list(record.normalizations),
                }
                for record in ledger.records
            ]
            coverage = [
                {
                    "window_id": item.window_id,
                    "first_message_id": item.first_message_id,
                    "last_message_id": item.last_message_id,
                    "message_count": item.message_count,
                    "evidence_range_count": item.evidence_range_count,
                    "uncertainties": list(item.uncertainties),
                }
                for item in ledger.coverage
            ]
            coverage.extend(
                {
                    "window_id": windows[item.index].window_id,
                    "first_message_id": str(windows[item.index].messages[0]["message_id"]),
                    "last_message_id": str(windows[item.index].messages[-1]["message_id"]),
                    "message_count": len(windows[item.index].messages),
                    "evidence_range_count": 0,
                    "uncertainties": [],
                    "status": "unavailable",
                    "unavailable_code": item.code,
                }
                for item in sorted(unavailable, key=lambda value: value.index)
            )
            highest: list[dict[str, Any]] = [_record_payload(record) for record in ledger.records]
            synthesis_operation = snapshot.operations["ledger_synthesis"]

            def synthesis_user() -> dict[str, Any]:
                return _user(
                    "ledger_synthesis",
                    question=request.question,
                    analysis_plan=analysis_plan,
                    coverage_report=coverage,
                    evidence_validation_summary=evidence_validation,
                    ledger_metadata=metadata,
                    records_or_highest_level_summaries=highest,
                )

            synthesis_payload = build_provider_payload(
                synthesis_operation,
                operation="ledger_synthesis",
                messages=[
                    {"role": "system", "content": synthesis_operation.system_prompt},
                    {"role": "user", "content": canonical_json(synthesis_user())},
                ],
                user_object=synthesis_user(),
                response_schema=SCHEMA_REGISTRY["ledger_synthesis"]["model_output"],
            )
            preflight = count_provider_payload(synthesis_payload, synthesis_operation)
            usable = _input_target(synthesis_operation)
            yield sequencer.event(
                "ledger_synthesis_preflight",
                data={
                    "evidence_range_count": len(ledger.records),
                    "evidence_message_count": len({
                        str(message["message_id"])
                        for record in ledger.records
                        for message in record.messages
                    }),
                    "required_input_tokens": preflight.input_tokens,
                    "usable_input_tokens": usable,
                    "excess_input_tokens": max(0, preflight.input_tokens - usable),
                    "direct_fit": preflight.fits and preflight.input_tokens <= usable,
                },
            )
            compaction_applied = False
            compaction_levels = 0
            compaction_group_calls = 0
            compaction_in_progress = False
            if not (preflight.fits and preflight.input_tokens <= usable):
                compaction_in_progress = True
                logged(
                    "ledger_compaction_required",
                    severity="WARNING",
                    internal_operation="ledger_compaction",
                    input_tokens=preflight.input_tokens,
                    target_input_tokens=usable,
                    state="required",
                )
                yield sequencer.event(
                    "ledger_compaction_required",
                    data={
                        "evidence_range_count": len(ledger.records),
                        "evidence_message_count": len({
                            str(message["message_id"])
                            for record in ledger.records
                            for message in record.messages
                        }),
                        "required_input_tokens": preflight.input_tokens,
                        "usable_input_tokens": usable,
                        "excess_input_tokens": max(0, preflight.input_tokens - usable),
                        "direct_fit": False,
                        "maximum_depth": snapshot.global_config.ledger_compaction_max_depth,
                    },
                )
                for level in range(1, snapshot.global_config.ledger_compaction_max_depth + 1):
                    compaction_operation = snapshot.operations["ledger_compaction"]

                    def group_fits(candidate: Sequence[Mapping[str, Any]]) -> bool:
                        return _payload_fits(
                            "ledger_compaction",
                            compaction_operation,
                            _user(
                                "ledger_compaction",
                                question=request.question,
                                analysis_plan=analysis_plan,
                                level=level,
                                group_id=f"g{level:02d}-probe",
                                coverage_report=coverage,
                                records_or_summaries=list(candidate),
                            ),
                            SCHEMA_REGISTRY["ledger_compaction"]["model_output"],
                        )

                    groups = partition_records(
                        highest,
                        group_fits,
                        level=level,
                        max_depth=snapshot.global_config.ledger_compaction_max_depth,
                    )
                    reduced: list[dict[str, Any]] = []
                    for group_index, (group_id, group) in enumerate(groups):
                        expected_ids = _original_range_ids(group)
                        yield sequencer.event(
                            "ledger_compaction_group_started",
                            data={
                                "level": level,
                                "group_id": group_id,
                                "group_index": group_index,
                                "group_count": len(groups),
                                "covered_range_count": len(expected_ids),
                            },
                        )
                        def compaction_output_unusable(content: str) -> bool:
                            try:
                                value = json.loads(content.strip())
                            except (TypeError, ValueError, json.JSONDecodeError):
                                return True
                            return not isinstance(value, dict) or not {"group_id", "summary", "covered_range_ids", "uncertainties"} <= set(value)

                        invocation = model_call(
                            "ledger_compaction",
                            _user(
                                "ledger_compaction",
                                question=request.question,
                                analysis_plan=analysis_plan,
                                level=level,
                                group_id=group_id,
                                coverage_report=coverage,
                                records_or_summaries=list(group),
                            ),
                            LedgerCompactionOutput,
                            preserve_raw_output=True,
                            retry_unusable_output=True,
                            unusable_output=compaction_output_unusable,
                        )
                        async for progress_name, progress_data in invocation.progress():
                            if progress_name == "heartbeat":
                                logged("heartbeat", **progress_data)
                            yield sequencer.event(progress_name, data=progress_data)
                        raw_compacted, usage = invocation.result()
                        assert isinstance(raw_compacted, RawModelOutput)
                        try:
                            compacted = LedgerCompactionOutput.model_validate(json.loads(raw_compacted.content.strip()))
                        except (TypeError, ValueError, json.JSONDecodeError, ValidationError) as exc:
                            raise LedgerError(
                                "compaction group returned a nonconforming machine-readable envelope",
                                details={"reason": "COMPACTION_UNAVAILABLE", "group_id": group_id},
                            ) from exc
                        if compacted.group_id != group_id or compacted.covered_range_ids != expected_ids:
                            raise LedgerError("compaction group did not preserve original range coverage")
                        reduced.append({"level": level, **compacted.model_dump()})
                        compaction_group_calls += 1
                        yield sequencer.event(
                            "ledger_compaction_group_completed",
                            data={
                                "level": level,
                                "group_id": group_id,
                                "group_index": group_index,
                                "group_count": len(groups),
                                "covered_range_count": len(expected_ids),
                                "input_tokens": usage.input_tokens,
                                "output_tokens": usage.output_tokens,
                                "usage_source": usage.source,
                                "estimated_cost": usage.cost,
                            },
                        )
                    if _original_range_ids(reduced) != [record.range_id for record in ledger.records]:
                        raise LedgerError("compaction level changed global range coverage or order")
                    highest = reduced
                    compaction_applied = True
                    compaction_levels = level
                    yield sequencer.event(
                        "ledger_compaction_level_completed",
                        data={
                            "level": level,
                            "group_count": len(groups),
                            "covered_range_count": len(_original_range_ids(reduced)),
                        },
                    )
                    final_probe = count_provider_payload(
                        build_provider_payload(
                            synthesis_operation,
                            operation="ledger_synthesis",
                            messages=[
                                {"role": "system", "content": synthesis_operation.system_prompt},
                                {"role": "user", "content": canonical_json(synthesis_user())},
                            ],
                            user_object=synthesis_user(),
                            response_schema=SCHEMA_REGISTRY["ledger_synthesis"]["model_output"],
                        ),
                        synthesis_operation,
                    )
                    if final_probe.fits and final_probe.input_tokens <= usable:
                        break
                else:
                    raise LedgerBudgetExceeded("evidence ledger compaction did not fit synthesis budget")
                final_synthesis_input_tokens = final_probe.input_tokens
                yield sequencer.event(
                    "ledger_compaction_completed",
                    data={
                        "levels": compaction_levels,
                        "group_calls": compaction_group_calls,
                        "original_range_count": len(ledger.records),
                        "covered_range_count": len(_original_range_ids(highest)),
                        "final_synthesis_input_tokens": final_synthesis_input_tokens,
                    },
                )
                logged(
                    "ledger_compaction_completed",
                    internal_operation="ledger_compaction",
                    input_tokens=final_synthesis_input_tokens,
                    state="completed",
                )
            else:
                final_synthesis_input_tokens = preflight.input_tokens
            compaction_in_progress = False

            diagnostics = {
                "mode": retrieval_mode,
                "query_count": len(query_objects),
                "raw_hit_count": candidate_counts["raw_hit_count"],
                "unique_candidate_message_count": candidate_counts["unique_candidate_message_count"],
                "selected_suggestion_message_count": len(selected_ids),
                "suggestion_range_count": sum(len(value) for value in suggestions_by_window.values()),
                **_overlap_diagnostics(ledger.records, selected_ids, set()),
            }
            processing = {
                "direct_synthesis_input_tokens": preflight.input_tokens,
                "synthesis_usable_input_tokens": usable,
                "compaction_applied": compaction_applied,
                "compaction_levels": compaction_levels,
                "compaction_group_calls": compaction_group_calls,
            }
            yield sequencer.event(
                "ledger_synthesis_started",
                data={"evidence_range_count": len(ledger.records)},
            )
            invocation = model_call(
                "ledger_synthesis",
                synthesis_user(),
                LedgerSynthesisOutput,
                preserve_raw_output=True,
                retry_unusable_output=True,
                unusable_output=lambda content: inspect_synthesis_content(content).parse_status == "unavailable",
            )
            try:
                async for progress_name, progress_data in invocation.progress():
                    if progress_name == "heartbeat":
                        logged("heartbeat", **progress_data)
                    yield sequencer.event(progress_name, data=progress_data)
                final, usage = invocation.result()
            except ProviderError as exc:
                if exc.code != "MODEL_OUTPUT_UNUSABLE":
                    raise
                result, inspection = assemble_synthesis_result(
                    None,
                    records=ledger.records,
                    evidence_validation=evidence_validation,
                    strategy=strategy,
                    message_count=len(messages),
                    planned_window_count=len(windows),
                    usable_window_count=len(completed_windows),
                    unavailable_window_count=len(unavailable),
                    retrieval_diagnostics=diagnostics,
                    ledger_processing=processing,
                    usage=collector.summary(),
                )
                yield sequencer.event(
                    "warning",
                    data={"code": "SYNTHESIS_UNAVAILABLE", "details": {"reason": "configured_attempts_exhausted"}, "stage": "synthesis", "operation": "ledger_synthesis", "window_id": None},
                )
                yield sequencer.event(
                    "synthesis_validation_completed",
                    data={"status": "unavailable", "result_count": 0, "verified_citation_count": 0, "unverified_citation_count": 0, "omitted_range_count": len(result["unclassified_evidence"]), "warning_count": len(result["synthesis_validation"]["warnings"])},
                )
                yield sequencer.event("retrieval_overlap_completed", data={
                    key: diagnostics[key]
                    for key in (
                        "final_ranges_overlapping_suggestions",
                        "final_ranges_outside_suggestions",
                        "answer_relevant_ranges_overlapping_suggestions",
                        "answer_relevant_ranges_outside_suggestions",
                        "suggestions_without_final_evidence",
                    )
                })
                for warning in result["synthesis_validation"]["warnings"]:
                    logged("result_warning", severity="WARNING", warning_code=warning["code"])
                logged("request_completed", completion_status=result["completion_status"], answer_source=result["answer_source"])
                yield sequencer.event("completed", result=result)
                return
            assert isinstance(final, RawModelOutput)
            raw_synthesis = final.content
            inspected_synthesis = inspect_synthesis_content(raw_synthesis)
            yield sequencer.event(
                "ledger_synthesis_received",
                data={
                    "evidence_range_count": len(ledger.records),
                    "content_nonblank": inspected_synthesis.parse_status != "unavailable",
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "usage_source": usage.source,
                    "estimated_cost": usage.cost,
                },
            )
            cited_range_ids = {
                range_id
                for item in inspected_synthesis.results
                for range_id in item.get("range_ids", [])
                if range_id in {record.range_id for record in ledger.records}
            }
            diagnostics = {
                **diagnostics,
                **_overlap_diagnostics(ledger.records, selected_ids, cited_range_ids),
            }
            result, inspection = assemble_synthesis_result(
                raw_synthesis,
                records=ledger.records,
                evidence_validation=evidence_validation,
                strategy=strategy,
                message_count=len(messages),
                planned_window_count=len(windows),
                usable_window_count=len(completed_windows),
                unavailable_window_count=len(unavailable),
                retrieval_diagnostics=diagnostics,
                ledger_processing=processing,
                usage=collector.summary(),
            )
            yield sequencer.event(
                "synthesis_validation_completed",
                data={
                    "status": result["synthesis_validation"]["status"],
                    "result_count": len(result["results"]),
                    "verified_citation_count": sum(len(item["verified_range_ids"]) for item in result["results"]),
                    "unverified_citation_count": sum(len(item["unverified_range_ids"]) for item in result["results"]),
                    "omitted_range_count": len(result["unclassified_evidence"]),
                    "warning_count": len(result["synthesis_validation"]["warnings"]),
                },
            )
            yield sequencer.event("retrieval_overlap_completed", data={
                key: diagnostics[key]
                for key in (
                    "final_ranges_overlapping_suggestions",
                    "final_ranges_outside_suggestions",
                    "answer_relevant_ranges_overlapping_suggestions",
                    "answer_relevant_ranges_outside_suggestions",
                    "suggestions_without_final_evidence",
                )
            })
            for warning in result["synthesis_validation"]["warnings"]:
                logged("result_warning", severity="WARNING", warning_code=warning["code"])
            logged("request_completed", completion_status=result["completion_status"], answer_source=result["answer_source"])
            yield sequencer.event("completed", result=result)
        except asyncio.CancelledError:
            for task in active_tasks:
                task.cancel()
            await asyncio.gather(*active_tasks, return_exceptions=True)
            logged("client_cancelled", severity="WARNING")
            raise
        except Exception as exc:
            if compaction_in_progress and isinstance(exc, (ProviderError, LedgerError)):
                fallback_warning = {
                    "code": "COMPACTION_UNAVAILABLE",
                    "details": {"reason": str(exc)[:512], "error_code": getattr(exc, "code", "COMPACTION_UNAVAILABLE")},
                }
                evidence_validation.setdefault("warnings", []).append(fallback_warning)
                fallback_diagnostics = {
                    "mode": retrieval_mode,
                    "query_count": len(query_objects),
                    "raw_hit_count": candidate_counts["raw_hit_count"],
                    "unique_candidate_message_count": candidate_counts["unique_candidate_message_count"],
                    "selected_suggestion_message_count": len(selected_ids),
                    "suggestion_range_count": sum(len(value) for value in suggestions_by_window.values()),
                    **_overlap_diagnostics(ledger.records, selected_ids, set()),
                }
                fallback_processing = {
                    "direct_synthesis_input_tokens": preflight.input_tokens,
                    "synthesis_usable_input_tokens": usable,
                    "compaction_applied": False,
                    "compaction_levels": compaction_levels,
                    "compaction_group_calls": compaction_group_calls,
                }
                result, _ = assemble_synthesis_result(
                    None,
                    records=ledger.records,
                    evidence_validation=evidence_validation,
                    strategy=strategy,
                    message_count=len(messages),
                    planned_window_count=len(windows),
                    usable_window_count=len(completed_windows),
                    unavailable_window_count=len(unavailable),
                    retrieval_diagnostics=fallback_diagnostics,
                    ledger_processing=fallback_processing,
                    usage=collector.summary(),
                )
                yield sequencer.event(
                    "warning",
                    data={"code": "COMPACTION_UNAVAILABLE", "details": fallback_warning["details"], "stage": "compaction", "operation": "ledger_compaction", "window_id": None},
                )
                yield sequencer.event(
                    "warning",
                    data={"code": "SYNTHESIS_UNAVAILABLE", "details": {"reason": "original_ledger_did_not_fit_after_compaction_failure"}, "stage": "synthesis", "operation": "ledger_synthesis", "window_id": None},
                )
                yield sequencer.event(
                    "synthesis_validation_completed",
                    data={"status": "unavailable", "result_count": 0, "verified_citation_count": 0, "unverified_citation_count": 0, "omitted_range_count": len(result["unclassified_evidence"]), "warning_count": len(result["synthesis_validation"]["warnings"])},
                )
                yield sequencer.event("retrieval_overlap_completed", data={
                    key: fallback_diagnostics[key]
                    for key in (
                        "final_ranges_overlapping_suggestions",
                        "final_ranges_outside_suggestions",
                        "answer_relevant_ranges_overlapping_suggestions",
                        "answer_relevant_ranges_outside_suggestions",
                        "suggestions_without_final_evidence",
                    )
                })
                for warning in result["synthesis_validation"]["warnings"]:
                    logged("result_warning", severity="WARNING", warning_code=warning["code"])
                logged("request_completed", completion_status=result["completion_status"], answer_source=result["answer_source"])
                yield sequencer.event("completed", result=result)
                return
            for task in active_tasks:
                task.cancel()
            await asyncio.gather(*active_tasks, return_exceptions=True)
            stage = "ledger" if isinstance(exc, LedgerError) else "window" if isinstance(exc, UnsplittableMessage) else "analysis_plan" if isinstance(exc, (AnalysisPlanStale, RetrievalGeometryMismatch)) else "provider"
            info = map_error(exc, stage=stage)
            safe_error_details = dict(info.details or {})
            logged(
                "request_failed",
                stage=info.stage,
                error_code=info.code,
                http_status=info.status,
                completed_windows=completed_window_count,
                window_count=len(windows),
                **safe_error_details,
            )
            details = safe_error_details
            details.update({"completed_windows": completed_window_count, "window_count": len(windows)})
            yield sequencer.event(
                "failed",
                error={
                    "request_id": request.request_id,
                    "code": info.code,
                    "message": info.message,
                    "stage": info.stage,
                    "retryable": info.retryable,
                    "details": details,
                },
            )

    return StreamingResponse(stream(), media_type="application/x-ndjson")
