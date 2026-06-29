"""Persistent process log service."""

from __future__ import annotations

import json
import sqlite3
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
from message_evidence_workstation.domain.models import ProcessLogEntry
from message_evidence_workstation.logging_ui.log_bus import LogBus, get_log_bus

_USE_DEFAULT_LOG_BUS = object()
DEFAULT_BATCH_FLUSH_EVERY = 25


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class ProcessLogBatch:
    """Deferred process-log writer for long-running jobs."""

    def __init__(
        self,
        logger: "ProcessLogger",
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
    ) -> ProcessLogEntry:
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
        if self._logger._process_log_table_ready():
            for item in self._pending:
                entry = item["entry"]
                cursor = self._logger.conn.execute(
                    """
                    INSERT INTO process_log (
                        dataset_id, timestamp, severity, component, operation, message,
                        details_json, exception_type, stack_trace
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entry.dataset_id,
                        entry.timestamp,
                        entry.severity,
                        entry.component,
                        entry.operation,
                        entry.message,
                        json.dumps(entry.details_json),
                        entry.exception_type,
                        entry.stack_trace,
                    ),
                )
                entry.process_log_id = int(cursor.lastrowid)
            self._logger.conn.commit()
        for item in self._pending:
            if item["publish_live"] and self._logger.log_bus is not None:
                entry = item["entry"]
                self._logger.log_bus.publish(
                    {
                        "process_log_id": entry.process_log_id,
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

    def debug(self, component: str, operation: str, message: str, **kwargs: Any) -> ProcessLogEntry:
        return self._enqueue(SEVERITY_DEBUG, component, operation, message, **kwargs)

    def info(self, component: str, operation: str, message: str, **kwargs: Any) -> ProcessLogEntry:
        return self._enqueue(SEVERITY_INFO, component, operation, message, **kwargs)

    def warning(self, component: str, operation: str, message: str, **kwargs: Any) -> ProcessLogEntry:
        return self._enqueue(SEVERITY_WARNING, component, operation, message, **kwargs)

    def error(self, component: str, operation: str, message: str, **kwargs: Any) -> ProcessLogEntry:
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
    ) -> ProcessLogEntry:
        return self.info(
            component,
            operation,
            message,
            details=details,
            dataset_id=dataset_id,
        )


class ProcessLogger:
    def __init__(
        self,
        conn: sqlite3.Connection,
        log_bus: LogBus | None | object = _USE_DEFAULT_LOG_BUS,
        dataset_id: int | None = None,
    ) -> None:
        self.conn = conn
        if log_bus is _USE_DEFAULT_LOG_BUS:
            self.log_bus = get_log_bus()
        else:
            self.log_bus = log_bus  # type: ignore[assignment]
        self.dataset_id = dataset_id

    def _process_log_table_ready(self) -> bool:
        row = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'process_log'"
        ).fetchone()
        return row is not None

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
    ) -> ProcessLogEntry:
        exception_type = type(exc).__name__ if exc else None
        stack_trace = "".join(traceback.format_exception(exc)) if exc else None
        details_json = details or {}
        if exc and "error" not in details_json:
            details_json = {**details_json, "error": str(exc)}
        effective_dataset_id = dataset_id if dataset_id is not None else self.dataset_id
        return ProcessLogEntry(
            process_log_id=0,
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
    ) -> ProcessLogEntry:
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

        if self._process_log_table_ready():
            cursor = self.conn.execute(
                """
                INSERT INTO process_log (
                    dataset_id, timestamp, severity, component, operation, message,
                    details_json, exception_type, stack_trace
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.dataset_id,
                    entry.timestamp,
                    entry.severity,
                    entry.component,
                    entry.operation,
                    entry.message,
                    json.dumps(entry.details_json),
                    entry.exception_type,
                    entry.stack_trace,
                ),
            )
            self.conn.commit()
            entry.process_log_id = int(cursor.lastrowid)

        payload = {
            "process_log_id": entry.process_log_id,
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
    def batch(self, *, auto_flush_every: int = DEFAULT_BATCH_FLUSH_EVERY) -> Iterator[ProcessLogBatch]:
        batch_logger = ProcessLogBatch(self, auto_flush_every=auto_flush_every)
        try:
            yield batch_logger
        except BaseException:
            batch_logger.flush()
            raise
        else:
            batch_logger.flush()

    def debug(self, component: str, operation: str, message: str, **kwargs: Any) -> ProcessLogEntry:
        return self.log(SEVERITY_DEBUG, component, operation, message, **kwargs)

    def info(self, component: str, operation: str, message: str, **kwargs: Any) -> ProcessLogEntry:
        return self.log(SEVERITY_INFO, component, operation, message, **kwargs)

    def warning(self, component: str, operation: str, message: str, **kwargs: Any) -> ProcessLogEntry:
        return self.log(SEVERITY_WARNING, component, operation, message, **kwargs)

    def error(self, component: str, operation: str, message: str, **kwargs: Any) -> ProcessLogEntry:
        return self.log(SEVERITY_ERROR, component, operation, message, **kwargs)


def fetch_process_logs(
    conn: sqlite3.Connection,
    *,
    severity: str | None = None,
    component: str | None = None,
    limit: int = 500,
) -> list[ProcessLogEntry]:
    clauses: list[str] = []
    params: list[Any] = []
    if severity:
        clauses.append("severity = ?")
        params.append(severity)
    if component:
        clauses.append("component = ?")
        params.append(component)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"""
        SELECT process_log_id, dataset_id, timestamp, severity, component, operation,
               message, details_json, exception_type, stack_trace
        FROM process_log
        {where}
        ORDER BY process_log_id DESC
        LIMIT ?
        """,
        (*params, limit),
    ).fetchall()
    entries: list[ProcessLogEntry] = []
    for row in rows:
        details_raw = row["details_json"]
        details = json.loads(details_raw) if details_raw else {}
        entries.append(
            ProcessLogEntry(
                process_log_id=row["process_log_id"],
                dataset_id=row["dataset_id"],
                timestamp=row["timestamp"],
                severity=row["severity"],
                component=row["component"],
                operation=row["operation"],
                message=row["message"],
                details_json=details,
                exception_type=row["exception_type"],
                stack_trace=row["stack_trace"],
            )
        )
    return list(reversed(entries))
