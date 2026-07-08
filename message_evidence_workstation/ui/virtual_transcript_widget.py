"""Virtualized SQL-backed transcript widget (Gen 3)."""

from __future__ import annotations

import sqlite3

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPainterPath, QPen, QWheelEvent
from PySide6.QtWidgets import QMessageBox, QScrollBar, QWidget

from message_evidence_workstation.db import evidence_blocks
from message_evidence_workstation.domain.constants import CREATED_BY_CONVERSATIONAL_ANSWER
from message_evidence_workstation.domain.models import EvidenceBlock
from message_evidence_workstation.domain.slots import (
    BOUNDARY_CONTEXT_END,
    BOUNDARY_CONTEXT_START,
    BOUNDARY_RELEVANT_END,
    BOUNDARY_RELEVANT_START,
    default_slots_for_hit_index_with_context,
    resolve_boundary_move,
)
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.ui.transcript_display import build_sender_participant_map
from message_evidence_workstation.ui.virtual_transcript_annotations import (
    boundary_handles_for_layouts,
    highlight_header_rect,
    highlight_icon_rect,
    hit_header_rect,
    hit_icon_rect,
    zone_for_ordinal,
)
from message_evidence_workstation.ui.virtual_transcript_height_index import TranscriptHeightIndex
from message_evidence_workstation.ui.virtual_transcript_model import VirtualTranscriptModel
from message_evidence_workstation.ui.virtual_transcript_renderer import VirtualTranscriptRenderer

WINDOW_OVERSCAN = 12
_LOG_COMPONENT = "ui.virtual_transcript_widget"

RELEVANT_FILL = "#e8f3df"
CONTEXT_FILL = "#ece9e4"
HIGHLIGHT_FILL = "#fff5bf"
DELETE_PREVIEW_CONTEXT_FILL = "#ffe8a3"
DELETE_PREVIEW_RELEVANT_FILL = "#ffd24d"
CENTER_MARKER_COLOR = "#d4d4d4"


class VirtualTranscriptWidget(QWidget):
    """Paint-based virtual transcript surface."""

    thread_loaded = Signal(str, int)
    evidence_block_created = Signal(int)
    evidence_block_deleted = Signal(int)
    active_block_changed = Signal(object)
    status_changed = Signal()

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
        self._model = VirtualTranscriptModel(conn, logger)
        self._height_index: TranscriptHeightIndex | None = None
        self._renderer = VirtualTranscriptRenderer()
        self._scroll_offset_y = 0.0
        self._visible_start_ordinal = 0
        self._visible_end_ordinal = 0
        self._layout_rects: list = []
        self._drag_target: tuple[str, int] | None = None
        self._delete_preview_block_id: int | None = None
        self._anchor_scroll_on_resize: float | None = None

        self._scroll_bar = QScrollBar(Qt.Orientation.Vertical, self)
        self._scroll_bar.valueChanged.connect(self._on_scrollbar_changed)
        self._scroll_bar.hide()

        self.setMouseTracking(True)
        self.setMinimumHeight(240)

    @property
    def model(self) -> VirtualTranscriptModel:
        return self._model

    @property
    def message_count(self) -> int:
        return self._model.message_count

    @property
    def source_thread_id(self) -> str | None:
        return self._model.source_thread_id

    @property
    def active_evidence_block_id(self) -> int | None:
        return self._model.active_evidence_block_id

    @property
    def visible_ordinal_range(self) -> tuple[int, int]:
        return self._visible_start_ordinal, self._visible_end_ordinal

    @property
    def cached_message_count(self) -> int:
        return self._model.cached_message_count()

    @property
    def measured_height_count(self) -> int:
        return self._height_index.measured_count if self._height_index is not None else 0

    @property
    def _source_thread_id(self) -> str | None:
        return self._model.source_thread_id

    @property
    def transcript_surface(self):
        """Compatibility alias for embedded search/conversational panels."""
        return self

    def set_dataset(self, dataset_id: int | None) -> None:
        self.dataset_id = dataset_id
        self._model.set_dataset(dataset_id)
        self._height_index = None
        self._scroll_offset_y = 0.0
        self._layout_rects = []
        self.update()

    def load_source_thread(self, source_thread_id: str, *, source_action: str = "thread_load") -> None:
        if (
            self._model.source_thread_id == source_thread_id
            and self._height_index is not None
            and self._model.message_count > 0
        ):
            return
        self._model.load_thread(source_thread_id)
        self._height_index = TranscriptHeightIndex(
            self._model.message_count,
            default_height=self._renderer.estimate_height(
                self._renderer.style_for_width(max(self.width(), 320))
            ),
        )
        self._scroll_offset_y = 0.0
        participant_messages = self._model.messages_for_range(
            0,
            min(self._model.message_count, WINDOW_OVERSCAN * 2),
        )
        self._renderer.set_participant_map(build_sender_participant_map(participant_messages))
        self._sync_scrollbar()
        self._refresh_visible_window(force_remeasure=True)
        if self._model.active_evidence_block_id is not None:
            self.active_block_changed.emit(self._model.active_evidence_block_id)
        self.thread_loaded.emit(source_thread_id, self._model.message_count)
        self.status_changed.emit()
        self.logger.info(
            component=_LOG_COMPONENT,
            operation="thread_ready",
            message="Virtual transcript thread ready",
            details={
                "source_thread_id": source_thread_id,
                "message_count": self._model.message_count,
                "source_action": source_action,
            },
            dataset_id=self.dataset_id,
        )

    def reload_current_thread(self) -> None:
        thread_id = self._model.source_thread_id
        if thread_id is None:
            return
        anchor = self._scroll_offset_y
        self.load_source_thread(thread_id)
        self.scroll_to_offset(anchor)

    def scroll_to_center_ordinal(self, ordinal: int) -> bool:
        if self._height_index is None or self._model.message_count <= 0:
            return False
        target = max(0, min(int(ordinal), self._model.message_count - 1))
        top = self._height_index.offset_for_ordinal(target)
        height = self._height_index.height_at(target)
        message_center = top + (height / 2.0)
        self.scroll_to_offset(message_center - self._viewport_center_screen_y())
        layout = next((item for item in self._layout_rects if item.ordinal == target), None)
        if layout is not None:
            refined_center = layout.top + (layout.height / 2.0)
            self.scroll_to_offset(refined_center - self._viewport_center_screen_y())
        return True

    def scroll_to_ordinal(self, ordinal: int) -> bool:
        if self._height_index is None or self._model.message_count <= 0:
            return False
        target = max(0, min(int(ordinal), self._model.message_count - 1))
        self.scroll_to_offset(self._height_index.offset_for_ordinal(target))
        return True

    def scroll_to_message(self, message_id: str) -> bool:
        ordinal = self._model.ordinal_for_message_id(message_id)
        if ordinal is None:
            return False
        return self.scroll_to_center_ordinal(ordinal)

    def focus_message(self, message_id: str, *, source_action: str = "focus_message") -> None:
        if not self.scroll_to_message(message_id):
            return
        self.logger.info(
            component=_LOG_COMPONENT,
            operation="message_focused",
            message="Centered virtual transcript on message",
            details={
                "dataset_id": self.dataset_id,
                "source_thread_id": self._model.source_thread_id,
                "message_id": message_id,
                "source_action": source_action,
            },
            dataset_id=self.dataset_id,
        )

    def select_evidence_block(self, evidence_block_id: int) -> None:
        block = evidence_blocks.get_evidence_block(self.conn, evidence_block_id)
        if block is None or self.dataset_id is None:
            return
        if self._model.source_thread_id != block.source_thread_id:
            self.load_source_thread(block.source_thread_id, source_action="evidence_block_reveal")
        elif self._model.overlay_for_block(evidence_block_id) is None:
            self._model.append_or_update_evidence_block(block)
        self._model.show_evidence_block(evidence_block_id)
        self._model.set_active_evidence_block(evidence_block_id)
        ordinal = self._model.ordinal_for_message_id(block.core_hit_message_id)
        if ordinal is not None:
            self.scroll_to_center_ordinal(ordinal)
        self.active_block_changed.emit(evidence_block_id)
        self.status_changed.emit()
        self.update()

    def reveal_created_evidence_block(
        self,
        block: EvidenceBlock,
        *,
        source_action: str = "search_drop",
    ) -> None:
        if self.dataset_id is None:
            return
        if self._model.source_thread_id != block.source_thread_id:
            self.load_source_thread(block.source_thread_id, source_action=source_action)
        elif self._model.overlay_for_block(block.evidence_block_id) is None:
            self._model.append_or_update_evidence_block(block)
        self._model.show_evidence_block(block.evidence_block_id)
        ordinal = self._model.ordinal_for_message_id(block.core_hit_message_id)
        if ordinal is not None:
            self.scroll_to_center_ordinal(ordinal)
        self.update()

    def hide_evidence_block(self, evidence_block_id: int) -> None:
        block = evidence_blocks.get_evidence_block(self.conn, evidence_block_id)
        if block is not None:
            if self._model.source_thread_id != block.source_thread_id:
                self.load_source_thread(block.source_thread_id, source_action="evidence_block_hide")
            elif self._model.overlay_for_block(evidence_block_id) is None:
                self._model.append_or_update_evidence_block(block)
        self._model.hide_evidence_block(evidence_block_id)
        self.active_block_changed.emit(self._model.active_evidence_block_id)
        self.status_changed.emit()
        self.update()

    def show_evidence_block(self, evidence_block_id: int) -> None:
        block = evidence_blocks.get_evidence_block(self.conn, evidence_block_id)
        if block is not None:
            if self._model.source_thread_id != block.source_thread_id:
                self.load_source_thread(block.source_thread_id, source_action="evidence_block_show")
            elif self._model.overlay_for_block(evidence_block_id) is None:
                self._model.append_or_update_evidence_block(block)
        self._model.show_evidence_block(evidence_block_id)
        self.status_changed.emit()
        self.update()

    def is_evidence_block_hidden(self, evidence_block_id: int) -> bool:
        return self._model.is_evidence_block_hidden(evidence_block_id)

    def scroll_to_offset(self, offset: float) -> None:
        if self._height_index is None:
            return
        max_scroll = max(0.0, self._height_index.total_height() - self.height())
        self._scroll_offset_y = max(0.0, min(offset, max_scroll))
        self._sync_scrollbar()
        self._refresh_visible_window(force_remeasure=True)
        self.update()

    def reveal_active_evidence_block(self) -> None:
        overlay = self._model.active_overlay()
        if overlay is None:
            return
        ordinal = self._model.ordinal_for_message_id(overlay.core_hit_message_id)
        if ordinal is not None:
            self.scroll_to_center_ordinal(ordinal)

    def create_evidence_block_for_message(
        self,
        message_id: str,
        category_id: int | None = None,
        *,
        source_action: str = "virtual_create",
    ) -> EvidenceBlock | None:
        if self.dataset_id is None or self._model.source_thread_id is None:
            return None
        ordinal = self._model.ordinal_for_message_id(message_id)
        if ordinal is None:
            return None
        return self._create_evidence_block_at_ordinal(
            ordinal,
            category_id=category_id,
            source_action=source_action,
        )

    def create_evidence_block_from_viewport_center(
        self,
        category_id: int | None = None,
        *,
        source_action: str = "viewport_center",
    ) -> EvidenceBlock | None:
        ordinal = self.viewport_center_ordinal()
        if ordinal is None:
            return None
        return self._create_evidence_block_at_ordinal(
            ordinal,
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
        if self.dataset_id is None or self._model.source_thread_id is None:
            return None
        hit_index = self._model.ordinal_for_message_id(hit_message_id)
        relevant_start = self._model.ordinal_for_message_id(relevant_start_message_id)
        relevant_end = self._model.ordinal_for_message_id(relevant_end_message_id)
        context_start = self._model.ordinal_for_message_id(leading_context_start_message_id)
        context_end = self._model.ordinal_for_message_id(trailing_context_end_message_id)
        if None in {hit_index, relevant_start, relevant_end, context_start, context_end}:
            return None
        message_count = self._model.message_count
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
            source_thread_id=self._model.source_thread_id,
            title=title,
            summary=summary,
            core_hit_message_id=hit_message_id,
            message_count=message_count,
            context_start_slot=context_start,
            relevant_start_slot=relevant_start,
            relevant_end_slot=relevant_end + 1,
            context_end_slot=context_end + 1,
            highlighted_message_ids=[hit_message_id],
            created_by=CREATED_BY_CONVERSATIONAL_ANSWER,
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
                "source_thread_id": self._model.source_thread_id,
            },
            dataset_id=self.dataset_id,
        )
        self._model.append_or_update_evidence_block(block)
        self.focus_message(hit_message_id, source_action=source_action)
        self.evidence_block_created.emit(block.evidence_block_id)
        return block

    def viewport_center_ordinal(self) -> int | None:
        if self._height_index is None or self._model.message_count <= 0:
            return None
        ordinal = self._ordinal_at_content_y(self._viewport_center_content_y())
        return max(0, min(int(ordinal), self._model.message_count - 1))

    def _viewport_center_screen_y(self) -> float:
        return float(self.height()) / 2.0

    def _viewport_center_content_y(self) -> float:
        return self._scroll_offset_y + self._viewport_center_screen_y()

    def evidence_block_at_viewport_center(self):
        ordinal = self.viewport_center_ordinal()
        if ordinal is None:
            return None
        return self._model.overlay_containing_ordinal(ordinal)

    def prompt_delete_evidence_block_at_viewport_center(self) -> None:
        overlay = self.evidence_block_at_viewport_center()
        if overlay is None:
            QMessageBox.information(
                self,
                "Delete evidence block",
                "No evidence block contains the center marker.",
            )
            return
        self._delete_preview_block_id = overlay.evidence_block_id
        self.update()
        QTimer.singleShot(0, self, lambda: self._finish_delete_prompt(overlay.evidence_block_id))

    def _finish_delete_prompt(self, evidence_block_id: int) -> None:
        overlay = self._model.overlay_for_block(evidence_block_id)
        slot_label = "—"
        if overlay is not None:
            slot_label = (
                f"{overlay.context_start_slot}–{max(overlay.context_start_slot, overlay.context_end_slot - 1)}"
            )
        reply = QMessageBox.question(
            self,
            "Delete evidence block?",
            f"Delete evidence block #{evidence_block_id} (messages {slot_label})?\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        self._delete_preview_block_id = None
        self.update()
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._delete_evidence_block(evidence_block_id)

    def resizeEvent(self, event) -> None:
        if self._height_index is not None:
            self._anchor_scroll_on_resize = self._scroll_offset_y
            style = self._renderer.style_for_width(max(self.width(), 320))
            self._height_index.invalidate_all(default_height=self._renderer.estimate_height(style))
        bar_width = self._scroll_bar.sizeHint().width()
        self._scroll_bar.setGeometry(
            max(0, self.width() - bar_width),
            0,
            bar_width,
            self.height(),
        )
        super().resizeEvent(event)
        self._sync_scrollbar()
        self._refresh_visible_window(force_remeasure=True)
        if self._anchor_scroll_on_resize is not None:
            self.scroll_to_offset(self._anchor_scroll_on_resize)
            self._anchor_scroll_on_resize = None

    def wheelEvent(self, event: QWheelEvent) -> None:
        delta = event.angleDelta().y()
        if delta == 0:
            return
        step = -delta / 120.0 * 48.0
        self.scroll_to_offset(self._scroll_offset_y + step)

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#ffffff"))
        if self._height_index is None or self._model.message_count <= 0:
            painter.setPen("#666666")
            painter.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), "Select a source thread")
            return
        style = self._renderer.style_for_width(max(self.width(), 320))
        delete_preview_overlay = (
            self._model.overlay_for_block(self._delete_preview_block_id)
            if self._delete_preview_block_id is not None
            else None
        )
        painted_column_headers = False
        for layout in self._layout_rects:
            message = self._model.message_at(layout.ordinal)
            if message is None:
                continue
            screen_top = int(layout.top - self._scroll_offset_y)
            if screen_top > self.height() or screen_top + layout.height < 0:
                continue
            in_delete_preview = (
                delete_preview_overlay is not None
                and delete_preview_overlay.context_start_slot
                <= layout.ordinal
                < delete_preview_overlay.context_end_slot
            )
            if in_delete_preview and delete_preview_overlay is not None:
                preview_zone = zone_for_ordinal(delete_preview_overlay, layout.ordinal)
                zone = preview_zone or self._model.message_zone(layout.ordinal)
                if preview_zone == "relevant":
                    background = DELETE_PREVIEW_RELEVANT_FILL
                elif preview_zone == "context":
                    background = DELETE_PREVIEW_CONTEXT_FILL
                else:
                    background = DELETE_PREVIEW_CONTEXT_FILL
                is_delete_preview = True
                is_highlighted = False
            else:
                zone = self._model.message_zone(layout.ordinal)
                is_highlighted = self._model.message_is_highlighted_in_any_block(message.message_id)
                background = None
                if zone == "relevant":
                    background = HIGHLIGHT_FILL if is_highlighted else RELEVANT_FILL
                elif zone == "context":
                    background = CONTEXT_FILL
                is_delete_preview = False
            shifted = layout.__class__(
                ordinal=layout.ordinal,
                top=float(screen_top),
                height=layout.height,
                content_left=layout.content_left,
                content_width=layout.content_width,
            )
            self._renderer.paint_message(
                painter,
                message,
                shifted,
                style,
                background_color=background,
                is_context=zone == "context",
                is_relevant=zone == "relevant",
                is_highlighted=is_highlighted,
                is_delete_preview=is_delete_preview,
            )
            relevant_overlays = self._model.overlays_for_relevant_ordinal(layout.ordinal)
            overlay_count = len(relevant_overlays)
            for overlay_index, overlay in enumerate(relevant_overlays):
                if not painted_column_headers and overlay_index == 0:
                    self._renderer.paint_annotation_column_headers(
                        painter,
                        hit_rect=hit_header_rect(shifted),
                        highlight_rect=highlight_header_rect(shifted),
                    )
                    painted_column_headers = True
                self._renderer.paint_hit_marker(
                    painter,
                    hit_icon_rect(shifted, overlay_index, overlay_count),
                    active=message.message_id == overlay.core_hit_message_id,
                )
                self._renderer.paint_highlight_marker(
                    painter,
                    highlight_icon_rect(shifted, overlay_index, overlay_count),
                    active=message.message_id in overlay.highlighted_message_ids,
                )
        for overlay in reversed(self._model.block_overlays()):
            for handle in boundary_handles_for_layouts(overlay, self._screen_layouts()):
                drag_active = (
                    self._drag_target is not None
                    and self._drag_target == (handle.boundary_name, handle.evidence_block_id)
                )
                self._renderer.paint_boundary_handle(
                    painter,
                    label=handle.label,
                    rect=handle.rect,
                    active=drag_active,
                )
        self._paint_viewport_center_marker(painter)

    def _paint_viewport_center_marker(self, painter: QPainter) -> None:
        center_y = int(self._viewport_center_screen_y())
        bar_width = self._scroll_bar.width() if self._scroll_bar.isVisible() else 0
        left = 8
        right = max(left + 40, self.width() - bar_width - 8)
        marker_color = QColor(CENTER_MARKER_COLOR)
        pen = QPen(marker_color)
        pen.setStyle(Qt.PenStyle.DashLine)
        pen.setWidth(1)
        painter.setPen(pen)
        painter.drawLine(left + 12, center_y, right, center_y)
        caret = QPainterPath()
        caret_size = 7
        caret.moveTo(left, center_y - caret_size)
        caret.lineTo(left + caret_size + 4, center_y)
        caret.lineTo(left, center_y + caret_size)
        caret.closeSubpath()
        painter.fillPath(caret, marker_color)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        point = event.position().toPoint()
        drag_target = self._boundary_at_point(point)
        if drag_target is not None:
            self._drag_target = drag_target
            return
        for layout in self._screen_layouts():
            message = self._model.message_at(layout.ordinal)
            if message is None:
                continue
            relevant_overlays = self._model.overlays_for_relevant_ordinal(layout.ordinal)
            overlay_count = len(relevant_overlays)
            for overlay_index, overlay in enumerate(relevant_overlays):
                if hit_icon_rect(layout, overlay_index, overlay_count).contains(point):
                    self._persist_hit_message(overlay.evidence_block_id, message.message_id)
                    return
                if highlight_icon_rect(layout, overlay_index, overlay_count).contains(point):
                    self._persist_highlight_toggle(overlay.evidence_block_id, message.message_id)
                    return

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_target is None or self._height_index is None:
            return
        boundary_name, evidence_block_id = self._drag_target
        overlay = self._model.overlay_for_block(evidence_block_id)
        if overlay is None:
            return
        content_y = event.position().y() + self._scroll_offset_y
        ordinal = self._ordinal_at_content_y(content_y)
        resolved = resolve_boundary_move(
            boundary_name,
            ordinal,
            message_count=self._model.message_count,
            context_start=overlay.context_start_slot,
            relevant_start=overlay.relevant_start_slot,
            relevant_end=overlay.relevant_end_slot,
            context_end=overlay.context_end_slot,
        )
        if resolved is None:
            return
        self._model.update_overlay_slots(
            evidence_block_id,
            context_start=resolved[0],
            relevant_start=resolved[1],
            relevant_end=resolved[2],
            context_end=resolved[3],
        )
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._drag_target is None:
            return
        _boundary_name, evidence_block_id = self._drag_target
        overlay = self._model.overlay_for_block(evidence_block_id)
        if overlay is not None:
            self._persist_overlay_slots(overlay)
        self._drag_target = None
        self.update()
        del event

    def _create_evidence_block_at_ordinal(
        self,
        ordinal: int,
        *,
        category_id: int | None = None,
        source_action: str,
    ) -> EvidenceBlock | None:
        if self.dataset_id is None or self._model.source_thread_id is None:
            return None
        message_id = self._model.message_id_for_ordinal(ordinal)
        if message_id is None:
            return None
        if category_id is None:
            category_id = evidence_blocks.ensure_uncategorized_category(
                self.conn,
                self.logger,
                self.dataset_id,
            ).category_id
        slots = default_slots_for_hit_index_with_context(
            self._model.message_count,
            ordinal,
        )
        block = evidence_blocks.create_evidence_block(
            self.conn,
            self.logger,
            dataset_id=self.dataset_id,
            category_id=category_id,
            source_thread_id=self._model.source_thread_id,
            title=f"Evidence at {ordinal}",
            core_hit_message_id=message_id,
            message_count=self._model.message_count,
            context_start_slot=slots[0],
            relevant_start_slot=slots[1],
            relevant_end_slot=slots[2],
            context_end_slot=slots[3],
        )
        self._model.append_or_update_evidence_block(block)
        self.update()
        self.evidence_block_created.emit(block.evidence_block_id)
        self.active_block_changed.emit(block.evidence_block_id)
        self.status_changed.emit()
        self.logger.info(
            component=_LOG_COMPONENT,
            operation="evidence_block_created",
            message="Created evidence block from virtual transcript",
            details={
                "evidence_block_id": block.evidence_block_id,
                "ordinal": ordinal,
                "source_action": source_action,
            },
            dataset_id=self.dataset_id,
        )
        return block

    def _delete_evidence_block(self, evidence_block_id: int) -> None:
        if self.dataset_id is None:
            return
        evidence_blocks.delete_evidence_block(
            self.conn,
            self.logger,
            evidence_block_id=evidence_block_id,
        )
        self._model.remove_evidence_block(evidence_block_id)
        if self._model.active_evidence_block_id is None:
            self.active_block_changed.emit(None)
        self.evidence_block_deleted.emit(evidence_block_id)
        self.status_changed.emit()
        self.update()
        self.logger.info(
            component=_LOG_COMPONENT,
            operation="evidence_block_deleted",
            message="Deleted evidence block from virtual transcript",
            details={"evidence_block_id": evidence_block_id},
            dataset_id=self.dataset_id,
        )

    def _persist_overlay_slots(self, overlay) -> None:
        if self.dataset_id is None:
            return
        block = evidence_blocks.update_evidence_block_slots(
            self.conn,
            self.logger,
            evidence_block_id=overlay.evidence_block_id,
            message_count=self._model.message_count,
            context_start_slot=overlay.context_start_slot,
            relevant_start_slot=overlay.relevant_start_slot,
            relevant_end_slot=overlay.relevant_end_slot,
            context_end_slot=overlay.context_end_slot,
        )
        self._model.append_or_update_evidence_block(block)
        self.status_changed.emit()

    def _persist_hit_message(self, evidence_block_id: int, message_id: str) -> None:
        if self.dataset_id is None:
            return
        block = evidence_blocks.update_evidence_block_anchor(
            self.conn,
            self.logger,
            evidence_block_id=evidence_block_id,
            core_hit_message_id=message_id,
        )
        self._model.append_or_update_evidence_block(block)
        self.status_changed.emit()
        self.update()

    def _persist_highlight_toggle(self, evidence_block_id: int, message_id: str) -> None:
        if self.dataset_id is None:
            return
        self._model.toggle_overlay_highlight(evidence_block_id, message_id)
        updated = self._model.overlay_for_block(evidence_block_id)
        if updated is None:
            return
        block = evidence_blocks.set_evidence_block_highlights(
            self.conn,
            self.logger,
            evidence_block_id=updated.evidence_block_id,
            highlighted_message_ids=sorted(updated.highlighted_message_ids),
        )
        self._model.append_or_update_evidence_block(block)
        self.status_changed.emit()
        self.update()

    def _boundary_at_point(self, point) -> tuple[str, int] | None:
        boundary_order = (
            BOUNDARY_RELEVANT_START,
            BOUNDARY_RELEVANT_END,
            BOUNDARY_CONTEXT_START,
            BOUNDARY_CONTEXT_END,
        )
        boundary_slots = {
            BOUNDARY_CONTEXT_START: lambda overlay: overlay.context_start_slot,
            BOUNDARY_CONTEXT_END: lambda overlay: overlay.context_end_slot,
            BOUNDARY_RELEVANT_START: lambda overlay: overlay.relevant_start_slot,
            BOUNDARY_RELEVANT_END: lambda overlay: overlay.relevant_end_slot,
        }
        for overlay in reversed(self._model.block_overlays()):
            for boundary_name in boundary_order:
                ordinal = boundary_slots[boundary_name](overlay)
                layout = next(
                    (item for item in self._screen_layouts() if item.ordinal == ordinal),
                    None,
                )
                if layout is None:
                    continue
                for handle in boundary_handles_for_layouts(overlay, [layout]):
                    if handle.boundary_name != boundary_name:
                        continue
                    expanded = handle.rect.adjusted(-4, -6, 4, 6)
                    if expanded.contains(point):
                        return boundary_name, overlay.evidence_block_id
        return None

    def _on_scrollbar_changed(self, value: int) -> None:
        self._scroll_offset_y = float(value)
        self._refresh_visible_window(force_remeasure=False)
        self.update()
        self.status_changed.emit()

    def _sync_scrollbar(self) -> None:
        if self._height_index is None:
            self._scroll_bar.hide()
            return
        total = int(self._height_index.total_height())
        page = max(1, self.height())
        maximum = max(0, total - page)
        self._scroll_bar.setRange(0, maximum)
        self._scroll_bar.setPageStep(page)
        self._scroll_bar.blockSignals(True)
        self._scroll_bar.setValue(int(self._scroll_offset_y))
        self._scroll_bar.blockSignals(False)
        self._scroll_bar.show()

    def _refresh_visible_window(self, *, force_remeasure: bool) -> None:
        del force_remeasure
        if self._height_index is None or self._model.source_thread_id is None:
            self._layout_rects = []
            return
        style = self._renderer.style_for_width(max(self.width(), 320))
        first_ordinal = self._height_index.ordinal_for_offset(self._scroll_offset_y)
        last_ordinal = self._height_index.ordinal_for_offset(
            self._scroll_offset_y + max(self.height(), 1)
        )
        start = max(0, first_ordinal - WINDOW_OVERSCAN)
        end = min(self._model.message_count, last_ordinal + WINDOW_OVERSCAN + 1)
        messages = self._model.messages_for_range(start, end)
        for index, message in enumerate(messages):
            ordinal = start + index
            measured = self._renderer.measure_message(message, style)
            self._height_index.set_height(ordinal, measured)
        start_y = self._height_index.offset_for_ordinal(start)
        layouts, _ = self._renderer.layout_messages(
            messages,
            start_ordinal=start,
            start_y=start_y,
            style=style,
        )
        self._layout_rects = layouts
        self._visible_start_ordinal = start
        self._visible_end_ordinal = max(start, end - 1)
        self._sync_scrollbar()

    def _screen_layouts(self):
        return [
            layout.__class__(
                ordinal=layout.ordinal,
                top=float(layout.top - self._scroll_offset_y),
                height=layout.height,
                content_left=layout.content_left,
                content_width=layout.content_width,
            )
            for layout in self._layout_rects
        ]

    def _ordinal_at_content_y(self, content_y: float) -> int:
        for layout in self._layout_rects:
            if layout.top <= content_y < layout.top + layout.height:
                return layout.ordinal
        if self._layout_rects:
            best_ordinal = self._layout_rects[0].ordinal
            best_distance = float("inf")
            for layout in self._layout_rects:
                center = layout.top + (layout.height / 2.0)
                distance = abs(center - content_y)
                if distance < best_distance:
                    best_distance = distance
                    best_ordinal = layout.ordinal
            return best_ordinal
        if self._height_index is None:
            return 0
        return self._height_index.ordinal_for_offset(content_y)
