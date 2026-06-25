"""Shared evidence-block transcript surface for search and dedicated transcript tabs."""

from __future__ import annotations

import sqlite3

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

from message_evidence_workstation.config.settings import load_settings, save_settings
from message_evidence_workstation.db import evidence_blocks, repositories
from message_evidence_workstation.domain.models import EvidenceBlock
from message_evidence_workstation.domain.slots import default_slots_for_hit_index_with_context
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.ui.speaker_tint_bar import SpeakerTintBar
from message_evidence_workstation.ui.transcript_display import normalize_speaker_tints
from message_evidence_workstation.ui.transcript_surface import (
    BlockOverlay,
    EvidenceTranscriptModel,
    Gen2TranscriptSurfaceWidget,
)

_LOG_COMPONENT = "ui.evidence_block_transcript_widget"


class EvidenceBlockTranscriptWidget(QWidget):
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
        layout.setContentsMargins(0, 0, 0, 0)

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

    @property
    def model(self) -> EvidenceTranscriptModel:
        return self._model

    def _on_speaker_tints_changed(self, tints: list[str]) -> None:
        settings = load_settings()
        settings.transcript.speaker_tints = normalize_speaker_tints(tints)
        save_settings(settings)
        self.transcript_surface.set_speaker_tints(tints)

    def set_dataset(self, dataset_id: int | None) -> None:
        self.dataset_id = dataset_id
        self._source_thread_id = None
        if dataset_id is None:
            self._model.load_messages([])

    def load_source_thread(self, source_thread_id: str, *, source_action: str = "thread_load") -> None:
        if self.dataset_id is None:
            return
        if self._source_thread_id == source_thread_id:
            return
        if self._source_thread_id is not None:
            self._persist_all_overlays()
        self._load_thread(source_thread_id, source_action=source_action)

    def reveal_created_evidence_block(
        self,
        block: EvidenceBlock,
        *,
        source_action: str = "search_drop",
    ) -> None:
        if self.dataset_id is None:
            return
        if self._source_thread_id != block.source_thread_id:
            if self._source_thread_id is not None:
                self._persist_all_overlays()
            self._load_thread(block.source_thread_id, source_action=source_action)
        else:
            self._persist_all_overlays()
            if self._model.overlay_by_id(block.evidence_block_id) is None:
                self._model.append_evidence_block(block)
        ordered_ids = self._model.ordered_message_ids()
        if block.core_hit_message_id in ordered_ids:
            hit_index = ordered_ids.index(block.core_hit_message_id)
            self.transcript_surface.scroll_to_message_index(hit_index)

    def focus_message(self, message_id: str, *, source_action: str = "focus_message") -> None:
        ordered_ids = self._model.ordered_message_ids()
        if message_id not in ordered_ids:
            return
        hit_index = ordered_ids.index(message_id)
        self.transcript_surface.scroll_to_message_index(hit_index)
        self.logger.info(
            component=_LOG_COMPONENT,
            operation="message_focused",
            message="Centered transcript on message",
            details={
                "dataset_id": self.dataset_id,
                "source_thread_id": self._source_thread_id,
                "message_id": message_id,
                "hit_index": hit_index,
                "source_action": source_action,
            },
            dataset_id=self.dataset_id,
        )

    def select_evidence_block(self, evidence_block_id: int) -> None:
        block = evidence_blocks.get_evidence_block(self.conn, evidence_block_id)
        if block is None or self.dataset_id is None:
            return
        if self._source_thread_id != block.source_thread_id:
            self.load_source_thread(block.source_thread_id, source_action="evidence_block_reveal")
        ordered_ids = self._model.ordered_message_ids()
        if block.core_hit_message_id in ordered_ids:
            hit_index = ordered_ids.index(block.core_hit_message_id)
            self.transcript_surface.scroll_to_message_index(hit_index)

    def create_evidence_block_from_viewport_center(
        self,
        category_id: int | None = None,
        *,
        source_action: str = "viewport_button",
    ) -> EvidenceBlock | None:
        if self.dataset_id is None or self._source_thread_id is None:
            return None
        hit_index = self.transcript_surface.viewport_center_message_index()
        if hit_index is None:
            return None
        messages = repositories.list_messages_for_thread(
            self.conn,
            self.dataset_id,
            self._source_thread_id,
        )
        if not messages or hit_index >= len(messages):
            return None
        return self._create_evidence_block(
            hit_message_id=messages[hit_index].message_id,
            hit_index=hit_index,
            category_id=category_id,
            source_action=source_action,
        )

    def create_evidence_block_for_message(
        self,
        message_id: str,
        category_id: int | None = None,
        *,
        source_action: str = "message_hit",
    ) -> EvidenceBlock | None:
        if self.dataset_id is None or self._source_thread_id is None:
            return None
        messages = repositories.list_messages_for_thread(
            self.conn,
            self.dataset_id,
            self._source_thread_id,
        )
        ordered_ids = [message.message_id for message in messages]
        if message_id not in ordered_ids:
            return None
        hit_index = ordered_ids.index(message_id)
        return self._create_evidence_block(
            hit_message_id=message_id,
            hit_index=hit_index,
            category_id=category_id,
            source_action=source_action,
        )

    def create_evidence_block_for_answer_range(
        self,
        *,
        hit_message_id: str,
        relevant_start_message_id: str,
        relevant_end_message_id: str,
        leading_context_start_message_id: str,
        trailing_context_end_message_id: str,
        title: str,
        summary: str = "",
        category_id: int | None = None,
        source_action: str = "answer_range",
    ) -> EvidenceBlock | None:
        if self.dataset_id is None or self._source_thread_id is None:
            return None
        self._persist_all_overlays()
        messages = repositories.list_messages_for_thread(
            self.conn,
            self.dataset_id,
            self._source_thread_id,
        )
        ordered_ids = [message.message_id for message in messages]
        required_ids = {
            hit_message_id,
            relevant_start_message_id,
            relevant_end_message_id,
            leading_context_start_message_id,
            trailing_context_end_message_id,
        }
        if not required_ids.issubset(set(ordered_ids)):
            return None
        block = evidence_blocks.create_evidence_block_from_conversational_candidate(
            self.conn,
            self.logger,
            dataset_id=self.dataset_id,
            source_thread_id=self._source_thread_id,
            ordered_message_ids=ordered_ids,
            title=title,
            summary=summary,
            core_message_id=hit_message_id,
            leading_context_start_message_id=leading_context_start_message_id,
            relevant_start_message_id=relevant_start_message_id,
            relevant_end_message_id=relevant_end_message_id,
            trailing_context_end_message_id=trailing_context_end_message_id,
            highlighted_message_ids=[hit_message_id],
            category_id=category_id,
        )
        self.logger.info(
            component=_LOG_COMPONENT,
            operation="answer_range_evidence_block_created",
            message="Created evidence block from conversational answer range",
            details={
                "evidence_block_id": block.evidence_block_id,
                "core_hit_message_id": hit_message_id,
                "source_action": source_action,
                "dataset_id": self.dataset_id,
                "source_thread_id": self._source_thread_id,
            },
            dataset_id=self.dataset_id,
        )
        self._model.append_evidence_block(block)
        self.focus_message(hit_message_id, source_action=source_action)
        self.evidence_block_created.emit(block.evidence_block_id)
        return block

    def _load_thread(self, source_thread_id: str, *, source_action: str) -> None:
        assert self.dataset_id is not None
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
        self.logger.info(
            component=_LOG_COMPONENT,
            operation="thread_loaded",
            message="Loaded evidence transcript thread",
            details={
                "dataset_id": self.dataset_id,
                "source_thread_id": source_thread_id,
                "message_count": len(messages),
                "evidence_block_count": len(blocks),
                "source_action": source_action,
            },
            dataset_id=self.dataset_id,
        )

    def _create_evidence_block(
        self,
        *,
        hit_message_id: str,
        hit_index: int,
        category_id: int | None,
        source_action: str,
    ) -> EvidenceBlock | None:
        if self.dataset_id is None or self._source_thread_id is None:
            return None
        self._persist_all_overlays()
        messages = repositories.list_messages_for_thread(
            self.conn,
            self.dataset_id,
            self._source_thread_id,
        )
        if not messages:
            return None
        ordered_ids = [message.message_id for message in messages]
        hit_message = messages[hit_index]
        title = hit_message.body[:80] if hit_message.body else f"Evidence {hit_message.message_id}"
        context_start, relevant_start, relevant_end, context_end = (
            default_slots_for_hit_index_with_context(len(messages), hit_index)
        )
        if category_id is None:
            category_id = evidence_blocks.ensure_uncategorized_category(
                self.conn,
                self.logger,
                self.dataset_id,
            ).category_id
        block = evidence_blocks.create_evidence_block(
            self.conn,
            self.logger,
            dataset_id=self.dataset_id,
            category_id=category_id,
            source_thread_id=self._source_thread_id,
            title=title,
            core_hit_message_id=hit_message_id,
            ordered_message_ids=ordered_ids,
            context_start_slot=context_start,
            relevant_start_slot=relevant_start,
            relevant_end_slot=relevant_end,
            context_end_slot=context_end,
        )
        self.logger.info(
            component=_LOG_COMPONENT,
            operation="evidence_block_created",
            message="Created evidence block from transcript widget",
            details={
                "evidence_block_id": block.evidence_block_id,
                "core_hit_message_id": hit_message_id,
                "category_id": block.category_id,
                "hit_index": hit_index,
                "source_action": source_action,
                "dataset_id": self.dataset_id,
                "source_thread_id": self._source_thread_id,
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
        return block

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
