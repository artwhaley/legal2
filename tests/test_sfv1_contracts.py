import uuid

import pytest
from pydantic import ValidationError

from server.contracts import (
    ConversationalAnalysisRequest,
    KeywordExpansionOutput,
    WindowEvidenceEnvelope,
    parse_ndjson_event,
)
from message_evidence_workstation.client_api.contracts import (
    validate_stream_value,
)


def request_id() -> str:
    return str(uuid.uuid4())


def test_requests_reject_unknown_fields_and_wrong_types():
    with pytest.raises(ValidationError):
        ConversationalAnalysisRequest.model_validate({"request_id": request_id(), "question": "q", "working_corpus": {"scope_id": "s", "messages": []}, "analysis_context": {}, "extra": 1})
    with pytest.raises(ValidationError):
        KeywordExpansionOutput.model_validate({"terms": [1]})


def test_window_evidence_requires_exact_empty_or_nonempty_shape():
    with pytest.raises(ValidationError):
        WindowEvidenceEnvelope.model_validate({"window_id": "w1", "no_relevant_evidence": True, "evidence_ranges": [], "uncertainties": []})


def test_stream_event_rejects_unknown_and_wrong_terminal_shape():
    base = {"request_id": request_id(), "sequence": 1, "timestamp": "2026-01-01T00:00:00Z", "config_version": 1}
    with pytest.raises(ValidationError):
        parse_ndjson_event({**base, "event": "failed", "error": {"request_id": base["request_id"], "code": "X", "message": "x", "stage": "provider", "retryable": False, "details": {}, "extra": 1}}, endpoint="/v1/embeddings")
    with pytest.raises(ValidationError):
        parse_ndjson_event({**base, "event": "completed", "result": {"total_items": 1, "embedding_profile_id": "p"}}, endpoint="/v1/conversational-analysis")


def test_exact_event_data_rejects_missing_required_fields():
    base = {"request_id": request_id(), "sequence": 1, "timestamp": "2026-01-01T00:00:00Z", "config_version": 1}
    with pytest.raises(ValidationError):
        parse_ndjson_event({**base, "event": "window_plan_created", "data": {"window_count": 1, "message_count": 1}}, endpoint="/v1/conversational-analysis")
    with pytest.raises(ValidationError):
        parse_ndjson_event({**base, "event": "embedding_progress", "data": {"completed_items": 1, "total_items": 1, "server_items_per_second": 0.0, "extra": 1}}, endpoint="/v1/embeddings")


def test_server_and_temporary_python_client_accept_retry_and_heartbeat_contracts():
    base = {
        "request_id": request_id(),
        "sequence": 1,
        "timestamp": "2026-01-01T00:00:00Z",
        "config_version": 1,
    }
    events = [
        {
            **base,
            "event": "retry_wait",
            "data": {
                "operation": "window_evidence_extraction",
                "failed_attempt": 1,
                "next_attempt": 2,
                "delay_ms": 2000,
                "error_code": "PROVIDER_UNAVAILABLE",
                "window_id": "w000001",
                "window_index": 0,
                "window_count": 8,
            },
        },
        {
            **base,
            "event": "heartbeat",
            "data": {
                "operation": "window_evidence_extraction",
                "elapsed_ms": 10000,
                "completed_windows": 0,
                "active_windows": 2,
                "window_count": 8,
            },
        },
        {
            **base,
            "event": "window_plan_created",
            "data": {
                "strategy": "single_window_ledger",
                "window_count": 1,
                "message_count": 1,
                "hard_input_tokens": 100,
                "target_input_tokens": 80,
                "utilization_percent": 80.0,
                "retrieval_reserve_tokens": 0,
                "window_plan_hash": "a" * 64,
            },
        },
    ]
    for event in events:
        parse_ndjson_event(
            event,
            endpoint="/v1/conversational-analysis",
        )
        validate_stream_value(
            event,
            endpoint="/v1/conversational-analysis",
        )


@pytest.mark.parametrize(
    "event_name,data",
    [
        (
            "window_completed",
            {
                "window_id": "w000001",
                "window_index": 0,
                "window_count": 1,
                "accepted_range_count": 1,
                "rejected_range_count": 1,
                "normalized_range_count": 0,
                "validation_status": "complete",
                "input_tokens": 1,
                "output_tokens": 1,
                "usage_source": "estimated",
                "estimated_cost": None,
            },
        ),
        (
            "evidence_validation_completed",
            {
                "window_count": 1,
                "accepted_range_count": 1,
                "rejected_range_count": 0,
                "normalized_range_count": 2,
                "status": "complete",
            },
        ),
    ],
)
def test_server_and_python_client_reject_inconsistent_validation_events(event_name, data):
    value = {
        "request_id": request_id(),
        "sequence": 1,
        "event": event_name,
        "timestamp": "2026-01-01T00:00:00Z",
        "config_version": 1,
        "data": data,
    }
    with pytest.raises(ValidationError):
        parse_ndjson_event(value, endpoint="/v1/conversational-analysis")
    with pytest.raises(ValueError):
        validate_stream_value(value, endpoint="/v1/conversational-analysis")
