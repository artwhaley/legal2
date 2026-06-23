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

from message_evidence_workstation.config.settings import load_settings, save_settings
from message_evidence_workstation.db import evidence_blocks, repositories
from message_evidence_workstation.domain.slots import default_slots_for_hit_index_with_context
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.ui.speaker_tint_bar import SpeakerTintBar
from message_evidence_workstation.ui.transcript_display import normalize_speaker_tints
from message_evidence_workstation.ui.transcript_surface import (
    BlockOverlay,
    EvidenceTranscriptModel,
    Gen2TranscriptSurfaceWidget,
)


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
        self._source_thread_id: str | None = None
        self._model = EvidenceTranscriptModel(self)

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

        settings = load_settings()
        self.speaker_tint_bar = SpeakerTintBar(settings.transcript.speaker_tints)
        self.speaker_tint_bar.tints_changed.connect(self._on_speaker_tints_changed)
        layout.addWidget(self.speaker_tint_bar)

        self.transcript_surface = Gen2TranscriptSurfaceWidget(
            self._model,
            speaker_tints=self.speaker_tint_bar.tints(),
        )
        layout.addWidget(self.transcript_surface, stretch=1)

        self._model.overlay_edited.connect(self._persist_overlay)

    def _on_speaker_tints_changed(self, tints: list[str]) -> None:
        settings = load_settings()
        settings.transcript.speaker_tints = normalize_speaker_tints(tints)
        save_settings(settings)
        self.transcript_surface.set_speaker_tints(tints)

    def set_dataset(self, dataset_id: int | None) -> None:
        self.dataset_id = dataset_id
        self.thread_combo.blockSignals(True)
        self.thread_combo.clear()
        self.thread_combo.blockSignals(False)
        if dataset_id is None:
            self._model.load_messages([])
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
            self._load_thread(threads[0].source_thread_id)
        else:
            self._model.load_messages([])
            self.new_block_button.setEnabled(False)

    def select_source_thread(self, source_thread_id: str) -> None:
        index = self.thread_combo.findData(source_thread_id, role=Qt.ItemDataRole.UserRole)
        if index >= 0:
            self.thread_combo.setCurrentIndex(index)

    def select_evidence_block(self, evidence_block_id: int) -> None:
        block = evidence_blocks.get_evidence_block(self.conn, evidence_block_id)
        if block is None or self.dataset_id is None:
            return
        self.select_source_thread(block.source_thread_id)
        ordered_ids = self._model.ordered_message_ids()
        if block.core_hit_message_id in ordered_ids:
            hit_index = ordered_ids.index(block.core_hit_message_id)
            self.transcript_surface.scroll_to_message_index(hit_index)

    def _on_thread_changed(self, row: int) -> None:
        if row < 0:
            return
        source_thread_id = self.thread_combo.currentData(Qt.ItemDataRole.UserRole)
        if isinstance(source_thread_id, str):
            self._persist_all_overlays()
            self._load_thread(source_thread_id)

    def _load_thread(self, source_thread_id: str) -> None:
        if self.dataset_id is None:
            return
        self._source_thread_id = source_thread_id
        blocks = evidence_blocks.list_evidence_blocks(
            self.conn,
            self.dataset_id,
            source_thread_id=source_thread_id,
        )
        messages = repositories.list_messages_for_thread(
            self.conn,
            self.dataset_id,
            source_thread_id,
        )
        self._model.load_thread_blocks(messages, blocks)
        self.new_block_button.setEnabled(bool(messages))
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

    def _persist_overlay(self, evidence_block_id: int) -> None:
        overlay = self._model.overlay_by_id(evidence_block_id)
        if overlay is None:
            return
        self._write_overlay_to_db(overlay)

    def _persist_all_overlays(self) -> None:
        for overlay in self._model.block_overlays():
            self._write_overlay_to_db(overlay)

    def _write_overlay_to_db(self, overlay: BlockOverlay) -> None:
        message_count = self._model.message_count()
        if message_count <= 0:
            return
        evidence_blocks.update_evidence_block_slots(
            self.conn,
            self.logger,
            evidence_block_id=overlay.evidence_block_id,
            message_count=message_count,
            context_start_slot=overlay.context_start_slot,
            relevant_start_slot=overlay.relevant_start_slot,
            relevant_end_slot=overlay.relevant_end_slot,
            context_end_slot=overlay.context_end_slot,
        )
        evidence_blocks.update_evidence_block_anchor(
            self.conn,
            self.logger,
            evidence_block_id=overlay.evidence_block_id,
            core_hit_message_id=overlay.core_hit_message_id,
        )
        evidence_blocks.set_evidence_block_highlights(
            self.conn,
            self.logger,
            evidence_block_id=overlay.evidence_block_id,
            highlighted_message_ids=sorted(overlay.highlighted_message_ids),
        )

    def _create_evidence_block_from_view(self) -> None:
        if self.dataset_id is None or self._source_thread_id is None:
            return
        hit_index = self.transcript_surface.viewport_center_message_index()
        if hit_index is None:
            return
        self._persist_all_overlays()
        messages = repositories.list_messages_for_thread(
            self.conn,
            self.dataset_id,
            self._source_thread_id,
        )
        if not messages:
            return
        ordered_ids = [message.message_id for message in messages]
        hit_message = messages[hit_index]
        title = hit_message.body[:80] if hit_message.body else f"Evidence {hit_message.message_id}"
        context_start, relevant_start, relevant_end, context_end = (
            default_slots_for_hit_index_with_context(len(messages), hit_index)
        )
        category = evidence_blocks.ensure_uncategorized_category(
            self.conn,
            self.logger,
            self.dataset_id,
        )
        block = evidence_blocks.create_evidence_block(
            self.conn,
            self.logger,
            dataset_id=self.dataset_id,
            category_id=category.category_id,
            source_thread_id=self._source_thread_id,
            title=title,
            core_hit_message_id=hit_message.message_id,
            ordered_message_ids=ordered_ids,
            context_start_slot=context_start,
            relevant_start_slot=relevant_start,
            relevant_end_slot=relevant_end,
            context_end_slot=context_end,
        )
        self.logger.info(
            component="ui.transcript_widget_tab",
            operation="evidence_block_created_from_view",
            message="Created evidence block from transcript viewport center",
            details={
                "evidence_block_id": block.evidence_block_id,
                "core_hit_message_id": hit_message.message_id,
                "hit_index": hit_index,
                "slots": {
                    "context_start_slot": context_start,
                    "relevant_start_slot": relevant_start,
                    "relevant_end_slot": relevant_end,
                    "context_end_slot": context_end,
                },
            },
            dataset_id=self.dataset_id,
        )
        self._model.append_evidence_block(block)
        self.transcript_surface.scroll_to_message_index(hit_index)
        self.evidence_block_created.emit(block.evidence_block_id)
