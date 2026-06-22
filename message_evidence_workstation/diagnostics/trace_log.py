"""Synchronous file trace log for crash diagnosis (no Qt)."""

from __future__ import annotations

import atexit
import faulthandler
import json
import sys
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from message_evidence_workstation.config.paths import workspace_dir

_TRACE_PATH = workspace_dir() / "crash_trace.log"
_ENABLED = False
_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def trace(component: str, operation: str, message: str = "", **details: Any) -> None:
    global _ENABLED
    if not _ENABLED:
        return
    line = {
        "ts": _now(),
        "thread": threading.current_thread().name,
        "component": component,
        "operation": operation,
        "message": message,
        "details": details,
    }
    payload = json.dumps(line, ensure_ascii=True, default=str)
    with _LOCK:
        _TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _TRACE_PATH.open("a", encoding="utf-8") as handle:
            handle.write(payload + "\n")
            handle.flush()


def install_diagnostics(*, clear_log: bool = True) -> Path:
    """Enable faulthandler + excepthooks + file trace. Call once at app startup."""
    global _ENABLED
    _TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if clear_log:
        _TRACE_PATH.write_text("", encoding="utf-8")
    _ENABLED = True

    fault_file = _TRACE_PATH.with_name("crash_faulthandler.log")
    fault_handle = fault_file.open("a", encoding="utf-8")
    faulthandler.enable(file=fault_handle, all_threads=True)

    def _excepthook(exc_type, exc, tb) -> None:
        trace(
            "diagnostics",
            "unhandled_exception",
            "".join(traceback.format_exception(exc_type, exc, tb)),
        )
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = _excepthook

    if hasattr(threading, "excepthook"):

        def _thread_excepthook(args: threading.ExceptHookArgs) -> None:
            trace(
                "diagnostics",
                "unhandled_thread_exception",
                "".join(
                    traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)
                ),
                thread=args.thread.name if args.thread else "",
            )

        threading.excepthook = _thread_excepthook

    trace("diagnostics", "installed", path=str(_TRACE_PATH), python=sys.version)
    atexit.register(lambda: trace("diagnostics", "process_exit"))
    return _TRACE_PATH


def trace_path() -> Path:
    return _TRACE_PATH
