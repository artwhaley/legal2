"""Diagnostic event service — uses rotating JSONL and in-memory event bus.

Replaces DB persistence with metadata-only rotating JSONL diagnostics.
"""

from __future__ import annotations

import traceback
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from message_evidence_workstation.domain.constants import (
    SEVERITY_DEBUG,
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARNING,
)
from message_evidence_workstation.domain.models import DiagnosticEntry
from message_evidence_workstation.logging_ui.log_bus import LogBus, get_log_bus
from message_evidence_workstation.diagnostics.rotating_log import get_diagnostics

_USE_DEFAULT_LOG_BUS = object()
DEFAULT_BATCH_FLUSH_EVERY = 25


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class DiagnosticBatch:
    """Deferred diagnostic writer for long-running jobs."""

    def __init__(
        self,
        logger: "DiagnosticLogger",
        *,
        auto_flush_every: int = DEFAULT_BATCH_FLUSH_EVERY,
    ) -> None:
        self._logger = logger
        self._auto_flush_every = max(1, auto_flush_every)
        self._pending: list[dict[str, Any]] = []

    def _enqueue(
        self,
        severity: str,
        component: str,
        operation: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        exc: BaseException | None = None,
        dataset_id: int | None = None,
        publish_live: bool = True,
    ) -> DiagnosticEntry:
        entry = self._logger._build_entry(
            severity,
            component,
            operation,
            message,
            details=details,
            exc=exc,
            dataset_id=dataset_id,
        )
        self._pending.append(
            {
                "entry": entry,
                "publish_live": publish_live,
            }
        )
        if len(self._pending) >= self._auto_flush_every:
            self.flush()
        return entry

    def flush(self) -> None:
        if not self._pending:
            return
        for item in self._pending:
            entry = item["entry"]
            _write_to_jsonl(entry)
        for item in self._pending:
            if item["publish_live"] and self._logger.log_bus is not None:
                entry = item["entry"]
                self._logger.log_bus.publish(
                    {
                        "event_id": entry.event_id,
                        "dataset_id": entry.dataset_id,
                        "timestamp": entry.timestamp,
                        "severity": entry.severity,
                        "component": entry.component,
                        "operation": entry.operation,
                        "message": entry.message,
                        "details_json": entry.details_json,
                        "exception_type": entry.exception_type,
                        "stack_trace": entry.stack_trace,
                        "operation_id": str(uuid.uuid4()),
                    }
                )
        self._pending.clear()

    def debug(self, component: str, operation: str, message: str, **kwargs: Any) -> DiagnosticEntry:
        return self._enqueue(SEVERITY_DEBUG, component, operation, message, **kwargs)

    def info(self, component: str, operation: str, message: str, **kwargs: Any) -> DiagnosticEntry:
        return self._enqueue(SEVERITY_INFO, component, operation, message, **kwargs)

    def warning(self, component: str, operation: str, message: str, **kwargs: Any) -> DiagnosticEntry:
        return self._enqueue(SEVERITY_WARNING, component, operation, message, **kwargs)

    def error(self, component: str, operation: str, message: str, **kwargs: Any) -> DiagnosticEntry:
        self.flush()
        return self._logger.error(component, operation, message, **kwargs)

    def summary(
        self,
        component: str,
        operation: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        dataset_id: int | None = None,
    ) -> DiagnosticEntry:
        return self.info(
            component,
            operation,
            message,
            details=details,
            dataset_id=dataset_id,
        )


def _write_to_jsonl(entry: DiagnosticEntry) -> None:
    diag = get_diagnostics()
    if entry.exception_type:
        diag.write_error(
            component=entry.component,
            operation=entry.operation,
            message=entry.message,
            details={
                "dataset_id": entry.dataset_id,
                "severity": entry.severity,
                **entry.details_json,
            },
        )
    else:
        diag.write_event(
            component=entry.component,
            operation=entry.operation,
            message=entry.message,
            severity=entry.severity,
            details={
                "dataset_id": entry.dataset_id,
                **entry.details_json,
            },
        )


class DiagnosticLogger:
    """Diagnostic eventger — writes to rotating JSONL + in-memory event bus.

    Diagnostics are external metadata-only JSONL events. They are not EVW
    records and never include transcript, prompt, response, or embedding data.
    """

    def __init__(
        self,
        log_bus: LogBus | None | object = _USE_DEFAULT_LOG_BUS,
        dataset_id: int | None = None,
    ) -> None:
        if log_bus is _USE_DEFAULT_LOG_BUS:
            self.log_bus = get_log_bus()
        else:
            self.log_bus = log_bus  # type: ignore[assignment]
        self.dataset_id = dataset_id

    def _build_entry(
        self,
        severity: str,
        component: str,
        operation: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        exc: BaseException | None = None,
        dataset_id: int | None = None,
    ) -> DiagnosticEntry:
        exception_type = type(exc).__name__ if exc else None
        stack_trace = "".join(traceback.format_exception(exc)) if exc else None
        details_json = details or {}
        if exc and "error" not in details_json:
            details_json = {**details_json, "error": str(exc)}
        effective_dataset_id = dataset_id if dataset_id is not None else self.dataset_id
        return DiagnosticEntry(
            event_id=0,
            dataset_id=effective_dataset_id,
            timestamp=utc_now_iso(),
            severity=severity,
            component=component,
            operation=operation,
            message=message,
            details_json=details_json,
            exception_type=exception_type,
            stack_trace=stack_trace,
        )

    def log(
        self,
        severity: str,
        component: str,
        operation: str,
        message: str,
        details: dict[str, Any] | None = None,
        exc: BaseException | None = None,
        dataset_id: int | None = None,
        publish_live: bool = True,
    ) -> DiagnosticEntry:
        entry = self._build_entry(
            severity,
            component,
            operation,
            message,
            details=details,
            exc=exc,
            dataset_id=dataset_id,
        )
        operation_id = str(uuid.uuid4())

        _write_to_jsonl(entry)

        payload = {
            "event_id": entry.event_id,
            "dataset_id": entry.dataset_id,
            "timestamp": entry.timestamp,
            "severity": entry.severity,
            "component": entry.component,
            "operation": entry.operation,
            "message": entry.message,
            "details_json": entry.details_json,
            "exception_type": entry.exception_type,
            "stack_trace": entry.stack_trace,
            "operation_id": operation_id,
        }
        if publish_live and self.log_bus is not None:
            self.log_bus.publish(payload)
        return entry

    @contextmanager
    def batch(self, *, auto_flush_every: int = DEFAULT_BATCH_FLUSH_EVERY) -> Iterator[DiagnosticBatch]:
        batch_logger = DiagnosticBatch(self, auto_flush_every=auto_flush_every)
        try:
            yield batch_logger
        except BaseException:
            batch_logger.flush()
            raise
        else:
            batch_logger.flush()

    def debug(self, component: str, operation: str, message: str, **kwargs: Any) -> DiagnosticEntry:
        return self.log(SEVERITY_DEBUG, component, operation, message, **kwargs)

    def info(self, component: str, operation: str, message: str, **kwargs: Any) -> DiagnosticEntry:
        return self.log(SEVERITY_INFO, component, operation, message, **kwargs)

    def warning(self, component: str, operation: str, message: str, **kwargs: Any) -> DiagnosticEntry:
        return self.log(SEVERITY_WARNING, component, operation, message, **kwargs)

    def error(self, component: str, operation: str, message: str, **kwargs: Any) -> DiagnosticEntry:
        return self.log(SEVERITY_ERROR, component, operation, message, **kwargs)


def fetch_diagnostic_events(
    conn: object = None,
    *,
    severity: str | None = None,
    component: str | None = None,
    limit: int = 500,
) -> list[DiagnosticEntry]:
    """Return empty — diagnostic events are now external JSONL files."""
    return []
