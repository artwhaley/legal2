"""Prototype tab for reusable transcript widgets."""

from __future__ import annotations

import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from message_evidence_workstation.db import evidence_blocks, repositories
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.ui.transcript_surface import (
    EvidenceTranscriptModel,
    LazyQmlTranscriptSurface,
    TranscriptSurfaceWidget,
)


class TranscriptWidgetTab(QWidget):
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
        self._source_thread_id: str | None = None
        self._model = EvidenceTranscriptModel(self)

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Evidence transcript editor prototype. Drag blue context and black relevant "
            "boundary handles on separator rows. Click the circle beside a message to "
            "toggle highlighting."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Source thread"))
        self.thread_combo = QComboBox()
        self.thread_combo.currentIndexChanged.connect(self._on_thread_changed)
        controls.addWidget(self.thread_combo, stretch=1)
        layout.addLayout(controls)

        block_controls = QHBoxLayout()
        block_controls.addWidget(QLabel("Evidence block"))
        self.block_combo = QComboBox()
        self.block_combo.currentIndexChanged.connect(self._on_block_changed)
        block_controls.addWidget(self.block_combo, stretch=1)
        layout.addLayout(block_controls)

        self.summary_label = QLabel("No thread loaded.")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        self.version_tabs = QTabWidget()
        self.model_view_surface = TranscriptSurfaceWidget(self._model)
        self.version_tabs.addTab(self.model_view_surface, "Model / View")
        self.qml_surface = LazyQmlTranscriptSurface(self._model, logger)
        self.version_tabs.addTab(self.qml_surface, "QML")
        self.version_tabs.currentChanged.connect(self._on_version_tab_changed)
        layout.addWidget(self.version_tabs, stretch=1)

        self._model.state_changed.connect(self._update_summary)

    def set_dataset(self, dataset_id: int | None) -> None:
        self.dataset_id = dataset_id
        self.thread_combo.blockSignals(True)
        self.thread_combo.clear()
        self.thread_combo.blockSignals(False)
        self.block_combo.blockSignals(True)
        self.block_combo.clear()
        self.block_combo.blockSignals(False)
        if dataset_id is None:
            self.summary_label.setText("No dataset loaded.")
            self._model.load_messages([])
            return
        threads = repositories.list_source_threads(self.conn, dataset_id)
        self.thread_combo.blockSignals(True)
        for thread in threads:
            label = f"{thread.display_title} ({thread.source_thread_id})"
            self.thread_combo.addItem(label, thread.source_thread_id)
        self.thread_combo.blockSignals(False)
        if threads:
            self.thread_combo.setCurrentIndex(0)
            self._load_thread(threads[0].source_thread_id)
        else:
            self._model.load_messages([])
            self.summary_label.setText("No source threads available.")

    def select_source_thread(self, source_thread_id: str) -> None:
        index = self.thread_combo.findData(source_thread_id, role=Qt.ItemDataRole.UserRole)
        if index >= 0:
            self.thread_combo.setCurrentIndex(index)

    def select_evidence_block(self, evidence_block_id: int) -> None:
        block = evidence_blocks.get_evidence_block(self.conn, evidence_block_id)
        if block is None or self.dataset_id is None:
            return
        self.select_source_thread(block.source_thread_id)
        index = self.block_combo.findData(evidence_block_id, role=Qt.ItemDataRole.UserRole)
        if index >= 0:
            self.block_combo.setCurrentIndex(index)

    def _on_thread_changed(self, row: int) -> None:
        if row < 0:
            return
        source_thread_id = self.thread_combo.currentData(Qt.ItemDataRole.UserRole)
        if isinstance(source_thread_id, str):
            self._load_thread(source_thread_id)

    def _on_block_changed(self, row: int) -> None:
        if row < 0 or self._source_thread_id is None or self.dataset_id is None:
            return
        evidence_block_id = self.block_combo.currentData(Qt.ItemDataRole.UserRole)
        if evidence_block_id is None:
            return
        messages = repositories.list_messages_for_thread(
            self.conn,
            self.dataset_id,
            self._source_thread_id,
        )
        blocks = evidence_blocks.list_evidence_blocks(
            self.conn,
            self.dataset_id,
            source_thread_id=self._source_thread_id,
        )
        self._model.load_thread_blocks(
            messages,
            blocks,
            active_block_id=int(evidence_block_id),
        )
        self._update_summary()

    def _load_thread(self, source_thread_id: str) -> None:
        if self.dataset_id is None:
            return
        self._source_thread_id = source_thread_id
        blocks = evidence_blocks.list_evidence_blocks(
            self.conn,
            self.dataset_id,
            source_thread_id=source_thread_id,
        )
        self.block_combo.blockSignals(True)
        self.block_combo.clear()
        for block in blocks:
            self.block_combo.addItem(block.title, block.evidence_block_id)
        self.block_combo.blockSignals(False)

        active_block_id = blocks[0].evidence_block_id if blocks else None
        if blocks:
            self.block_combo.setCurrentIndex(0)

        messages = repositories.list_messages_for_thread(
            self.conn,
            self.dataset_id,
            source_thread_id,
        )
        self._model.load_thread_blocks(messages, blocks, active_block_id=active_block_id)
        self.logger.info(
            component="ui.transcript_widget_tab",
            operation="thread_loaded",
            message="Loaded evidence transcript thread",
            details={
                "dataset_id": self.dataset_id,
                "source_thread_id": source_thread_id,
                "message_count": len(messages),
                "evidence_block_count": len(blocks),
            },
            dataset_id=self.dataset_id,
        )
        self._update_summary()

    def _update_summary(self) -> None:
        if self.dataset_id is None:
            self.summary_label.setText("No dataset loaded.")
            return
        self.summary_label.setText(self._model.summary_text())

    def _on_version_tab_changed(self, index: int) -> None:
        if self.version_tabs.tabText(index) == "QML":
            self.qml_surface.ensure_loaded()
