"""Virtualized SQL-backed transcript widget (Gen 3)."""

from __future__ import annotations

import sqlite3

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QWheelEvent
from PySide6.QtWidgets import QScrollBar, QWidget

from message_evidence_workstation.db import evidence_blocks
from message_evidence_workstation.domain.models import EvidenceBlock
from message_evidence_workstation.domain.slots import (
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
RELEVANT_FILL_INACTIVE = "#f3f7ef"


class VirtualTranscriptWidget(QWidget):
    """Paint-based virtual transcript surface."""

    thread_loaded = Signal(str, int)
    evidence_block_created = Signal(int)
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
        self._drag_boundary: str | None = None
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

    def set_dataset(self, dataset_id: int | None) -> None:
        self.dataset_id = dataset_id
        self._model.set_dataset(dataset_id)
        self._height_index = None
        self._scroll_offset_y = 0.0
        self._layout_rects = []
        self.update()

    def load_source_thread(self, source_thread_id: str) -> None:
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
        return self.scroll_to_ordinal(ordinal)

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
            self.scroll_to_ordinal(ordinal)

    def create_evidence_block_for_message(
        self,
        message_id: str,
        *,
        source_action: str = "virtual_create",
    ) -> EvidenceBlock | None:
        if self.dataset_id is None or self._model.source_thread_id is None:
            return None
        ordinal = self._model.ordinal_for_message_id(message_id)
        if ordinal is None:
            return None
        return self._create_evidence_block_at_ordinal(ordinal, source_action=source_action)

    def create_evidence_block_from_viewport_center(
        self,
        *,
        source_action: str = "viewport_center",
    ) -> EvidenceBlock | None:
        if self._height_index is None:
            return None
        center_offset = self._scroll_offset_y + self.height() / 2.0
        ordinal = self._height_index.ordinal_for_offset(center_offset)
        return self._create_evidence_block_at_ordinal(ordinal, source_action=source_action)

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
        overlay = self._model.active_overlay()
        painted_column_headers = False
        for layout in self._layout_rects:
            message = self._model.message_at(layout.ordinal)
            if message is None:
                continue
            screen_top = int(layout.top - self._scroll_offset_y)
            if screen_top > self.height() or screen_top + layout.height < 0:
                continue
            background = None
            zone = None
            if overlay is not None:
                zone = zone_for_ordinal(overlay, layout.ordinal)
                if zone == "relevant":
                    background = RELEVANT_FILL if overlay.is_active else RELEVANT_FILL_INACTIVE
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
            )
            if overlay is not None and overlay.is_active:
                if zone == "relevant":
                    if not painted_column_headers:
                        self._renderer.paint_annotation_column_headers(
                            painter,
                            hit_rect=hit_header_rect(shifted),
                            highlight_rect=highlight_header_rect(shifted),
                        )
                        painted_column_headers = True
                    self._renderer.paint_hit_marker(
                        painter,
                        hit_icon_rect(shifted),
                        active=message.message_id == overlay.core_hit_message_id,
                    )
                    self._renderer.paint_highlight_marker(
                        painter,
                        highlight_icon_rect(shifted),
                        active=message.message_id in overlay.highlighted_message_ids,
                    )
        if overlay is not None and overlay.is_active:
            for handle in boundary_handles_for_layouts(overlay, self._screen_layouts()):
                self._renderer.paint_boundary_handle(
                    painter,
                    label=handle.label,
                    rect=handle.rect,
                    active=self._drag_boundary == handle.boundary_name,
                )

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        overlay = self._model.active_overlay()
        if overlay is None or not overlay.is_active:
            return
        point = event.position().toPoint()
        for handle in boundary_handles_for_layouts(overlay, self._screen_layouts()):
            if handle.rect.contains(point):
                self._drag_boundary = handle.boundary_name
                return
        for layout in self._screen_layouts():
            message = self._model.message_at(layout.ordinal)
            if message is None:
                continue
            if zone_for_ordinal(overlay, layout.ordinal) != "relevant":
                continue
            if hit_icon_rect(layout).contains(point):
                self._persist_hit_message(message.message_id)
                return
            if highlight_icon_rect(layout).contains(point):
                self._persist_highlight_toggle(message.message_id)
                return

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_boundary is None or self._height_index is None:
            return
        overlay = self._model.active_overlay()
        if overlay is None:
            return
        content_y = event.position().y() + self._scroll_offset_y
        ordinal = self._ordinal_at_content_y(content_y)
        resolved = resolve_boundary_move(
            self._drag_boundary,
            ordinal,
            message_count=self._model.message_count,
            context_start=overlay.context_start_slot,
            relevant_start=overlay.relevant_start_slot,
            relevant_end=overlay.relevant_end_slot,
            context_end=overlay.context_end_slot,
        )
        if resolved is None:
            return
        self._model.update_active_overlay_slots(
            context_start=resolved[0],
            relevant_start=resolved[1],
            relevant_end=resolved[2],
            context_end=resolved[3],
        )
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._drag_boundary is None:
            return
        overlay = self._model.active_overlay()
        if overlay is not None:
            self._persist_active_overlay_slots(overlay)
        self._drag_boundary = None
        self.update()
        del event

    def _create_evidence_block_at_ordinal(
        self,
        ordinal: int,
        *,
        source_action: str,
    ) -> EvidenceBlock | None:
        if self.dataset_id is None or self._model.source_thread_id is None:
            return None
        message_id = self._model.message_id_for_ordinal(ordinal)
        if message_id is None:
            return None
        category = evidence_blocks.ensure_uncategorized_category(
            self.conn,
            self.logger,
            self.dataset_id,
        )
        slots = default_slots_for_hit_index_with_context(
            self._model.message_count,
            ordinal,
        )
        block = evidence_blocks.create_evidence_block(
            self.conn,
            self.logger,
            dataset_id=self.dataset_id,
            category_id=category.category_id,
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
        self.scroll_to_ordinal(ordinal)
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

    def _persist_active_overlay_slots(self, overlay) -> None:
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

    def _persist_hit_message(self, message_id: str) -> None:
        overlay = self._model.active_overlay()
        if overlay is None or self.dataset_id is None:
            return
        block = evidence_blocks.update_evidence_block_anchor(
            self.conn,
            self.logger,
            evidence_block_id=overlay.evidence_block_id,
            core_hit_message_id=message_id,
        )
        self._model.append_or_update_evidence_block(block)
        self.status_changed.emit()
        self.update()

    def _persist_highlight_toggle(self, message_id: str) -> None:
        overlay = self._model.active_overlay()
        if overlay is None or self.dataset_id is None:
            return
        self._model.toggle_active_overlay_highlight(message_id)
        updated = self._model.active_overlay()
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
        if force_remeasure:
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
        if self._height_index is None:
            return 0
        return self._height_index.ordinal_for_offset(content_y)
