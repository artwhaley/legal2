"""Redacted structured events, bounded ring, metrics, and error mapping."""

from __future__ import annotations

import json
import logging
import sys
import time
from collections import Counter, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from server.provider import ProviderError
from server.resilience import CircuitOpenError, QueueFullError, QueueTimeoutError


_log = logging.getLogger("server.events")


@dataclass(frozen=True, slots=True)
class ErrorInfo:
    code: str
    message: str
    stage: str
    status: int
    retryable: bool = False
    details: dict[str, Any] | None = None


def map_error(exc: Exception, *, stage: str = "request") -> ErrorInfo:
    if isinstance(exc, ProviderError):
        status = 429 if exc.code == "PROVIDER_RATE_LIMITED" else 504 if exc.code == "PROVIDER_TIMEOUT" else 503 if exc.code == "PROVIDER_UNAVAILABLE" else 500 if exc.code == "CONFIGURATION_ERROR" else 502
        return ErrorInfo(exc.code, str(exc), "provider", status, exc.retryable, {"provider_request_id": exc.provider_request_id} if exc.provider_request_id else {})
    if isinstance(exc, QueueFullError):
        return ErrorInfo("SERVER_BUSY", str(exc), "queue", 503)
    if isinstance(exc, QueueTimeoutError):
        return ErrorInfo("QUEUE_TIMEOUT", str(exc), "queue", 503)
    if isinstance(exc, CircuitOpenError):
        return ErrorInfo("CIRCUIT_OPEN", str(exc), "queue", 503)
    if exc.__class__.__name__ == "ConfigurationRequired":
        return ErrorInfo("CONFIGURATION_REQUIRED", "server configuration is required", "request", 503)
    name = str(getattr(exc, "code", "") or exc.__class__.__name__)
    known = {
        "REQUEST_INVALID": (400, "request is invalid"),
        "REQUEST_INTEGRITY_FAILED": (422, "request integrity validation failed"),
        "UNSPLITTABLE_MESSAGE": (422, "a message cannot fit the configured window"),
        "WORKLOAD_TOO_LARGE": (413, "the requested workload exceeds its configured ceiling"),
        "LEDGER_BUDGET_EXCEEDED": (422, "evidence ledger exceeds configured budget"),
        "LEDGER_INTERNAL_INTEGRITY_FAILED": (500, "preserved evidence assembly failed internally"),
        "NO_USABLE_WINDOW_OUTPUT": (502, "no usable evidence extraction output was returned"),
        "NO_USABLE_RESULT": (502, "no useful answer or validated evidence was available"),
        "MODEL_OUTPUT_INVALID": (502, "model output failed strict validation"),
        "ACCOUNTING_PERSISTENCE_FAILED": (500, "usage accounting persistence failed"),
        "CONFIGURATION_ERROR": (500, "active server configuration is invalid"),
        "EMBEDDING_RECONFIGURING": (503, "embedding configuration is being activated"),
        "ANALYSIS_PLAN_EMPTY": (422, "analysis plan is empty"),
        "ANALYSIS_PLAN_STALE": (409, "analysis plan is stale or incompatible"),
        "RETRIEVAL_GEOMETRY_MISMATCH": (409, "retrieval embedding geometry is incompatible"),
    }
    if name in known:
        status, message = known[name]
        details = getattr(exc, "details", None)
        return ErrorInfo(
            name,
            message,
            stage,
            status,
            details=dict(details) if isinstance(details, dict) else None,
        )
    if isinstance(exc, ValueError):
        return ErrorInfo("REQUEST_INVALID", str(exc), stage, 422)
    _log.exception("unmapped server exception", exc_info=exc)
    return ErrorInfo("INTERNAL_ERROR", "internal server error", stage, 500)


class EventSink:
    def __init__(self, ring_size: int = 2000):
        self.events: deque[dict[str, Any]] = deque(maxlen=ring_size)
        self.metrics = Counter()
        self.started_at = time.monotonic()

    def emit(self, event: str, *, request_id: str | None = None, config_version: int | None = None, product_endpoint: str | None = None, internal_operation: str | None = None, **fields: Any) -> dict[str, Any]:
        allowed = {
            "timestamp",
            "severity",
            "event",
            "request_id",
            "config_version",
            "product_endpoint",
            "internal_operation",
            "operation",
            "provider",
            "model",
            "strategy",
            "stage",
            "state",
            "attempt",
            "failed_attempt",
            "next_attempt",
            "delay_ms",
            "queue_wait_ms",
            "latency_ms",
            "elapsed_ms",
            "input_tokens",
            "hard_input_tokens",
            "target_input_tokens",
            "utilization_percent",
            "output_tokens",
            "usage_source",
            "estimated_cost",
            "http_status",
            "error_code",
            "provider_request_id",
            "window_id",
            "window_index",
            "window_count",
            "message_count",
            "evidence_range_count",
            "accepted_range_count",
            "rejected_range_count",
            "normalized_range_count",
            "validation_status",
            "validation_code",
            "reason",
            "range_index",
            "start_message_id",
            "end_message_id",
            "declared_thread_id",
            "start_thread_id",
            "end_thread_id",
            "start_message_index",
            "end_message_index",
            "returned_window_id",
            "completed_windows",
            "active_windows",
            "batch_index",
            "item_count",
            "completed_items",
            "total_items",
            "queued_count",
            "in_flight",
            "completion_status",
            "answer_source",
            "warning_code",
        }
        safe_fields = {key: value for key, value in fields.items() if key in allowed and _safe_scalar(value)}
        record = {"timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "severity": "INFO", "event": event, "request_id": request_id, "config_version": config_version, "product_endpoint": product_endpoint, "internal_operation": internal_operation, **safe_fields}
        self.events.append(record)
        self.metrics[event] += 1
        if event == "request_completed" and fields.get("completion_status") in {"complete", "complete_with_warnings", "partial"}:
            self.metrics[f"completion_status.{fields['completion_status']}"] += 1
        if event == "result_warning" and isinstance(fields.get("warning_code"), str):
            self.metrics[f"warning.{fields['warning_code']}"] += 1
        print(json.dumps(record, ensure_ascii=False, separators=(",", ":")), file=sys.stdout, flush=True)
        return record

    def snapshot(self) -> list[dict[str, Any]]:
        return list(self.events)

    def resize(self, ring_size: int) -> None:
        if ring_size <= 0:
            raise ValueError("event ring size must be positive")
        self.events = deque(self.events, maxlen=ring_size)

    def dashboard_metrics(self) -> dict[str, Any]:
        return {"uptime_seconds": max(0.0, time.monotonic() - self.started_at), "events": dict(self.metrics)}


def _safe_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))
