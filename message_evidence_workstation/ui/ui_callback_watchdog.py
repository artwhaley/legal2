"""Guard against blocking the Qt UI thread in background job callbacks."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")

UI_CALLBACK_WARN_SECONDS = 0.1
UI_CALLBACK_ASSERT_SECONDS = 0.05


def _strict_callbacks() -> bool:
    return os.environ.get("MEW_STRICT_UI_CALLBACKS", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def run_ui_callback(label: str, callback: Callable[[], T]) -> T:
    """Run a UI-thread callback and warn or assert if it blocks too long."""
    started = time.perf_counter()
    try:
        return callback()
    finally:
        elapsed = time.perf_counter() - started
        if elapsed <= UI_CALLBACK_WARN_SECONDS:
            pass
        else:
            message = f"{label} blocked UI thread for {elapsed:.3f}s"
            if _strict_callbacks() or elapsed > 1.0:
                raise AssertionError(message)
            import logging

            logging.getLogger("message_evidence_workstation.ui").warning(message)
