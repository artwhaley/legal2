"""Demonstrator tab for the virtual transcript widget."""

from __future__ import annotations

import random
import sqlite3

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from message_evidence_workstation.db import repositories
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.ui.virtual_transcript_widget import VirtualTranscriptWidget


class VirtualTranscriptWidgetTab(QWidget):
    evidence_block_created = Signal(int)
    evidence_block_deleted = Signal(int)

    def __init__(
        self,
        conn: sqlite3.Connection,
        logger: ProcessLogger,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.conn = conn
        self.logger = logger
        self.dataset_id: int | None = None
        self._pending_thread_id: str | None = None
        self._thread_loaded = False

        layout = QVBoxLayout(self)
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Source thread"))
        self.thread_combo = QComboBox()
        self.thread_combo.currentIndexChanged.connect(self._on_thread_changed)
        row1.addWidget(self.thread_combo, stretch=1)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        self.jump_50_button = QPushButton("Jump 50")
        self.jump_50_button.clicked.connect(lambda: self._jump_to_ordinal(50))
        row2.addWidget(self.jump_50_button)
        self.jump_500_button = QPushButton("Jump 500")
        self.jump_500_button.clicked.connect(lambda: self._jump_to_ordinal(500))
        row2.addWidget(self.jump_500_button)
        self.jump_14000_button = QPushButton("Jump 14,000")
        self.jump_14000_button.clicked.connect(lambda: self._jump_to_ordinal(14_000))
        row2.addWidget(self.jump_14000_button)
        self.jump_random_button = QPushButton("Jump random")
        self.jump_random_button.clicked.connect(self._jump_random)
        row2.addWidget(self.jump_random_button)
        self.create_viewport_button = QPushButton("Create at viewport center")
        self.create_viewport_button.clicked.connect(self._create_from_viewport)
        row2.addWidget(self.create_viewport_button)
        self.delete_viewport_button = QPushButton("Delete block at center")
        self.delete_viewport_button.clicked.connect(self._delete_at_viewport)
        row2.addWidget(self.delete_viewport_button)
        self.create_random_button = QPushButton("Create at random message")
        self.create_random_button.clicked.connect(self._create_at_random)
        row2.addWidget(self.create_random_button)
        self.reveal_button = QPushButton("Reveal active block")
        self.reveal_button.clicked.connect(self._reveal_active)
        row2.addWidget(self.reveal_button)
        self.reload_button = QPushButton("Reload thread")
        self.reload_button.clicked.connect(self._reload_thread)
        row2.addWidget(self.reload_button)
        row2.addStretch()
        layout.addLayout(row2)

        self.status_label = QLabel("No dataset loaded.")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.transcript_widget = VirtualTranscriptWidget(conn, logger, self)
        self.transcript_widget.thread_loaded.connect(
            lambda _thread_id, _count: self._update_status(last_action="thread loaded")
        )
        self.transcript_widget.evidence_block_created.connect(self.evidence_block_created.emit)
        self.transcript_widget.evidence_block_deleted.connect(self.evidence_block_deleted.emit)
        self.transcript_widget.active_block_changed.connect(
            lambda _block_id: self._update_status(last_action="active block changed")
        )
        self.transcript_widget.status_changed.connect(
            lambda: self._update_status(last_action="state updated")
        )
        layout.addWidget(self.transcript_widget, stretch=1)
        self._set_controls_enabled(False)

    def set_dataset(self, dataset_id: int | None) -> None:
        self.dataset_id = dataset_id
        self._thread_loaded = False
        self._pending_thread_id = None
        self.transcript_widget.set_dataset(dataset_id)
        self.thread_combo.blockSignals(True)
        self.thread_combo.clear()
        self.thread_combo.blockSignals(False)
        if dataset_id is None:
            self._set_controls_enabled(False)
            self._update_status(last_action="dataset cleared")
            return
        threads = repositories.list_source_threads(self.conn, dataset_id)
        self.thread_combo.blockSignals(True)
        for thread in threads:
            label = f"{thread.display_title} ({thread.source_thread_id})"
            self.thread_combo.addItem(label, thread.source_thread_id)
        self.thread_combo.blockSignals(False)
        self._set_controls_enabled(True)
        if threads:
            self._pending_thread_id = threads[0].source_thread_id
            self.thread_combo.setCurrentIndex(0)
            self._update_status(last_action="thread pending (open tab to load)")
        else:
            self._update_status(last_action="no threads")

    def ensure_thread_loaded(self) -> None:
        if self.dataset_id is None or self._thread_loaded:
            return
        thread_id = self._pending_thread_id
        if thread_id is None:
            thread_id = self.thread_combo.currentData(Qt.ItemDataRole.UserRole)
        if not isinstance(thread_id, str):
            return
        self.transcript_widget.load_source_thread(thread_id)
        self._thread_loaded = True
        self._pending_thread_id = thread_id
        self._update_status(last_action="thread loaded")

    def select_source_thread(self, source_thread_id: str) -> None:
        index = self.thread_combo.findData(source_thread_id, role=Qt.ItemDataRole.UserRole)
        if index >= 0:
            self.thread_combo.blockSignals(True)
            self.thread_combo.setCurrentIndex(index)
            self.thread_combo.blockSignals(False)
            self._pending_thread_id = source_thread_id
            self._thread_loaded = False
            if self.isVisible():
                self.ensure_thread_loaded()

    def _on_thread_changed(self, row: int) -> None:
        if row < 0:
            return
        source_thread_id = self.thread_combo.currentData(Qt.ItemDataRole.UserRole)
        if isinstance(source_thread_id, str):
            self._pending_thread_id = source_thread_id
            self._thread_loaded = False
            self.transcript_widget.load_source_thread(source_thread_id)
            self._thread_loaded = True
            self._update_status(last_action="thread changed")

    def _jump_to_ordinal(self, ordinal: int) -> None:
        self.ensure_thread_loaded()
        count = self.transcript_widget.message_count
        target = min(ordinal, max(0, count - 1)) if count else 0
        self.transcript_widget.scroll_to_ordinal(target)
        self._update_status(last_action=f"jump ordinal {target}")

    def _jump_random(self) -> None:
        self.ensure_thread_loaded()
        count = self.transcript_widget.message_count
        if count <= 0:
            return
        target = random.randint(0, count - 1)
        self.transcript_widget.scroll_to_ordinal(target)
        self._update_status(last_action=f"jump random {target}")

    def _create_from_viewport(self) -> None:
        self.ensure_thread_loaded()
        block = self.transcript_widget.create_evidence_block_from_viewport_center(
            source_action="viewport_button",
        )
        if block is not None:
            self._update_status(last_action=f"created block {block.evidence_block_id}")

    def _delete_at_viewport(self) -> None:
        self.ensure_thread_loaded()
        self.transcript_widget.prompt_delete_evidence_block_at_viewport_center()
        self._update_status(last_action="delete block at center")

    def _create_at_random(self) -> None:
        self.ensure_thread_loaded()
        count = self.transcript_widget.message_count
        if count <= 0:
            return
        ordinal = random.randint(0, count - 1)
        message_id = self.transcript_widget.model.message_id_for_ordinal(ordinal)
        if message_id is None:
            return
        self.transcript_widget.scroll_to_ordinal(ordinal)
        block = self.transcript_widget.create_evidence_block_for_message(
            message_id,
            source_action="random_create",
        )
        if block is not None:
            self._update_status(last_action=f"created block {block.evidence_block_id} at {ordinal}")

    def _reveal_active(self) -> None:
        self.ensure_thread_loaded()
        self.transcript_widget.reveal_active_evidence_block()
        self._update_status(last_action="reveal active block")

    def _reload_thread(self) -> None:
        self.ensure_thread_loaded()
        self.transcript_widget.reload_current_thread()
        self._update_status(last_action="reload thread")

    def reveal_evidence_block(self, evidence_block_id: int) -> None:
        self.ensure_thread_loaded()
        self.transcript_widget.select_evidence_block(evidence_block_id)
        self._update_status(last_action=f"revealed block {evidence_block_id}")

    def hide_evidence_block(self, evidence_block_id: int) -> None:
        self.ensure_thread_loaded()
        self.transcript_widget.hide_evidence_block(evidence_block_id)
        self._update_status(last_action=f"hid block {evidence_block_id}")

    def show_evidence_block(self, evidence_block_id: int) -> None:
        self.ensure_thread_loaded()
        self.transcript_widget.show_evidence_block(evidence_block_id)
        self._update_status(last_action=f"showed block {evidence_block_id}")

    def is_evidence_block_hidden(self, evidence_block_id: int) -> bool:
        return self.transcript_widget.is_evidence_block_hidden(evidence_block_id)

    def _set_controls_enabled(self, enabled: bool) -> None:
        for widget in (
            self.jump_50_button,
            self.jump_500_button,
            self.jump_14000_button,
            self.jump_random_button,
            self.create_viewport_button,
            self.delete_viewport_button,
            self.create_random_button,
            self.reveal_button,
            self.reload_button,
        ):
            widget.setEnabled(enabled)

    def _update_status(self, *, last_action: str) -> None:
        thread_id = self.transcript_widget.source_thread_id or "—"
        message_count = self.transcript_widget.message_count
        visible_start, visible_end = self.transcript_widget.visible_ordinal_range
        cached = self.transcript_widget.cached_message_count
        measured = self.transcript_widget.measured_height_count
        active = self.transcript_widget.active_evidence_block_id
        active_label = str(active) if active is not None else "—"
        self.status_label.setText(
            f"Thread: {thread_id} | Messages: {message_count:,} | "
            f"Visible: {visible_start:,}-{visible_end:,} | "
            f"Cache: {cached:,} | Measured heights: {measured:,} | "
            f"Active block: {active_label} | Last action: {last_action}"
        )
