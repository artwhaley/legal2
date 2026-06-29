"""Live embedding progress for the main window status bar."""

from __future__ import annotations

import json
from typing import Callable

from PySide6.QtCore import QObject, Qt, Signal

from message_evidence_workstation.domain.embedding_state import EmbeddingState
from message_evidence_workstation.logging_ui.log_bus import LogBus


class EmbeddingProgressController(QObject):
    state_changed = Signal(object)

    def __init__(self, log_bus: LogBus, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._state = EmbeddingState()
        self._active_model: str | None = None
        log_bus.entry_added.connect(self._on_log_entry, Qt.ConnectionType.QueuedConnection)

    @property
    def state(self) -> EmbeddingState:
        return self._state

    def set_active_model(self, model_name: str | None) -> None:
        self._active_model = model_name
        self._emit()

    def reset(self) -> None:
        self._state = EmbeddingState()
        self._emit()

    def mark_build_started(self, *, message_total: int = 0, chunk_total: int = 0) -> None:
        self._state.building = True
        if message_total > 0:
            self._state.message_total = message_total
        if chunk_total > 0:
            self._state.chunk_total = chunk_total
        self._emit()

    def refresh_from_db(
        self,
        conn,
        *,
        dataset_id: int | None,
        model_name: str | None,
    ) -> None:
        if dataset_id is None or not model_name:
            self.reset()
            return
        from message_evidence_workstation.embeddings.index_jobs import get_ready_index

        message_row = get_ready_index(conn, dataset_id, "message", model_name)
        chunk_row = get_ready_index(conn, dataset_id, "chunk", model_name)
        message_total = int(
            conn.execute(
                "SELECT COUNT(*) FROM message WHERE dataset_id = ?",
                (dataset_id,),
            ).fetchone()[0]
        )
        self._state.message_ready = message_row is not None
        self._state.chunk_ready = chunk_row is not None
        self._state.message_total = message_total
        self._state.message_progress = int(message_row["message_count"] or 0) if message_row else 0
        self._state.chunk_progress = int(chunk_row["chunk_count"] or 0) if chunk_row else 0
        if chunk_row is not None:
            meta = json.loads(chunk_row["chunking_config_json"] or "{}")
            progress = meta.get("build_progress") or {}
            chunk_total = progress.get("total") or meta.get("chunk_count")
            if chunk_total:
                self._state.chunk_total = int(chunk_total)
        self._state.building = not (self._state.message_ready and self._state.chunk_ready)
        self._active_model = model_name
        self._emit()

    def status_text(self) -> str:
        state = self._state
        if state.message_ready and state.chunk_ready:
            return "Embeddings ready"
        if not state.building and state.message_progress <= 0 and state.chunk_progress <= 0:
            return ""
        message_part = "Message embeddings: n/a"
        chunk_part = "Chunk embeddings: n/a"
        if state.message_total > 0 or state.message_progress > 0:
            total = state.message_total or "?"
            message_part = f"Message embeddings: {state.message_progress} / {total}"
        if state.chunk_total > 0 or state.chunk_progress > 0:
            total = state.chunk_total or "?"
            chunk_part = f"Chunk embeddings: {state.chunk_progress} / {total}"
        return f"{message_part}    |    {chunk_part}"

    def _on_log_entry(self, entry: dict) -> None:
        operation = str(entry.get("operation") or "")
        if operation not in {"message_batch_progress", "chunk_batch_progress"}:
            return
        details = entry.get("details") or entry.get("details_json") or {}
        if not isinstance(details, dict):
            details = {}
        if operation == "message_batch_progress":
            embedded = int(details.get("embedded") or 0)
            total = int(details.get("total") or 0)
            self._state.message_progress = embedded
            if total > 0:
                self._state.message_total = total
            self._state.building = True
        elif operation == "chunk_batch_progress":
            embedded = int(details.get("embedded") or details.get("chunk_count") or 0)
            total = int(details.get("total") or 0)
            self._state.chunk_progress = embedded
            if total > 0:
                self._state.chunk_total = total
            self._state.building = True
        self._emit()

    def _emit(self) -> None:
        self.state_changed.emit(self._state)


def connect_embedding_state(handler: Callable[[EmbeddingState], None], controller: EmbeddingProgressController) -> None:
    controller.state_changed.connect(handler)  # type: ignore[arg-type]
