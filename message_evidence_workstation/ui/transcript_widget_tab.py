"""Prototype tab for reusable transcript widgets."""

from __future__ import annotations

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
from message_evidence_workstation.ui.evidence_block_transcript_widget import EvidenceBlockTranscriptWidget


class TranscriptWidgetTab(QWidget):
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
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Source thread"))
        self.thread_combo = QComboBox()
        self.thread_combo.currentIndexChanged.connect(self._on_thread_changed)
        controls.addWidget(self.thread_combo, stretch=1)
        self.new_block_button = QPushButton("New evidence block")
        self.new_block_button.clicked.connect(self._create_evidence_block_from_view)
        controls.addWidget(self.new_block_button)
        layout.addLayout(controls)

        self.transcript_widget = EvidenceBlockTranscriptWidget(conn, logger, self)
        self.transcript_widget.evidence_block_created.connect(self.evidence_block_created.emit)
        layout.addWidget(self.transcript_widget, stretch=1)

    @property
    def transcript_surface(self):
        return self.transcript_widget.transcript_surface

    @property
    def _model(self):
        return self.transcript_widget.model

    def set_dataset(self, dataset_id: int | None) -> None:
        self.dataset_id = dataset_id
        self.transcript_widget.set_dataset(dataset_id)
        self.thread_combo.blockSignals(True)
        self.thread_combo.clear()
        self.thread_combo.blockSignals(False)
        if dataset_id is None:
            self.new_block_button.setEnabled(False)
            return
        threads = repositories.list_source_threads(self.conn, dataset_id)
        self.thread_combo.blockSignals(True)
        for thread in threads:
            label = f"{thread.display_title} ({thread.source_thread_id})"
            self.thread_combo.addItem(label, thread.source_thread_id)
        self.thread_combo.blockSignals(False)
        if threads:
            self.thread_combo.setCurrentIndex(0)
            self.transcript_widget.load_source_thread(threads[0].source_thread_id)
            self.new_block_button.setEnabled(True)
        else:
            self.new_block_button.setEnabled(False)

    def select_source_thread(self, source_thread_id: str) -> None:
        index = self.thread_combo.findData(source_thread_id, role=Qt.ItemDataRole.UserRole)
        if index >= 0:
            self.thread_combo.setCurrentIndex(index)

    def select_evidence_block(self, evidence_block_id: int) -> None:
        self.transcript_widget.select_evidence_block(evidence_block_id)

    def _on_thread_changed(self, row: int) -> None:
        if row < 0:
            return
        source_thread_id = self.thread_combo.currentData(Qt.ItemDataRole.UserRole)
        if isinstance(source_thread_id, str):
            self.transcript_widget.load_source_thread(source_thread_id)

    def _create_evidence_block_from_view(self) -> None:
        self.transcript_widget.create_evidence_block_from_viewport_center(
            source_action="viewport_button",
        )
