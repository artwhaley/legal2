"""Run blocking work off the Qt UI thread."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TypeVar

from PySide6.QtCore import QObject, QTimer, Signal, Slot

T = TypeVar("T")


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
    """Execute ``fn`` on a daemon thread; run callbacks on the UI thread."""
    if parent is None:
        raise ValueError("run_background requires a QObject parent for UI-thread delivery")

    bridge = _JobBridge(parent)

    def on_bridge_success(result: object) -> None:
        bridge.succeeded.disconnect(on_bridge_success)
        bridge.errored.disconnect(on_bridge_error)
        on_success(result)  # type: ignore[arg-type]

    def on_bridge_error(exc: object) -> None:
        bridge.succeeded.disconnect(on_bridge_success)
        bridge.errored.disconnect(on_bridge_error)
        on_error(exc if isinstance(exc, BaseException) else RuntimeError(str(exc)))

    bridge.succeeded.connect(on_bridge_success)
    bridge.errored.connect(on_bridge_error)

    def runner() -> None:
        try:
            result = fn()

            def deliver_success(r: object = result) -> None:
                bridge.accept_success(r)

            QTimer.singleShot(0, parent, deliver_success)
        except BaseException as exc:

            def deliver_error(e: BaseException = exc) -> None:
                bridge.accept_error(e)

            QTimer.singleShot(0, parent, deliver_error)

    thread = threading.Thread(target=runner, name="mew-background", daemon=True)
    thread.start()
    return thread
