"""Strict transport validation for the Python test client.

The client validates the server contract and executes the returned analysis
plan.  It does not construct or revise analysis policy.
"""

from __future__ import annotations

import math
import re
import uuid
from dataclasses import dataclass
from typing import Any


FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")
CONVERSATION_EVENTS = {
    "accepted", "queued", "retry_wait", "heartbeat", "accounting_completed",
    "analysis_plan_accepted", "retrieval_suggestions_built", "window_plan_created",
    "window_started", "window_completed", "evidence_validation_completed",
    "ledger_built", "ledger_synthesis_preflight", "ledger_compaction_required",
    "ledger_compaction_group_started", "ledger_compaction_group_completed",
    "ledger_compaction_level_completed", "ledger_compaction_completed",
    "ledger_synthesis_started", "ledger_synthesis_received",
    "synthesis_validation_completed", "warning", "window_output_unusable",
    "window_unavailable", "retrieval_overlap_completed", "completed", "failed",
}
EMBEDDING_EVENTS = {
    "accepted", "queued", "embedding_batch_started", "vector_batch",
    "embedding_progress", "completed", "failed",
}


def _int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _number(value: Any) -> bool:
    return _int(value) or isinstance(value, float)


def _uuid(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        uuid.UUID(value)
    except (ValueError, AttributeError):
        return False
    return True


def _fingerprint(value: Any) -> bool:
    return isinstance(value, str) and FINGERPRINT_RE.fullmatch(value) is not None


def _exact(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"{label} fields do not match the stream contract")
    return value


def _string(value: Any, label: str, *, maximum: int = 20_000, trimmed: bool = False) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ValueError(f"{label} is invalid")
    if trimmed and value != value.strip():
        raise ValueError(f"{label} must be trimmed")
    return value


def _string_list(value: Any, label: str, *, maximum_items: int, minimum_items: int = 0) -> list[str]:
    if not isinstance(value, list) or not minimum_items <= len(value) <= maximum_items:
        raise ValueError(f"{label} count is invalid")
    result = [_string(item, label, trimmed=True) for item in value]
    if len(result) != len(set(result)):
        raise ValueError(f"{label} must be unique")
    return result


def _validate_analysis_plan_body(value: Any) -> dict[str, Any]:
    plan = _exact(
        value,
        {
            "analysis_question", "answer_objective", "concepts",
            "inclusion_criteria", "exclusion_criteria", "answer_requirements",
            "interpretive_assumptions",
        },
        "analysis plan",
    )
    _string(plan["analysis_question"], "analysis_question", trimmed=True)
    _string(plan["answer_objective"], "answer_objective", trimmed=True)
    concepts = plan["concepts"]
    if not isinstance(concepts, list) or not 1 <= len(concepts) <= 12:
        raise ValueError("analysis plan concepts are invalid")
    for concept in concepts:
        concept = _exact(concept, {"label", "definition", "manifestations"}, "analysis concept")
        _string(concept["label"], "concept label", trimmed=True)
        _string(concept["definition"], "concept definition", trimmed=True)
        _string_list(concept["manifestations"], "concept manifestations", maximum_items=12, minimum_items=1)
    _string_list(plan["inclusion_criteria"], "inclusion criteria", maximum_items=20, minimum_items=1)
    _string_list(plan["exclusion_criteria"], "exclusion criteria", maximum_items=20)
    _string_list(plan["answer_requirements"], "answer requirements", maximum_items=12, minimum_items=1)
    _string_list(plan["interpretive_assumptions"], "interpretive assumptions", maximum_items=12)
    return plan


def _validate_queries(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not 1 <= len(value) <= 20:
        raise ValueError("retrieval query count is invalid")
    result: list[dict[str, Any]] = []
    query_ids: set[str] = set()
    texts: set[str] = set()
    for item in value:
        query = _exact(item, {"query_id", "text"}, "retrieval query")
        query_id = _string(query["query_id"], "retrieval query ID", maximum=512, trimmed=True)
        text = _string(query["text"], "retrieval query text", maximum=512, trimmed=True)
        if query_id in query_ids or text.casefold() in texts:
            raise ValueError("retrieval queries must have unique IDs and text")
        query_ids.add(query_id)
        texts.add(text.casefold())
        result.append(query)
    return result


def _validate_embedding(value: Any, *, required: bool = False) -> dict[str, Any] | None:
    if value is None:
        if required:
            raise ValueError("semantic mode requires embedding metadata")
        return None
    embedding = _exact(
        value,
        {"embedding_profile_id", "artifact_fingerprint", "dimensions", "normalization"},
        "embedding metadata",
    )
    _string(embedding["embedding_profile_id"], "embedding profile ID", maximum=512)
    if not _fingerprint(embedding["artifact_fingerprint"]):
        raise ValueError("embedding artifact fingerprint is invalid")
    if not _int(embedding["dimensions"]) or embedding["dimensions"] < 1:
        raise ValueError("embedding dimensions are invalid")
    if embedding["normalization"] not in {"unit_l2", "none"}:
        raise ValueError("embedding normalization is invalid")
    return embedding


def _validate_search_policy(value: Any) -> dict[str, Any]:
    policy = _exact(
        value,
        {"mode", "top_k_per_query", "fusion_method", "rrf_constant", "maximum_prompt_suggestion_messages"},
        "search policy",
    )
    if policy["mode"] not in {"none", "semantic_ranges"} or policy["fusion_method"] != "reciprocal_rank_fusion":
        raise ValueError("search policy mode or fusion method is invalid")
    for key, maximum in (("top_k_per_query", 1000), ("rrf_constant", 1000), ("maximum_prompt_suggestion_messages", 500)):
        if not _int(policy[key]) or not 1 <= policy[key] <= maximum:
            raise ValueError(f"search policy {key} is invalid")
    return policy


def _validate_usage(value: Any, label: str) -> dict[str, Any]:
    usage = _exact(value, {"input_tokens", "output_tokens", "source", "estimated_cost", "cost_complete", "currency"}, label)
    if not _int(usage["input_tokens"]) or usage["input_tokens"] < 0:
        raise ValueError(f"{label}.input_tokens is invalid")
    if not _int(usage["output_tokens"]) or usage["output_tokens"] < 0:
        raise ValueError(f"{label}.output_tokens is invalid")
    if usage["source"] not in {"provider_reported", "estimated", "mixed"}:
        raise ValueError(f"{label}.source is invalid")
    if usage["estimated_cost"] is not None and (not _number(usage["estimated_cost"]) or not math.isfinite(float(usage["estimated_cost"])) or usage["estimated_cost"] < 0):
        raise ValueError(f"{label}.estimated_cost is invalid")
    if not isinstance(usage["cost_complete"], bool) or usage["currency"] != "USD":
        raise ValueError(f"{label} completion or currency is invalid")
    return usage


def validate_analysis_plan(value: Any) -> dict[str, Any]:
    """Validate the exact v4 planning response returned by the server."""
    result = _exact(
        value,
        {
            "request_id", "config_version", "analysis_plan_id", "compatibility_fingerprint",
            "analysis_plan", "retrieval_queries", "embedding", "search_policy", "usage",
        },
        "analysis plan",
    )
    if not _uuid(result["request_id"]) or not _int(result["config_version"]) or result["config_version"] < 1 or not _uuid(result["analysis_plan_id"]):
        raise ValueError("analysis plan identity is invalid")
    if not _fingerprint(result["compatibility_fingerprint"]):
        raise ValueError("analysis plan fingerprint is invalid")
    _validate_analysis_plan_body(result["analysis_plan"])
    _validate_queries(result["retrieval_queries"])
    policy = _validate_search_policy(result["search_policy"])
    _validate_embedding(result["embedding"], required=policy["mode"] == "semantic_ranges")
    if policy["mode"] == "none" and result["embedding"] is not None:
        raise ValueError("none analysis plan must have null embedding")
    _validate_usage(result["usage"], "analysis plan usage")
    return result


def validate_analysis_context(value: Any) -> dict[str, Any]:
    """Validate the exact frozen context sent to conversational analysis."""
    context = _exact(
        value,
        {
            "analysis_plan_id", "plan_config_version", "compatibility_fingerprint", "analysis_plan",
            "retrieval_queries", "embedding", "search_policy", "hits",
        },
        "analysis context",
    )
    if not _uuid(context["analysis_plan_id"]) or not _int(context["plan_config_version"]) or context["plan_config_version"] < 1:
        raise ValueError("analysis context identity is invalid")
    if not _fingerprint(context["compatibility_fingerprint"]):
        raise ValueError("analysis context fingerprint is invalid")
    _validate_analysis_plan_body(context["analysis_plan"])
    queries = _validate_queries(context["retrieval_queries"])
    policy = _validate_search_policy(context["search_policy"])
    _validate_embedding(context["embedding"], required=policy["mode"] == "semantic_ranges")
    hits = context["hits"]
    if not isinstance(hits, list):
        raise ValueError("analysis context hits must be a list")
    query_ids = {str(query["query_id"]) for query in queries}
    pairs: set[tuple[str, str]] = set()
    ranks: dict[str, list[int]] = {}
    for hit in hits:
        hit = _exact(hit, {"query_id", "message_id", "rank", "distance"}, "retrieval hit")
        query_id = _string(hit["query_id"], "retrieval hit query ID", maximum=512, trimmed=True)
        message_id = _string(hit["message_id"], "retrieval hit message ID", maximum=512, trimmed=True)
        if query_id not in query_ids or not _int(hit["rank"]) or hit["rank"] < 1 or not _number(hit["distance"]) or not math.isfinite(float(hit["distance"])) or hit["distance"] < 0:
            raise ValueError("retrieval hit is invalid")
        pair = (query_id, message_id)
        if pair in pairs:
            raise ValueError("retrieval query/message pairs must be unique")
        pairs.add(pair)
        ranks.setdefault(query_id, []).append(hit["rank"])
    for query_id, values in ranks.items():
        if sorted(values) != list(range(1, len(values) + 1)):
            raise ValueError(f"ranks for {query_id} must be contiguous from 1")
    if policy["mode"] == "none" and (context["embedding"] is not None or hits):
        raise ValueError("none analysis context must have null embedding and empty hits")
    if policy["mode"] == "semantic_ranges" and not hits:
        raise ValueError("semantic analysis context requires hits")
    return context


WARNING_CODES = {
    "UNKNOWN_RANGE_ID", "UNKNOWN_MESSAGE_ID", "RANGE_ENDPOINTS_REVERSED",
    "THREAD_ID_CORRECTED", "CROSS_THREAD_RANGE", "AMBIGUOUS_RANGE",
    "DUPLICATE_CITATION", "CITATION_PARTIALLY_VERIFIED", "CITATION_UNVERIFIED",
    "UNKNOWN_PROBABILITY", "SYNTHESIS_OUTPUT_NONCONFORMANT",
    "SYNTHESIS_RESULT_UNCLASSIFIED", "SYNTHESIS_OMITTED_LEDGER_RANGE",
    "WINDOW_OUTPUT_UNUSABLE", "WINDOW_UNAVAILABLE", "COMPACTION_UNAVAILABLE",
    "SYNTHESIS_UNAVAILABLE",
}


def _validate_warning(value: Any, label: str = "warning") -> None:
    warning = _exact(value, {"code", "details"}, label)
    if warning["code"] not in WARNING_CODES or not isinstance(warning["details"], dict):
        raise ValueError(f"{label} is invalid")


def _validate_diagnostics(value: Any) -> None:
    diagnostics = _exact(
        value,
        {"mode", "query_count", "raw_hit_count", "unique_candidate_message_count", "selected_suggestion_message_count", "suggestion_range_count", "final_ranges_overlapping_suggestions", "final_ranges_outside_suggestions", "answer_relevant_ranges_overlapping_suggestions", "answer_relevant_ranges_outside_suggestions", "suggestions_without_final_evidence"},
        "retrieval diagnostics",
    )
    if diagnostics["mode"] not in {"none", "semantic_ranges"} or any(not _int(item) or item < 0 for key, item in diagnostics.items() if key != "mode"):
        raise ValueError("retrieval diagnostics are invalid")


def _validate_evidence_validation(value: Any) -> None:
    validation = _exact(
        value,
        {"planned_window_count", "usable_window_count", "unavailable_window_count", "unavailable_windows", "status", "accepted_range_count", "rejected_range_count", "normalized_range_count", "rejected_ranges", "warnings"},
        "evidence validation",
    )
    integer_keys = {"planned_window_count", "usable_window_count", "unavailable_window_count", "accepted_range_count", "rejected_range_count", "normalized_range_count"}
    if any(not _int(validation[key]) or validation[key] < 0 for key in integer_keys):
        raise ValueError("evidence validation counts are invalid")
    if validation["status"] not in {"complete", "partial"} or validation["usable_window_count"] + validation["unavailable_window_count"] != validation["planned_window_count"]:
        raise ValueError("evidence validation status or window counts are invalid")
    if not isinstance(validation["unavailable_windows"], list) or validation["unavailable_window_count"] != len(validation["unavailable_windows"]):
        raise ValueError("unavailable window diagnostics are invalid")
    for item in validation["unavailable_windows"]:
        item = _exact(item, {"window_id", "window_index", "window_count", "attempts", "code"}, "unavailable window diagnostic")
        _string(item["window_id"], "unavailable window ID", maximum=512)
        if any(not _int(item[key]) or item[key] < 0 for key in ("window_index", "attempts")) or not _int(item["window_count"]) or item["window_count"] < 1:
            raise ValueError("unavailable window counts are invalid")
        _string(item["code"], "unavailable window code", maximum=512)
    if not isinstance(validation["rejected_ranges"], list) or validation["rejected_range_count"] != len(validation["rejected_ranges"]):
        raise ValueError("rejected range diagnostics are invalid")
    for item in validation["rejected_ranges"]:
        item = _exact(item, {"window_id", "range_index", "code", "message", "declared_thread_id", "start_message_id", "end_message_id"}, "rejected range diagnostic")
        _string(item["window_id"], "rejected range window ID", maximum=512)
        if not _int(item["range_index"]) or item["range_index"] < 0:
            raise ValueError("rejected range index is invalid")
        _string(item["code"], "rejected range code", maximum=512)
        _string(item["message"], "rejected range message")
        for key in ("declared_thread_id", "start_message_id", "end_message_id"):
            if item[key] is not None:
                _string(item[key], f"rejected range {key}", maximum=512)
    if not isinstance(validation["warnings"], list):
        raise ValueError("evidence validation warnings are invalid")
    for warning in validation["warnings"]:
        _validate_warning(warning, "evidence warning")
    expected = "partial" if validation["rejected_range_count"] or validation["unavailable_window_count"] else "complete"
    if validation["status"] != expected or validation["normalized_range_count"] > validation["accepted_range_count"]:
        raise ValueError("evidence validation totals are inconsistent")


def _validate_result_item(value: Any, ledger_ids: set[str]) -> None:
    item = _exact(value, {"probability", "classification_status", "statement", "reported_range_ids", "verified_range_ids", "unverified_range_ids", "citation_status", "uncertainty", "warnings"}, "public result")
    if item["classification_status"] not in {"model_classified", "unclassified"} or item["citation_status"] not in {"verified", "partial", "unverified"}:
        raise ValueError("public result classification is invalid")
    if item["probability"] not in {None, "high_probability", "lower_probability"} or (item["classification_status"] == "model_classified") != (item["probability"] is not None):
        raise ValueError("public result probability is invalid")
    _string(item["statement"], "public result statement")
    reported = _string_list(item["reported_range_ids"], "reported range IDs", maximum_items=100000, minimum_items=1)
    verified = _string_list(item["verified_range_ids"], "verified range IDs", maximum_items=100000)
    unverified = _string_list(item["unverified_range_ids"], "unverified range IDs", maximum_items=100000)
    if set(verified) & set(unverified) or set(verified) | set(unverified) != set(reported):
        raise ValueError("public result citation partitions are invalid")
    if item["citation_status"] != ("verified" if not unverified else "partial" if verified else "unverified"):
        raise ValueError("public result citation status is invalid")
    if item["uncertainty"] is not None:
        _string(item["uncertainty"], "public result uncertainty")
    if not isinstance(item["warnings"], list):
        raise ValueError("public result warnings are invalid")
    for warning in item["warnings"]:
        _validate_warning(warning, "public result warning")
    if not set(verified) <= ledger_ids:
        raise ValueError("public result contains an unknown verified range")


def _validate_completed_result(payload: Any) -> None:
    result = _exact(
        payload,
        {"completion_status", "answer_source", "overview", "raw_answer", "results", "unclassified_evidence", "unverified_model_statements", "evidence_ledger", "evidence_validation", "synthesis_validation", "coverage", "retrieval_diagnostics", "ledger_processing", "usage", "uncertainties", "strategy"},
        "conversation completed result",
    )
    if result["completion_status"] not in {"complete", "complete_with_warnings", "partial"} or result["answer_source"] not in {"structured_synthesis", "raw_synthesis_output", "synthesis_unavailable"} or result["strategy"] not in {"single_window_ledger", "multi_window_ledger"}:
        raise ValueError("conversation result identity is invalid")
    if result["answer_source"] == "structured_synthesis":
        _string(result["overview"], "structured overview")
        if result["raw_answer"] is not None:
            raise ValueError("structured result must not contain raw output")
    elif result["answer_source"] == "raw_synthesis_output":
        _string(result["raw_answer"], "raw synthesis output")
        if result["overview"] is not None:
            raise ValueError("raw result must not contain structured overview")
    elif result["overview"] is not None or result["raw_answer"] is not None:
        raise ValueError("unavailable result must not contain synthesis text")
    if not isinstance(result["uncertainties"], list) or any(not isinstance(item, str) or not item.strip() for item in result["uncertainties"]):
        raise ValueError("conversation uncertainties are invalid")
    ledger_ids: set[str] = set()
    if not isinstance(result["evidence_ledger"], list):
        raise ValueError("evidence ledger must be a list")
    for record in result["evidence_ledger"]:
        record = _exact(record, {"range_id", "window_id", "source_range_index", "thread_id", "start_message_id", "end_message_id", "summary", "relevance", "normalizations"}, "evidence ledger record")
        if record["range_id"] in ledger_ids or not _int(record["source_range_index"]) or record["source_range_index"] < 0:
            raise ValueError("evidence ledger identity is invalid")
        ledger_ids.add(_string(record["range_id"], "evidence range ID", maximum=512))
        for key in ("window_id", "thread_id", "start_message_id", "end_message_id"):
            _string(record[key], f"evidence ledger {key}", maximum=512)
        for key in ("summary", "relevance"):
            if record[key] is not None:
                _string(record[key], f"evidence ledger {key}")
        if not isinstance(record["normalizations"], list) or any(item != "endpoint_order_swapped" for item in record["normalizations"]):
            raise ValueError("evidence ledger normalizations are invalid")
    if not isinstance(result["results"], list):
        raise ValueError("public results must be a list")
    for item in result["results"]:
        _validate_result_item(item, ledger_ids)
    if not isinstance(result["unclassified_evidence"], list) or not isinstance(result["unverified_model_statements"], list):
        raise ValueError("result evidence sections must be lists")
    for item in result["unclassified_evidence"]:
        item = _exact(item, {"range_id", "summary", "relevance", "reason"}, "unclassified evidence")
        if item["range_id"] not in ledger_ids or item["reason"] != "not_referenced_by_synthesis":
            raise ValueError("unclassified evidence identity is invalid")
        for key in ("summary", "relevance"):
            if item[key] is not None:
                _string(item[key], f"unclassified evidence {key}")
    for item in result["unverified_model_statements"]:
        item = _exact(item, {"statement", "reported_range_ids", "probability", "uncertainty", "warnings"}, "unverified model statement")
        _string(item["statement"], "unverified model statement")
        _string_list(item["reported_range_ids"], "unverified reported range IDs", maximum_items=100000)
        if item["probability"] not in {None, "high_probability", "lower_probability"}:
            raise ValueError("unverified model probability is invalid")
        if item["uncertainty"] is not None:
            _string(item["uncertainty"], "unverified model uncertainty")
        for warning in item["warnings"]:
            _validate_warning(warning, "unverified model warning")
    _validate_evidence_validation(result["evidence_validation"])
    synthesis = _exact(result["synthesis_validation"], {"status", "raw_output_preserved", "warnings"}, "synthesis validation")
    if synthesis["status"] not in {"conformant", "warnings", "unparseable", "unavailable"} or not isinstance(synthesis["raw_output_preserved"], bool) or not isinstance(synthesis["warnings"], list):
        raise ValueError("synthesis validation is invalid")
    for warning in synthesis["warnings"]:
        _validate_warning(warning, "synthesis warning")
    coverage = _exact(result["coverage"], {"message_count", "planned_window_count", "usable_window_count", "unavailable_window_count", "evidence_range_count"}, "conversation coverage")
    if any(not _int(item) or item < 0 for item in coverage.values()) or coverage["usable_window_count"] + coverage["unavailable_window_count"] != coverage["planned_window_count"]:
        raise ValueError("conversation coverage is invalid")
    _validate_diagnostics(result["retrieval_diagnostics"])
    processing = _exact(result["ledger_processing"], {"direct_synthesis_input_tokens", "synthesis_usable_input_tokens", "compaction_applied", "compaction_levels", "compaction_group_calls"}, "ledger processing")
    if not isinstance(processing["compaction_applied"], bool) or any(not _int(item) or item < 0 for key, item in processing.items() if key != "compaction_applied"):
        raise ValueError("ledger processing is invalid")
    _validate_usage(result["usage"], "conversation usage")
    if result["completion_status"] == "complete" and (result["evidence_validation"]["status"] != "complete" or result["synthesis_validation"]["status"] != "conformant" or result["unclassified_evidence"] or result["unverified_model_statements"] or any(item["warnings"] for item in result["results"])):
        raise ValueError("complete result contains warning or partial facts")


def _validate_compaction_data(event: str, data: dict[str, Any]) -> None:
    common = {"level", "group_id", "group_index", "group_count", "covered_range_count"}
    if event == "ledger_compaction_group_started":
        _exact(data, common, event)
    elif event == "ledger_compaction_group_completed":
        _exact(data, common | {"input_tokens", "output_tokens", "usage_source", "estimated_cost"}, event)
    elif event == "ledger_compaction_level_completed":
        _exact(data, {"level", "group_count", "covered_range_count"}, event)
    elif event == "ledger_compaction_completed":
        _exact(data, {"levels", "group_calls", "original_range_count", "covered_range_count", "final_synthesis_input_tokens"}, event)
    else:
        _exact(data, {"evidence_range_count", "evidence_message_count", "required_input_tokens", "usable_input_tokens", "excess_input_tokens", "direct_fit", "maximum_depth"}, event)
    for key, item in data.items():
        if key in {"group_id", "usage_source"}:
            _string(item, f"{event}.{key}", maximum=512)
        elif key == "estimated_cost":
            if item is not None and (not _number(item) or not math.isfinite(float(item)) or item < 0):
                raise ValueError(f"{event}.estimated_cost is invalid")
        elif key == "direct_fit":
            if not isinstance(item, bool):
                raise ValueError(f"{event}.direct_fit is invalid")
        elif not _int(item) or item < 0:
            raise ValueError(f"{event}.{key} is invalid")


def _validate_nonnegative(data: dict[str, Any], keys: set[str], event: str, *, positive: set[str] | None = None) -> None:
    for key in keys:
        value = data[key]
        if not _int(value) or value < 0 or (positive and key in positive and value == 0):
            raise ValueError(f"{event}.{key} is invalid")


def validate_stream_value(value: Any, *, endpoint: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("stream event must be an object")
    event = value.get("event")
    allowed = CONVERSATION_EVENTS if endpoint == "/v1/conversational-analysis" else EMBEDDING_EVENTS if endpoint == "/v1/embeddings" else None
    if allowed is None or event not in allowed:
        raise ValueError("stream event is not valid for this endpoint")
    payload_key = "error" if event == "failed" else "result" if event == "completed" else "data"
    _exact(value, {"request_id", "sequence", "event", "timestamp", "config_version", payload_key}, "event envelope")
    if not _uuid(value["request_id"]) or not _int(value["sequence"]) or value["sequence"] < 1 or not isinstance(value["timestamp"], str) or not value["timestamp"] or not _int(value["config_version"]) or value["config_version"] < 1:
        raise ValueError("stream envelope has invalid scalar fields")
    payload = value[payload_key]
    if event == "failed":
        error = _exact(payload, {"request_id", "code", "message", "stage", "retryable", "details"}, "failed error")
        if error["request_id"] != value["request_id"] or any(not isinstance(error[key], str) or not error[key] for key in ("code", "message", "stage")) or not isinstance(error["retryable"], bool) or not isinstance(error["details"], dict):
            raise ValueError("failed error has invalid fields")
        return value
    if event == "accepted":
        if endpoint == "/v1/embeddings":
            data = _exact(payload, {"endpoint", "total_items", "embedding_profile_id", "model", "requested_revision", "artifact_fingerprint", "dimensions", "normalization"}, "embedding accepted data")
            if data["endpoint"] != endpoint or not isinstance(data["model"], str) or not isinstance(data["requested_revision"], str) or not isinstance(data["artifact_fingerprint"], str) or not _int(data["total_items"]) or data["total_items"] < 1 or not _int(data["dimensions"]) or data["dimensions"] < 1 or data["normalization"] not in {"unit_l2", "none"}:
                raise ValueError("embedding accepted data is invalid")
        else:
            data = _exact(payload, {"endpoint", "scope_id", "message_count"}, "conversation accepted data")
            if data["endpoint"] != endpoint or not isinstance(data["scope_id"], str) or not _int(data["message_count"]) or data["message_count"] < 1:
                raise ValueError("conversation accepted data is invalid")
        return value
    if event == "completed":
        if endpoint == "/v1/embeddings":
            result = _exact(payload, {"total_items", "embedding_profile_id"}, "embedding completed result")
            if not _int(result["total_items"]) or result["total_items"] < 1 or not isinstance(result["embedding_profile_id"], str) or not result["embedding_profile_id"]:
                raise ValueError("embedding completed result is invalid")
        else:
            _validate_completed_result(payload)
        return value
    if event == "vector_batch":
        data = _exact(payload, {"batch_index", "items"}, "vector batch data")
        if not _int(data["batch_index"]) or data["batch_index"] < 0 or not isinstance(data["items"], list) or not data["items"]:
            raise ValueError("vector batch metadata is invalid")
        for item in data["items"]:
            item = _exact(item, {"message_id", "vector"}, "vector item")
            if not isinstance(item["message_id"], str) or not item["message_id"] or not isinstance(item["vector"], list) or not item["vector"] or any(not _number(number) or not math.isfinite(float(number)) for number in item["vector"]):
                raise ValueError("vector item is invalid")
        return value
    if event in {"queued", "retry_wait"}:
        base = {"operation", "queued_count", "wait_timeout_ms"} if event == "queued" else {"operation", "failed_attempt", "next_attempt", "delay_ms", "error_code"}
        optional = {"window_id", "window_index", "window_count"}
        if not set(payload) <= base | optional or not base <= set(payload) or ({key for key in optional if key in payload} not in (set(), optional)):
            raise ValueError(f"{event} data fields do not match the stream contract")
        _string(payload["operation"], f"{event}.operation")
        _string(payload["error_code"], f"{event}.error_code") if event == "retry_wait" else None
        _validate_nonnegative(payload, {"queued_count", "wait_timeout_ms"} if event == "queued" else {"failed_attempt", "next_attempt", "delay_ms"}, event, positive={"failed_attempt", "next_attempt"} if event == "retry_wait" else set())
        if event == "retry_wait" and payload["next_attempt"] <= payload["failed_attempt"]:
            raise ValueError("retry attempts are not increasing")
        if "window_id" in payload:
            _string(payload["window_id"], f"{event}.window_id")
            _validate_nonnegative(payload, {"window_index"}, event)
            _validate_nonnegative(payload, {"window_count"}, event, positive={"window_count"})
    elif event == "heartbeat":
        _exact(payload, {"operation", "elapsed_ms", "completed_windows", "active_windows", "window_count"}, event)
        _string(payload["operation"], f"{event}.operation")
        _validate_nonnegative(payload, {"elapsed_ms", "completed_windows", "active_windows", "window_count"}, event)
    elif event == "accounting_completed":
        _exact(payload, {"corpus_tokens", "analysis_input_tokens", "context_window_tokens", "reserved_output_tokens", "safety_margin_tokens", "strategy"}, event)
        _string(payload["strategy"], f"{event}.strategy")
        _validate_nonnegative(payload, {"corpus_tokens", "analysis_input_tokens", "context_window_tokens", "reserved_output_tokens", "safety_margin_tokens"}, event, positive={"context_window_tokens"})
    elif event == "analysis_plan_accepted":
        _exact(payload, {"analysis_plan_id", "compatibility_fingerprint", "concept_count", "retrieval_query_count", "retrieval_mode"}, event)
        if not _uuid(payload["analysis_plan_id"]) or not _fingerprint(payload["compatibility_fingerprint"]) or payload["retrieval_mode"] not in {"none", "semantic_ranges"}:
            raise ValueError("analysis plan acceptance is invalid")
        _validate_nonnegative(payload, {"concept_count", "retrieval_query_count"}, event, positive={"concept_count", "retrieval_query_count"})
    elif event == "retrieval_suggestions_built":
        _exact(payload, {"unique_candidate_message_count", "selected_suggestion_message_count", "suggestion_range_count", "unselected_candidate_message_count"}, event)
        _validate_nonnegative(payload, set(payload), event)
    elif event == "window_plan_created":
        _exact(payload, {"strategy", "window_count", "message_count", "hard_input_tokens", "target_input_tokens", "utilization_percent", "retrieval_reserve_tokens", "window_plan_hash"}, event)
        _string(payload["strategy"], f"{event}.strategy")
        _validate_nonnegative(payload, {"window_count", "message_count", "hard_input_tokens", "target_input_tokens", "retrieval_reserve_tokens"}, event, positive={"window_count", "message_count", "hard_input_tokens", "target_input_tokens"})
        if not _number(payload["utilization_percent"]) or not 1 <= float(payload["utilization_percent"]) <= 100 or not _fingerprint(payload["window_plan_hash"]):
            raise ValueError("window plan values are invalid")
    elif event == "window_started":
        _exact(payload, {"window_id", "window_index", "window_count", "message_count", "suggestion_range_count"}, event)
        _string(payload["window_id"], f"{event}.window_id")
        _validate_nonnegative(payload, {"window_index", "suggestion_range_count"}, event)
        _validate_nonnegative(payload, {"window_count", "message_count"}, event, positive={"window_count", "message_count"})
    elif event == "window_completed":
        _exact(payload, {"window_id", "window_index", "window_count", "accepted_range_count", "rejected_range_count", "normalized_range_count", "validation_status", "input_tokens", "output_tokens", "usage_source", "estimated_cost"}, event)
        _string(payload["window_id"], f"{event}.window_id")
        _validate_nonnegative(payload, {"window_index", "accepted_range_count", "rejected_range_count", "normalized_range_count", "input_tokens", "output_tokens"}, event)
        _validate_nonnegative(payload, {"window_count"}, event, positive={"window_count"})
        if payload["validation_status"] not in {"complete", "partial"} or payload["validation_status"] != ("partial" if payload["rejected_range_count"] else "complete") or payload["normalized_range_count"] > payload["accepted_range_count"] or payload["usage_source"] not in {"provider_reported", "estimated"}:
            raise ValueError("window validation totals are inconsistent")
    elif event == "evidence_validation_completed":
        _exact(payload, {"planned_window_count", "usable_window_count", "unavailable_window_count", "accepted_range_count", "rejected_range_count", "normalized_range_count", "status"}, event)
        _validate_nonnegative(payload, set(payload) - {"status"}, event)
        if payload["usable_window_count"] + payload["unavailable_window_count"] != payload["planned_window_count"] or payload["status"] != ("partial" if payload["rejected_range_count"] or payload["unavailable_window_count"] else "complete") or payload["normalized_range_count"] > payload["accepted_range_count"]:
            raise ValueError("evidence validation totals are inconsistent")
    elif event == "ledger_built":
        _exact(payload, {"window_count", "evidence_range_count"}, event)
        _validate_nonnegative(payload, set(payload), event, positive={"window_count"})
    elif event == "ledger_synthesis_preflight":
        _exact(payload, {"evidence_range_count", "evidence_message_count", "required_input_tokens", "usable_input_tokens", "excess_input_tokens", "direct_fit"}, event)
        _validate_nonnegative(payload, {key for key in payload if key != "direct_fit"}, event)
        if not isinstance(payload["direct_fit"], bool):
            raise ValueError("synthesis preflight fit flag is invalid")
    elif event == "ledger_compaction_required" or event in {"ledger_compaction_group_started", "ledger_compaction_group_completed", "ledger_compaction_level_completed", "ledger_compaction_completed"}:
        _validate_compaction_data(event, payload)
    elif event == "ledger_synthesis_started":
        _exact(payload, {"evidence_range_count"}, event)
        _validate_nonnegative(payload, set(payload), event)
    elif event == "ledger_synthesis_received":
        _exact(payload, {"evidence_range_count", "content_nonblank", "input_tokens", "output_tokens", "usage_source", "estimated_cost"}, event)
        _validate_nonnegative(payload, {"evidence_range_count", "input_tokens", "output_tokens"}, event)
        if not isinstance(payload["content_nonblank"], bool) or payload["usage_source"] not in {"provider_reported", "estimated"}:
            raise ValueError("synthesis receipt metadata is invalid")
    elif event == "synthesis_validation_completed":
        _exact(payload, {"status", "result_count", "verified_citation_count", "unverified_citation_count", "omitted_range_count", "warning_count"}, event)
        _validate_nonnegative(payload, {key for key in payload if key != "status"}, event)
        if payload["status"] not in {"conformant", "warnings", "unparseable", "unavailable"}:
            raise ValueError("synthesis validation status is invalid")
    elif event == "warning":
        _exact(payload, {"code", "details", "stage", "operation", "window_id"}, event)
        _validate_warning({"code": payload["code"], "details": payload["details"]}, event)
        _string(payload["stage"], f"{event}.stage")
        for key in ("operation", "window_id"):
            if payload[key] is not None:
                _string(payload[key], f"{event}.{key}")
    elif event == "window_output_unusable":
        _exact(payload, {"window_id", "window_index", "window_count", "attempt", "code"}, event)
        _string(payload["window_id"], f"{event}.window_id")
        _string(payload["code"], f"{event}.code")
        _validate_nonnegative(payload, {"window_index"}, event)
        _validate_nonnegative(payload, {"window_count", "attempt"}, event, positive={"window_count", "attempt"})
    elif event == "window_unavailable":
        _exact(payload, {"window_id", "window_index", "window_count", "attempts", "code"}, event)
        _string(payload["window_id"], f"{event}.window_id")
        _string(payload["code"], f"{event}.code")
        _validate_nonnegative(payload, {"window_index", "attempts"}, event)
        _validate_nonnegative(payload, {"window_count"}, event, positive={"window_count"})
    elif event == "retrieval_overlap_completed":
        _exact(payload, {"final_ranges_overlapping_suggestions", "final_ranges_outside_suggestions", "answer_relevant_ranges_overlapping_suggestions", "answer_relevant_ranges_outside_suggestions", "suggestions_without_final_evidence"}, event)
        _validate_nonnegative(payload, set(payload), event)
    elif event == "embedding_batch_started":
        _exact(payload, {"batch_index", "batch_count", "first_item_index", "last_item_index", "item_count"}, event)
        _validate_nonnegative(payload, set(payload), event, positive={"batch_count", "item_count"})
        if payload["last_item_index"] < payload["first_item_index"] or payload["item_count"] != payload["last_item_index"] - payload["first_item_index"] + 1:
            raise ValueError("embedding batch bounds are invalid")
    elif event == "embedding_progress":
        _exact(payload, {"completed_items", "total_items", "server_items_per_second"}, event)
        _validate_nonnegative(payload, {"completed_items", "total_items"}, event, positive={"total_items"})
        if not _number(payload["server_items_per_second"]) or not math.isfinite(float(payload["server_items_per_second"])) or payload["server_items_per_second"] < 0:
            raise ValueError("embedding progress rate is invalid")
    return value


@dataclass(frozen=True, slots=True)
class StreamEvent:
    value: dict[str, Any]

    @property
    def event(self) -> str:
        return str(self.value["event"])

    @property
    def terminal(self) -> bool:
        return self.event in {"completed", "failed"}
