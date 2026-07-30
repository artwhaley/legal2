"""Rotating JSONL diagnostics for metadata-only client events."""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)


_MAX_FILES = 5
_MAX_BYTES = 10 * 1024 * 1024  # 10 MiB


class RotatingJsonlDiagnostics:
    """External metadata-only rotating JSONL diagnostic log.

    Never stores transcript text, query bodies, prompt bodies,
    response bodies, embeddings, or provider payloads.
    """

    def __init__(self, directory: Path, prefix: str = "diag") -> None:
        self._directory = directory
        self._directory.mkdir(parents=True, exist_ok=True)
        self._prefix = prefix
        self._lock = threading.Lock()
        self._current_path = self._next_path()

    def _next_path(self) -> Path:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        return self._directory / f"{self._prefix}_{ts}.jsonl"

    def _rotate(self) -> None:
        """Keep at most _MAX_FILES files, deleting oldest beyond that."""
        files = sorted(self._directory.glob(f"{self._prefix}_*.jsonl"))
        while len(files) > _MAX_FILES:
            files[0].unlink(missing_ok=True)
            files = files[1:]

    def _current_size(self) -> int:
        try:
            return self._current_path.stat().st_size
        except FileNotFoundError:
            return 0

    def write(
        self,
        entry: dict[str, Any],
    ) -> None:
        with self._lock:
            if self._current_size() >= _MAX_BYTES:
                self._current_path = self._next_path()
                self._rotate()
            line = json.dumps(entry, ensure_ascii=True, default=str)
            with self._current_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()

    def write_event(
        self,
        component: str,
        operation: str,
        message: str,
        *,
        severity: str = "info",
        details: dict[str, Any] | None = None,
    ) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "severity": severity,
            "component": component,
            "operation": operation,
            "message": message,
        }
        if details:
            entry["details"] = details
        self.write(entry)

    def write_error(
        self,
        component: str,
        operation: str,
        message: str,
        exc: BaseException | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        entry: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "severity": "error",
            "component": component,
            "operation": operation,
            "message": message,
        }
        if exc is not None:
            entry["error_type"] = type(exc).__name__
            entry["error_message"] = str(exc)
        if details:
            entry["details"] = details
        self.write(entry)

_instance: RotatingJsonlDiagnostics | None = None
_lock = threading.Lock()


def get_diagnostics(directory: Path | None = None) -> RotatingJsonlDiagnostics:
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                from message_evidence_workstation.config.paths import workspace_dir

                d = directory or (workspace_dir() / "logs")
                _instance = RotatingJsonlDiagnostics(d)
    return _instance
