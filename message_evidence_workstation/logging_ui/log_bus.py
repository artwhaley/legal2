"""In-process log event bus for UI subscription."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, Signal


class LogBus(QObject):
    """Qt signal bus for live process log entries."""

    entry_added = Signal(dict)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._listeners: list[Callable[[dict[str, Any]], None]] = []

    def subscribe(self, listener: Callable[[dict[str, Any]], None]) -> None:
        from PySide6.QtCore import Qt

        self._listeners.append(listener)
        self.entry_added.connect(listener, Qt.ConnectionType.QueuedConnection)

    def publish(self, entry: dict[str, Any]) -> None:
        # Always deliver via Qt signal so UI slots run on the main thread.
        self.entry_added.emit(entry)


_log_bus: LogBus | None = None


def get_log_bus() -> LogBus:
    global _log_bus
    if _log_bus is None:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        _log_bus = LogBus(app) if app is not None else LogBus()
    return _log_bus
