"""Document-backed transcript widget (demonstrator)."""

from __future__ import annotations

import sqlite3

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QKeySequence,
    QTextBlock,
    QTextBlockUserData,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
)
from PySide6.QtWidgets import QApplication, QTextEdit, QVBoxLayout, QWidget

from message_evidence_workstation.db import evidence_blocks, repositories
from message_evidence_workstation.domain.models import EvidenceBlock, Message
from message_evidence_workstation.domain.slots import (
    default_slots_for_hit_index_with_context,
    resolve_boundary_move,
)
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.ui.new_transcript_annotation_overlay import (
    TranscriptAnnotationOverlay,
    TranscriptEvidenceOverlay,
)
from message_evidence_workstation.ui.transcript_data_source import SqlTranscriptDataSource, TranscriptDataSource
from message_evidence_workstation.ui.transcript_display import format_timestamp_label

DOCUMENT_BATCH_SIZE = 500
_LOG_COMPONENT = "ui.new_transcript_widget"


class ReadOnlyTranscriptEdit(QTextEdit):
    """QTextEdit that rejects user typing, paste, and drag-in text mutations."""

    def keyPressEvent(self, event) -> None:
        if event.matches(QKeySequence.StandardKey.Paste):
            event.ignore()
            return
        if event.text() and event.text().isprintable():
            event.ignore()
            return
        super().keyPressEvent(event)

    def insertFromMimeData(self, source) -> None:
        del source

    def canInsertFromMimeData(self, source) -> bool:
        del source
        return False


class TranscriptBlockUserData(QTextBlockUserData):
    """Metadata anchored to one message block in the QTextDocument."""

    def __init__(
        self,
        *,
        message_id: str,
        source_thread_id: str,
        thread_ordinal: int,
        timestamp: str,
        sender_display: str,
    ) -> None:
        super().__init__()
        self.message_id = message_id
        self.source_thread_id = source_thread_id
        self.thread_ordinal = thread_ordinal
        self.timestamp = timestamp
        self.sender_display = sender_display


class NewTranscriptWidget(QWidget):
    """Read-only document transcript for one active source thread."""

    load_progress = Signal(str)
    thread_loaded = Signal(str, int)
    evidence_block_created = Signal(int)
    active_block_changed = Signal(object)

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
        self._message_count = 0
        self._data_source: TranscriptDataSource | None = None
        self._overlays: list[TranscriptEvidenceOverlay] = []
        self._active_evidence_block_id: int | None = None

        self.message_id_to_block_number: dict[str, int] = {}
        self.block_number_to_message_id: dict[int, str] = {}
        self.message_index_to_document_block_number: dict[int, int] = {}
        self.message_id_to_thread_ordinal: dict[str, int] = {}
        self.thread_ordinal_to_message_id: dict[int, str] = {}
        self._formatted_ordinals: set[int] = set()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.text_edit = ReadOnlyTranscriptEdit(self)
        self.text_edit.setReadOnly(True)
        self.text_edit.setAcceptRichText(True)
        self.text_edit.setLineWrapMode(ReadOnlyTranscriptEdit.LineWrapMode.WidgetWidth)
        self.text_edit.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        self.text_edit.setUndoRedoEnabled(False)
        self._apply_document_style(self.text_edit.document())
        layout.addWidget(self.text_edit, stretch=1)

        self._annotation_overlay = TranscriptAnnotationOverlay(self.text_edit, self)
        self._annotation_overlay.boundary_moved.connect(self._on_boundary_drag)
        self._annotation_overlay.boundary_released.connect(self._on_boundary_released)
        self._annotation_overlay.hit_message_selected.connect(self._on_hit_message_selected)
        self._annotation_overlay.highlight_toggled.connect(self._on_highlight_toggled)

    def _apply_document_style(self, document: QTextDocument) -> None:
        document.setDefaultFont(QFont("Segoe UI", 10))
        document.setDocumentMargin(24)
        self.text_edit.setStyleSheet(
            "QTextEdit {"
            "background: #faf9f7;"
            "border: 1px solid #d8d4cc;"
            "padding: 8px;"
            "}"
        )

    def set_dataset(self, dataset_id: int | None) -> None:
        self.dataset_id = dataset_id
        if dataset_id is None:
            self._data_source = None
            self._clear_document()
            return
        self._data_source = SqlTranscriptDataSource(self.conn, dataset_id)

    def load_source_thread(self, source_thread_id: str, *, source_action: str = "thread_load") -> None:
        if self.dataset_id is None or self._data_source is None:
            self._clear_document()
            return
        if self._source_thread_id is not None and self._source_thread_id != source_thread_id:
            self.persist_all_overlays()
        self._source_thread_id = source_thread_id
        self._message_count = self._data_source.message_count(source_thread_id)
        self._build_document_from_sql(source_thread_id)
        self._load_overlays_from_db()
        self._refresh_annotation_display()
        self._update_overlay_widget()
        self.thread_loaded.emit(source_thread_id, self._message_count)
        self.logger.info(
            component=_LOG_COMPONENT,
            operation="thread_loaded",
            message="Loaded document transcript thread",
            details={
                "dataset_id": self.dataset_id,
                "source_thread_id": source_thread_id,
                "message_count": self._message_count,
                "evidence_block_count": len(self._overlays),
                "source_action": source_action,
            },
            dataset_id=self.dataset_id,
        )

    def reload_current_thread(self) -> None:
        if self._source_thread_id is None:
            return
        thread_id = self._source_thread_id
        self.persist_all_overlays()
        self.load_source_thread(thread_id, source_action="persist_reload")

    def document_block_count(self) -> int:
        return len(self.block_number_to_message_id)

    def message_block_user_data(self, message_id: str) -> TranscriptBlockUserData | None:
        block_number = self.message_id_to_block_number.get(message_id)
        if block_number is None:
            return None
        block = self._block_at_number(block_number)
        if block is None or not block.isValid():
            return None
        user_data = block.userData()
        return user_data if isinstance(user_data, TranscriptBlockUserData) else None

    def block_for_ordinal(self, thread_ordinal: int) -> QTextBlock | None:
        message_id = self.thread_ordinal_to_message_id.get(thread_ordinal)
        if message_id is None:
            return None
        block_number = self.message_id_to_block_number.get(message_id)
        if block_number is None:
            return None
        return self._block_at_number(block_number)

    def message_index_for_message_id(self, message_id: str) -> int | None:
        return self.message_id_to_block_number.get(message_id)

    def scroll_to_ordinal(self, thread_ordinal: int) -> bool:
        if self._message_count <= 0:
            return False
        target = max(0, min(thread_ordinal, self._message_count - 1))
        block = self.block_for_ordinal(target)
        if block is None or not block.isValid():
            return False
        cursor = QTextCursor(block)
        self.text_edit.setTextCursor(cursor)
        layout = self.text_edit.document().documentLayout()
        block_rect = layout.blockBoundingRect(block)
        viewport_height = self.text_edit.viewport().height()
        scroll = self.text_edit.verticalScrollBar()
        scroll.setValue(int(max(0, block_rect.center().y() - viewport_height / 2)))
        self._update_overlay_widget()
        return True

    def scroll_to_message(self, message_id: str) -> bool:
        ordinal = self.message_id_to_thread_ordinal.get(message_id)
        if ordinal is None:
            return False
        return self.scroll_to_ordinal(ordinal)

    def focus_message(self, message_id: str, *, source_action: str = "focus_message") -> None:
        if self.scroll_to_message(message_id):
            self.logger.info(
                component=_LOG_COMPONENT,
                operation="message_focused",
                message="Centered document transcript on message",
                details={
                    "dataset_id": self.dataset_id,
                    "source_thread_id": self._source_thread_id,
                    "message_id": message_id,
                    "source_action": source_action,
                },
                dataset_id=self.dataset_id,
            )

    def viewport_center_message_id(self) -> str | None:
        ordinal = self.viewport_center_ordinal()
        if ordinal is None:
            return None
        return self.thread_ordinal_to_message_id.get(ordinal)

    def viewport_center_ordinal(self) -> int | None:
        viewport = self.text_edit.viewport()
        center = QPoint(viewport.width() // 2, viewport.height() // 2)
        cursor = self.text_edit.cursorForPosition(center)
        return self._ordinal_for_block(cursor.block())

    def create_evidence_block_from_viewport_center(
        self,
        category_id: int | None = None,
        *,
        source_action: str = "viewport_button",
    ) -> EvidenceBlock | None:
        message_id = self.viewport_center_message_id()
        if message_id is None:
            return None
        hit_index = self.message_index_for_message_id(message_id)
        if hit_index is None:
            return None
        return self._create_evidence_block(
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
        hit_index = self.message_index_for_message_id(message_id)
        if hit_index is None:
            return None
        return self._create_evidence_block(
            hit_index=hit_index,
            category_id=category_id,
            source_action=source_action,
        )

    def reveal_created_evidence_block(
        self,
        block: EvidenceBlock,
        *,
        source_action: str = "search_drop",
    ) -> None:
        if self.dataset_id is None:
            return
        if self._source_thread_id != block.source_thread_id:
            self.load_source_thread(block.source_thread_id, source_action=source_action)
        else:
            if self.overlay_by_id(block.evidence_block_id) is None:
                self.append_evidence_block(block)
        self.set_active_evidence_block(block.evidence_block_id)
        self.scroll_to_message(block.core_hit_message_id)

    def select_evidence_block(self, evidence_block_id: int) -> None:
        block = evidence_blocks.get_evidence_block(self.conn, evidence_block_id)
        if block is None or self.dataset_id is None:
            return
        if self._source_thread_id != block.source_thread_id:
            self.load_source_thread(block.source_thread_id, source_action="evidence_block_reveal")
        self.set_active_evidence_block(evidence_block_id)
        self.scroll_to_message(block.core_hit_message_id)

    def append_evidence_block(self, block: EvidenceBlock) -> None:
        if self.overlay_by_id(block.evidence_block_id) is not None:
            return
        self._overlays.append(
            TranscriptEvidenceOverlay(
                evidence_block_id=block.evidence_block_id,
                context_start_slot=block.context_start_slot,
                relevant_start_slot=block.relevant_start_slot,
                relevant_end_slot=block.relevant_end_slot,
                context_end_slot=block.context_end_slot,
                core_hit_message_id=block.core_hit_message_id,
                highlighted_message_ids=frozenset(block.highlighted_message_ids),
                is_active=False,
            )
        )

    def set_active_evidence_block(self, evidence_block_id: int | None) -> None:
        self._active_evidence_block_id = evidence_block_id
        for overlay in self._overlays:
            overlay.is_active = overlay.evidence_block_id == evidence_block_id
        self._refresh_annotation_display()
        self._update_overlay_widget()
        self.active_block_changed.emit(evidence_block_id)

    def overlay_by_id(self, evidence_block_id: int) -> TranscriptEvidenceOverlay | None:
        for overlay in self._overlays:
            if overlay.evidence_block_id == evidence_block_id:
                return overlay
        return None

    def persist_overlay(self, evidence_block_id: int) -> None:
        overlay = self.overlay_by_id(evidence_block_id)
        if overlay is None:
            return
        self._write_overlay_to_db(overlay)

    def persist_all_overlays(self) -> None:
        for overlay in self._overlays:
            self._write_overlay_to_db(overlay)

    def move_boundary(self, evidence_block_id: int, boundary_name: str, slot_index: int, *, persist: bool) -> bool:
        overlay = self.overlay_by_id(evidence_block_id)
        if overlay is None:
            return False
        resolved = resolve_boundary_move(
            boundary_name,
            slot_index,
            message_count=self._message_count,
            context_start=overlay.context_start_slot,
            relevant_start=overlay.relevant_start_slot,
            relevant_end=overlay.relevant_end_slot,
            context_end=overlay.context_end_slot,
        )
        if resolved is None:
            return False
        (
            overlay.context_start_slot,
            overlay.relevant_start_slot,
            overlay.relevant_end_slot,
            overlay.context_end_slot,
        ) = resolved
        self._refresh_annotation_display()
        self._update_overlay_widget()
        if persist:
            self.persist_overlay(evidence_block_id)
        return True

    def set_hit_message(self, evidence_block_id: int, message_id: str, *, persist: bool = True) -> bool:
        overlay = self.overlay_by_id(evidence_block_id)
        if overlay is None:
            return False
        ordinal = self.message_id_to_thread_ordinal.get(message_id)
        if ordinal is None:
            return False
        if not (overlay.relevant_start_slot <= ordinal < overlay.relevant_end_slot):
            return False
        overlay.core_hit_message_id = message_id
        self._refresh_annotation_display()
        self._update_overlay_widget()
        if persist:
            self.persist_overlay(evidence_block_id)
        return True

    def toggle_highlight(self, evidence_block_id: int, message_id: str, *, persist: bool = True) -> bool:
        overlay = self.overlay_by_id(evidence_block_id)
        if overlay is None:
            return False
        ordinal = self.message_id_to_thread_ordinal.get(message_id)
        if ordinal is None:
            return False
        if not (overlay.relevant_start_slot <= ordinal < overlay.relevant_end_slot):
            return False
        highlighted = set(overlay.highlighted_message_ids)
        if message_id in highlighted:
            highlighted.remove(message_id)
        else:
            highlighted.add(message_id)
        overlay.highlighted_message_ids = frozenset(highlighted)
        self._refresh_annotation_display()
        self._update_overlay_widget()
        if persist:
            self.persist_overlay(evidence_block_id)
        return True

    @property
    def source_thread_id(self) -> str | None:
        return self._source_thread_id

    @property
    def message_count(self) -> int:
        return self._message_count

    @property
    def active_evidence_block_id(self) -> int | None:
        return self._active_evidence_block_id

    @property
    def document(self) -> QTextDocument:
        return self.text_edit.document()

    def _clear_document(self) -> None:
        self._source_thread_id = None
        self._message_count = 0
        self._overlays.clear()
        self._active_evidence_block_id = None
        self.message_id_to_block_number.clear()
        self.block_number_to_message_id.clear()
        self.message_index_to_document_block_number.clear()
        self.message_id_to_thread_ordinal.clear()
        self.thread_ordinal_to_message_id.clear()
        self._formatted_ordinals.clear()
        self.text_edit.clear()
        self._update_overlay_widget()

    def _load_overlays_from_db(self) -> None:
        self._overlays.clear()
        if self.dataset_id is None or self._source_thread_id is None or self._data_source is None:
            return
        blocks = self._data_source.fetch_evidence_blocks(self._source_thread_id)
        for block in blocks:
            self.append_evidence_block(block)
        if blocks:
            self.set_active_evidence_block(blocks[0].evidence_block_id)
        else:
            self._active_evidence_block_id = None

    def _create_evidence_block(
        self,
        *,
        hit_index: int,
        category_id: int | None,
        source_action: str,
    ) -> EvidenceBlock | None:
        if self.dataset_id is None or self._source_thread_id is None:
            return None
        self.persist_all_overlays()
        message_count = self._message_count
        if hit_index < 0 or hit_index >= message_count:
            return None
        messages = repositories.fetch_messages_for_slot_range(
            self.conn,
            self.dataset_id,
            self._source_thread_id,
            hit_index,
            hit_index + 1,
        )
        if not messages:
            return None
        hit_message = messages[0]
        hit_message_id = hit_message.message_id
        title = hit_message.body[:80] if hit_message.body else f"Evidence {hit_message.message_id}"
        context_start, relevant_start, relevant_end, context_end = (
            default_slots_for_hit_index_with_context(message_count, hit_index)
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
            message_count=message_count,
            context_start_slot=context_start,
            relevant_start_slot=relevant_start,
            relevant_end_slot=relevant_end,
            context_end_slot=context_end,
        )
        self.append_evidence_block(block)
        self.set_active_evidence_block(block.evidence_block_id)
        ordinal = self.message_id_to_thread_ordinal.get(hit_message_id, hit_index)
        self.scroll_to_ordinal(ordinal)
        self.evidence_block_created.emit(block.evidence_block_id)
        self.logger.info(
            component=_LOG_COMPONENT,
            operation="evidence_block_created",
            message="Created evidence block from new transcript widget",
            details={
                "evidence_block_id": block.evidence_block_id,
                "core_hit_message_id": hit_message_id,
                "source_action": source_action,
            },
            dataset_id=self.dataset_id,
        )
        return block

    def _write_overlay_to_db(self, overlay: TranscriptEvidenceOverlay) -> None:
        if self._message_count <= 0:
            return
        evidence_blocks.update_evidence_block_slots(
            self.conn,
            self.logger,
            evidence_block_id=overlay.evidence_block_id,
            message_count=self._message_count,
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

    def _on_boundary_drag(self, boundary_name: str, slot_index: int) -> None:
        if self._active_evidence_block_id is None:
            return
        self.move_boundary(
            self._active_evidence_block_id,
            boundary_name,
            slot_index,
            persist=False,
        )

    def _on_boundary_released(self, boundary_name: str, slot_index: int) -> None:
        if self._active_evidence_block_id is None:
            return
        self.move_boundary(
            self._active_evidence_block_id,
            boundary_name,
            slot_index,
            persist=True,
        )

    def _on_hit_message_selected(self, message_id: str) -> None:
        if self._active_evidence_block_id is None:
            return
        self.set_hit_message(self._active_evidence_block_id, message_id, persist=True)

    def _on_highlight_toggled(self, message_id: str) -> None:
        if self._active_evidence_block_id is None:
            return
        self.toggle_highlight(self._active_evidence_block_id, message_id, persist=True)

    def _ordinal_for_block(self, block: QTextBlock) -> int | None:
        while block.isValid():
            user_data = block.userData()
            if isinstance(user_data, TranscriptBlockUserData):
                return user_data.thread_ordinal
            block = block.previous()
        return None

    def _header_block_for_message_index(self, message_index: int) -> QTextBlock | None:
        index = 0
        block = self.text_edit.document().firstBlock()
        while block.isValid():
            user_data = block.userData()
            if isinstance(user_data, TranscriptBlockUserData):
                if index == message_index:
                    return block
                index += 1
            block = block.next()
        return None

    def _block_at_number(self, block_number: int) -> QTextBlock | None:
        document_block_number = self.message_index_to_document_block_number.get(block_number)
        if document_block_number is None:
            return None
        block = self.text_edit.document().findBlockByNumber(document_block_number)
        return block if block.isValid() else None

    def _slot_y_positions(self) -> dict[int, int]:
        positions: dict[int, int] = {0: 0}
        if self._message_count <= 0:
            return positions
        slots = self._annotation_slots_to_measure()
        if not slots:
            return positions
        for ordinal in sorted(slot for slot in slots if 0 <= slot < self._message_count):
            block = self.block_for_ordinal(ordinal)
            if block is None or not block.isValid():
                continue
            rect = self.text_edit.cursorRect(QTextCursor(block))
            positions[ordinal] = max(0, rect.top())
        if self._message_count in slots:
            last_block = self.block_for_ordinal(self._message_count - 1)
            if last_block is not None and last_block.isValid():
                rect = self.text_edit.cursorRect(QTextCursor(last_block))
                positions[self._message_count] = rect.bottom()
        return positions

    def _annotation_slots_to_measure(self) -> set[int]:
        slots: set[int] = set()
        for overlay in self._overlays:
            if not overlay.is_active:
                continue
            slots.update(
                {
                    overlay.context_start_slot,
                    overlay.relevant_start_slot,
                    overlay.relevant_end_slot,
                    overlay.context_end_slot,
                }
            )
            slots.update(range(overlay.relevant_start_slot, overlay.relevant_end_slot))
        return {max(0, min(self._message_count, slot)) for slot in slots}

    def _update_overlay_widget(self) -> None:
        if not self._overlays:
            self._annotation_overlay.set_slot_positions({}, message_count=self._message_count)
            self._annotation_overlay.set_overlays([])
            return
        self._annotation_overlay.set_slot_positions(
            self._slot_y_positions(),
            message_count=self._message_count,
        )
        self._annotation_overlay.set_overlays(self._overlays)

    def _refresh_annotation_display(self) -> None:
        header_format = QTextCharFormat()
        header_format.setFontWeight(QFont.Weight.DemiBold)
        header_format.setForeground(QColor("#555555"))
        body_format = QTextCharFormat()
        body_format.setForeground(QColor("#111111"))

        target_ordinals = self._annotation_ordinals_to_format()
        ordinals_to_touch = self._formatted_ordinals | target_ordinals
        next_formatted: set[int] = set()
        for ordinal in sorted(ordinals_to_touch):
            message_id = self.thread_ordinal_to_message_id.get(ordinal)
            if message_id is None:
                continue
            block_number = self.message_id_to_block_number.get(message_id)
            if block_number is None:
                continue
            header = self._block_at_number(block_number)
            if header is None or not header.isValid():
                continue
            header_fmt = self._char_format_for_ordinal(ordinal, is_header=True)
            self._apply_block_format(header, header_fmt or header_format)
            if header_fmt is not None:
                next_formatted.add(ordinal)
            body = header.next()
            if body.isValid() and not isinstance(body.userData(), TranscriptBlockUserData):
                body_fmt = self._char_format_for_ordinal(ordinal, is_header=False)
                self._apply_block_format(body, body_fmt or body_format)
        self._formatted_ordinals = next_formatted

    def _annotation_ordinals_to_format(self) -> set[int]:
        ordinals: set[int] = set()
        for overlay in self._overlays:
            start = max(0, min(self._message_count, overlay.context_start_slot))
            end = max(0, min(self._message_count, overlay.context_end_slot))
            ordinals.update(range(start, end))
            for message_id in (overlay.core_hit_message_id, *overlay.highlighted_message_ids):
                ordinal = self.message_id_to_thread_ordinal.get(message_id)
                if ordinal is not None:
                    ordinals.add(ordinal)
        return ordinals

    def _char_format_for_ordinal(self, ordinal: int, *, is_header: bool) -> QTextCharFormat | None:
        message_id = self.thread_ordinal_to_message_id.get(ordinal)
        active_overlay = self.overlay_by_id(self._active_evidence_block_id) if self._active_evidence_block_id else None
        in_context = False
        in_relevant = False
        is_hit = False
        is_highlight = False
        is_active_block = False
        for overlay in self._overlays:
            if overlay.context_start_slot <= ordinal < overlay.context_end_slot:
                in_context = True
                if overlay.is_active:
                    is_active_block = True
            if overlay.relevant_start_slot <= ordinal < overlay.relevant_end_slot:
                in_relevant = True
            if message_id and message_id == overlay.core_hit_message_id:
                is_hit = True
            if message_id and message_id in overlay.highlighted_message_ids:
                is_highlight = True
        if not in_context and not is_hit and not is_highlight:
            return None
        fmt = QTextCharFormat()
        if is_hit:
            fmt.setBackground(QBrush(QColor("#a5d6a7" if is_header else "#c8e6c9")))
            fmt.setFontWeight(QFont.Weight.Bold if is_header else QFont.Weight.Normal)
        elif is_highlight:
            fmt.setBackground(QBrush(QColor("#fff9c4")))
        elif in_relevant:
            fmt.setBackground(QBrush(QColor("#dcefd4" if is_active_block else "#eef7ee")))
        elif in_context:
            fmt.setBackground(QBrush(QColor("#f5f5f5")))
        return fmt

    def _apply_block_format(self, block: QTextBlock, fmt: QTextCharFormat) -> None:
        cursor = QTextCursor(block)
        cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
        cursor.setBlockCharFormat(fmt)
        cursor.mergeCharFormat(fmt)

    def _build_document_from_sql(self, source_thread_id: str) -> None:
        assert self._data_source is not None
        self.message_id_to_block_number.clear()
        self.block_number_to_message_id.clear()
        self.message_index_to_document_block_number.clear()
        self.message_id_to_thread_ordinal.clear()
        self.thread_ordinal_to_message_id.clear()
        self._formatted_ordinals.clear()

        document = self.text_edit.document()
        document.setUndoRedoEnabled(False)
        self.text_edit.setUpdatesEnabled(False)
        try:
            cursor = QTextCursor(document)
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            cursor.select(QTextCursor.SelectionType.Document)
            cursor.removeSelectedText()

            header_format = QTextCharFormat()
            header_format.setFontWeight(QFont.Weight.DemiBold)
            header_format.setForeground(QColor("#555555"))
            body_format = QTextCharFormat()
            body_format.setForeground(QColor("#111111"))

            block_number = 0
            total = self._message_count
            for start in range(0, max(total, 1), DOCUMENT_BATCH_SIZE):
                if start >= total:
                    break
                batch = self._data_source.fetch_messages(
                    source_thread_id,
                    start,
                    min(DOCUMENT_BATCH_SIZE, total - start),
                )
                for message in batch:
                    self._append_message_block(
                        cursor,
                        message,
                        block_number=block_number,
                        header_format=header_format,
                        body_format=body_format,
                    )
                    block_number += 1
                if total > DOCUMENT_BATCH_SIZE:
                    self.load_progress.emit(
                        f"Loaded {min(start + len(batch), total):,} / {total:,} messages"
                    )
                    QApplication.processEvents()

            cursor.movePosition(QTextCursor.MoveOperation.Start)
            self.text_edit.setTextCursor(cursor)
        finally:
            self.text_edit.setUpdatesEnabled(True)
            self.text_edit.viewport().update()

    def _append_message_block(
        self,
        cursor: QTextCursor,
        message: Message,
        *,
        block_number: int,
        header_format: QTextCharFormat,
        body_format: QTextCharFormat,
    ) -> None:
        ordinal = message.thread_ordinal if message.thread_ordinal is not None else block_number
        timestamp_label = format_timestamp_label(message.timestamp)
        header = f"{timestamp_label}  {message.sender_display}"
        body = message.body or ""

        if cursor.position() > 0:
            cursor.insertBlock()
        cursor.insertText(header, header_format)
        cursor.insertBlock()
        cursor.insertText(body, body_format)
        cursor.insertBlock()

        header_block = cursor.block().previous().previous()
        if not header_block.isValid():
            header_block = cursor.block()

        user_data = TranscriptBlockUserData(
            message_id=message.message_id,
            source_thread_id=message.source_thread_id,
            thread_ordinal=int(ordinal),
            timestamp=message.timestamp,
            sender_display=message.sender_display,
        )
        header_block.setUserData(user_data)

        self.message_id_to_block_number[message.message_id] = block_number
        self.block_number_to_message_id[block_number] = message.message_id
        self.message_index_to_document_block_number[block_number] = header_block.blockNumber()
        self.message_id_to_thread_ordinal[message.message_id] = int(ordinal)
        self.thread_ordinal_to_message_id[int(ordinal)] = message.message_id

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._annotation_overlay._sync_geometry()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._annotation_overlay._sync_geometry()
