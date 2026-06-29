"""Parallel demonstrator tab for the document-backed transcript widget."""

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

from message_evidence_workstation.db import evidence_blocks, repositories
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.ui.new_transcript_widget import NewTranscriptWidget


class NewTranscriptWidgetTab(QWidget):
    evidence_block_created = Signal(int)

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

        layout = QVBoxLayout(self)
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Source thread"))
        self.thread_combo = QComboBox()
        self.thread_combo.currentIndexChanged.connect(self._on_thread_changed)
        row1.addWidget(self.thread_combo, stretch=1)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        self.new_block_button = QPushButton("New evidence block")
        self.new_block_button.clicked.connect(self._create_from_viewport)
        row2.addWidget(self.new_block_button)

        self.jump_50_button = QPushButton("Jump 50")
        self.jump_50_button.clicked.connect(lambda: self._jump_to_ordinal(50))
        row2.addWidget(self.jump_50_button)

        self.jump_500_button = QPushButton("Jump 500")
        self.jump_500_button.clicked.connect(lambda: self._jump_to_ordinal(500))
        row2.addWidget(self.jump_500_button)

        self.jump_random_button = QPushButton("Jump random + create block")
        self.jump_random_button.clicked.connect(self._jump_random_and_create)
        row2.addWidget(self.jump_random_button)

        self.persist_reload_button = QPushButton("Persist / reload current thread")
        self.persist_reload_button.clicked.connect(self._persist_reload)
        row2.addWidget(self.persist_reload_button)
        row2.addStretch()
        layout.addLayout(row2)

        self.status_label = QLabel("No dataset loaded.")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.transcript_widget = NewTranscriptWidget(conn, logger, self)
        self._pending_thread_id: str | None = None
        self._thread_document_loaded = False
        self.transcript_widget.load_progress.connect(self._on_load_progress)
        self.transcript_widget.thread_loaded.connect(
            lambda _thread_id, _count: self._update_status(last_action="thread loaded")
        )
        self.transcript_widget.evidence_block_created.connect(self.evidence_block_created.emit)
        self.transcript_widget.active_block_changed.connect(
            lambda _block_id: self._update_status(last_action="active block changed")
        )
        layout.addWidget(self.transcript_widget, stretch=1)

    def _on_load_progress(self, message: str) -> None:
        self.status_label.setText(message)

    def set_dataset(self, dataset_id: int | None) -> None:
        self.dataset_id = dataset_id
        self._thread_document_loaded = False
        self._pending_thread_id = None
        self.transcript_widget.set_dataset(dataset_id)
        enabled = dataset_id is not None
        self.new_block_button.setEnabled(enabled)
        self.jump_50_button.setEnabled(enabled)
        self.jump_500_button.setEnabled(enabled)
        self.jump_random_button.setEnabled(enabled)
        self.persist_reload_button.setEnabled(enabled)
        self.thread_combo.blockSignals(True)
        self.thread_combo.clear()
        self.thread_combo.blockSignals(False)
        if dataset_id is None:
            self._update_status(last_action="dataset cleared")
            return

        threads = repositories.list_source_threads(self.conn, dataset_id)
        self.thread_combo.blockSignals(True)
        for thread in threads:
            label = f"{thread.display_title} ({thread.source_thread_id})"
            self.thread_combo.addItem(label, thread.source_thread_id)
        self.thread_combo.blockSignals(False)
        if threads:
            self._pending_thread_id = threads[0].source_thread_id
            self.thread_combo.setCurrentIndex(0)
            self._update_status(last_action="thread pending (open tab to load)")
        else:
            self._update_status(last_action="no threads")

    def ensure_document_loaded(self) -> None:
        if self.dataset_id is None or self._thread_document_loaded:
            return
        thread_id = self._pending_thread_id
        if thread_id is None:
            thread_id = self.thread_combo.currentData(Qt.ItemDataRole.UserRole)
        if not isinstance(thread_id, str):
            return
        self.status_label.setText(f"Loading transcript document for {thread_id}…")
        self.transcript_widget.load_source_thread(thread_id)
        self._thread_document_loaded = True
        self._pending_thread_id = thread_id
        self._update_status(last_action="thread loaded")

    def select_source_thread(self, source_thread_id: str) -> None:
        index = self.thread_combo.findData(source_thread_id, role=Qt.ItemDataRole.UserRole)
        if index >= 0:
            self.thread_combo.blockSignals(True)
            self.thread_combo.setCurrentIndex(index)
            self.thread_combo.blockSignals(False)
            self._pending_thread_id = source_thread_id
            self._thread_document_loaded = False
            if self.isVisible():
                self.ensure_document_loaded()

    def _on_thread_changed(self, row: int) -> None:
        if row < 0:
            return
        source_thread_id = self.thread_combo.currentData(Qt.ItemDataRole.UserRole)
        if isinstance(source_thread_id, str):
            self._pending_thread_id = source_thread_id
            self._thread_document_loaded = False
            self.transcript_widget.load_source_thread(source_thread_id)
            self._thread_document_loaded = True
            self._update_status(last_action="thread changed")

    def _create_from_viewport(self) -> None:
        self.ensure_document_loaded()
        block = self.transcript_widget.create_evidence_block_from_viewport_center(
            source_action="viewport_button",
        )
        if block is not None:
            self._update_status(last_action=f"created block {block.evidence_block_id}")

    def _jump_to_ordinal(self, ordinal: int) -> None:
        self.ensure_document_loaded()
        count = self.transcript_widget.message_count
        target = min(ordinal, max(0, count - 1)) if count else 0
        self.transcript_widget.scroll_to_ordinal(target)
        self._update_status(last_action=f"jump ordinal {target}")

    def _jump_random_and_create(self) -> None:
        self.ensure_document_loaded()
        count = self.transcript_widget.message_count
        if count <= 0:
            return
        ordinal = random.randint(0, count - 1)
        message_id = self.transcript_widget.thread_ordinal_to_message_id.get(ordinal)
        if message_id is None:
            return
        self.transcript_widget.scroll_to_ordinal(ordinal)
        block = self.transcript_widget.create_evidence_block_for_message(
            message_id,
            source_action="jump_random_create",
        )
        if block is not None:
            self._update_status(last_action=f"random block {block.evidence_block_id} at {ordinal}")

    def _persist_reload(self) -> None:
        self.ensure_document_loaded()
        self.transcript_widget.reload_current_thread()
        self._update_status(last_action="persist/reload")

    def _update_status(self, *, last_action: str) -> None:
        thread_id = self.transcript_widget.source_thread_id or "—"
        message_count = self.transcript_widget.message_count
        block_count = 0
        if self.dataset_id is not None and self.transcript_widget.source_thread_id:
            blocks = evidence_blocks.list_evidence_blocks(
                self.conn,
                self.dataset_id,
                source_thread_id=self.transcript_widget.source_thread_id,
            )
            block_count = len(blocks)
        active = self.transcript_widget.active_evidence_block_id
        active_label = str(active) if active is not None else "—"
        self.status_label.setText(
            f"Thread: {thread_id} | Messages: {message_count:,} | "
            f"Evidence blocks: {block_count} | Active block: {active_label} | "
            f"Last action: {last_action}"
        )
