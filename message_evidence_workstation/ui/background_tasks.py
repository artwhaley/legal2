"""Run blocking work off the Qt UI thread."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TypeVar

from PySide6.QtCore import QObject, Signal, Slot

T = TypeVar("T")

_shutdown_requested: bool = False
_shutdown_lock = threading.Lock()


def request_shutdown() -> None:
    """Signal all background runners to skip new work."""
    global _shutdown_requested
    with _shutdown_lock:
        _shutdown_requested = True


def _check_shutdown() -> bool:
    with _shutdown_lock:
        return _shutdown_requested


class _JobBridge(QObject):
    """Marshals worker-thread results onto the QObject owner thread (UI)."""

    succeeded = Signal(object)
    errored = Signal(object)

    @Slot(object)
    def accept_success(self, result: object) -> None:
        self.succeeded.emit(result)

    @Slot(object)
    def accept_error(self, exc: object) -> None:
        self.errored.emit(exc)


def run_background(
    parent: QObject | None,
    fn: Callable[[], T],
    *,
    on_success: Callable[[T], None],
    on_error: Callable[[BaseException], None],
) -> threading.Thread:
    """Execute ``fn`` on a daemon thread; run callbacks on the UI thread.

    If :func:`request_shutdown` has been called the work is skipped and a
    :class:`RuntimeError` is delivered to ``on_error`` immediately.
    """
    if parent is None:
        raise ValueError("run_background requires a QObject parent for UI-thread delivery")

    if _check_shutdown():
        thread = threading.Thread(target=lambda: None, name="mew-background-skipped", daemon=True)
        thread.start()
        resolved_error = RuntimeError("Background work skipped: shutdown requested")
        from message_evidence_workstation.ui.ui_callback_watchdog import run_ui_callback

        run_ui_callback(
            "background_tasks.on_error",
            lambda: on_error(resolved_error),  # type: ignore[arg-type]
        )
        return thread

    bridge = _JobBridge(parent)

    def on_bridge_success(result: object) -> None:
        from message_evidence_workstation.ui.ui_callback_watchdog import run_ui_callback

        bridge.succeeded.disconnect(on_bridge_success)
        bridge.errored.disconnect(on_bridge_error)
        run_ui_callback("background_tasks.on_success", lambda: on_success(result))  # type: ignore[arg-type]

    def on_bridge_error(exc: object) -> None:
        from message_evidence_workstation.ui.ui_callback_watchdog import run_ui_callback

        bridge.succeeded.disconnect(on_bridge_success)
        bridge.errored.disconnect(on_bridge_error)
        resolved = exc if isinstance(exc, BaseException) else RuntimeError(str(exc))
        run_ui_callback("background_tasks.on_error", lambda: on_error(resolved))

    bridge.succeeded.connect(on_bridge_success)
    bridge.errored.connect(on_bridge_error)

    def runner() -> None:
        if _check_shutdown():
            bridge.errored.emit(RuntimeError("Background work skipped: shutdown requested"))
            return
        try:
            result = fn()
            bridge.succeeded.emit(result)
        except Exception as exc:
            bridge.errored.emit(exc)

    thread = threading.Thread(target=runner, name="mew-background", daemon=True)
    thread.start()
    return thread
