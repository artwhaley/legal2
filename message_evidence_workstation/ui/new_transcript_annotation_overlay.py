"""Margin overlay for evidence boundaries and hit/highlight controls."""

from __future__ import annotations

from dataclasses import dataclass

from shiboken6 import isValid
from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QWidget

from message_evidence_workstation.domain.slots import (
    ALL_BOUNDARIES,
    BOUNDARY_CONTEXT_END,
    BOUNDARY_CONTEXT_START,
    BOUNDARY_RELEVANT_END,
    BOUNDARY_RELEVANT_START,
    resolve_boundary_move,
)

HANDLE_HEIGHT = 8
MARGIN_WIDTH = 72
HIT_RADIUS = 7
HIGHLIGHT_SIZE = 12


@dataclass(slots=True)
class TranscriptEvidenceOverlay:
    evidence_block_id: int
    context_start_slot: int
    relevant_start_slot: int
    relevant_end_slot: int
    context_end_slot: int
    core_hit_message_id: str
    highlighted_message_ids: frozenset[str]
    is_active: bool = False


class TranscriptAnnotationOverlay(QWidget):
    boundary_moved = Signal(str, int)
    boundary_released = Signal(str, int)
    hit_message_selected = Signal(str)
    highlight_toggled = Signal(str)

    def __init__(self, text_edit, owner, parent: QWidget | None = None) -> None:
        self._text_edit = text_edit
        self._owner = owner
        self._slot_y_for_slot: dict[int, int] = {}
        self._message_count = 0
        self._overlays: list[TranscriptEvidenceOverlay] = []
        self._drag_boundary: str | None = None
        super().__init__(text_edit)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.hide()
        self.setMouseTracking(True)
        text_edit.viewport().installEventFilter(self)
        text_edit.verticalScrollBar().valueChanged.connect(self._sync_geometry)
        text_edit.installEventFilter(self)

    def set_geometry_to_viewport(self) -> None:
        self._sync_geometry()

    def _sync_geometry(self, *_args) -> None:
        text_edit = getattr(self, "_text_edit", None)
        if text_edit is None or not isValid(text_edit):
            return
        viewport = text_edit.viewport()
        top_left = viewport.mapTo(text_edit, viewport.rect().topLeft())
        self.setGeometry(
            top_left.x() + max(0, viewport.width() - MARGIN_WIDTH),
            top_left.y(),
            MARGIN_WIDTH,
            viewport.height(),
        )
        if self.isHidden() and self._overlays:
            self.show()
        self.raise_()
        self.update()

    def eventFilter(self, watched, event) -> bool:
        text_edit = getattr(self, "_text_edit", None)
        if text_edit is None or not isValid(text_edit):
            return super().eventFilter(watched, event)
        viewport = text_edit.viewport()
        if watched in (text_edit, viewport):
            if event.type() in (event.Type.Resize, event.Type.Show):
                self._sync_geometry()
        return super().eventFilter(watched, event)

    def set_slot_positions(self, slot_y: dict[int, int], *, message_count: int) -> None:
        self._slot_y_for_slot = dict(slot_y)
        self._message_count = message_count
        self.set_geometry_to_viewport()
        self.update()

    def set_overlays(self, overlays: list[TranscriptEvidenceOverlay]) -> None:
        self._overlays = list(overlays)
        if not self._overlays:
            self.hide()
            self.update()
            return
        self.set_geometry_to_viewport()
        self.update()

    def _active_overlay(self) -> TranscriptEvidenceOverlay | None:
        for overlay in self._overlays:
            if overlay.is_active:
                return overlay
        return None

    def _boundary_at(self, pos: QPoint) -> str | None:
        for boundary_name in ALL_BOUNDARIES:
            slot = self._slot_for_boundary(boundary_name)
            if slot is None:
                continue
            y = self._slot_y_for_slot.get(slot)
            if y is None:
                continue
            if abs(pos.y() - y) <= HANDLE_HEIGHT:
                return boundary_name
        return None

    def _slot_for_boundary(self, boundary_name: str) -> int | None:
        overlay = self._active_overlay()
        if overlay is None:
            return None
        return {
            BOUNDARY_CONTEXT_START: overlay.context_start_slot,
            BOUNDARY_RELEVANT_START: overlay.relevant_start_slot,
            BOUNDARY_RELEVANT_END: overlay.relevant_end_slot,
            BOUNDARY_CONTEXT_END: overlay.context_end_slot,
        }.get(boundary_name)

    def _hit_control_at(self, pos: QPoint) -> str | None:
        overlay = self._active_overlay()
        if overlay is None:
            return None
        for ordinal in range(overlay.relevant_start_slot, overlay.relevant_end_slot):
            y = self._slot_y_for_slot.get(ordinal)
            if y is None:
                continue
            center = QPoint(HIT_RADIUS + 4, y + HIT_RADIUS + 4)
            if (pos - center).manhattanLength() <= HIT_RADIUS + 4:
                return self._message_id_for_ordinal(ordinal)
        return None

    def _highlight_control_at(self, pos: QPoint) -> str | None:
        overlay = self._active_overlay()
        if overlay is None:
            return None
        for ordinal in range(overlay.relevant_start_slot, overlay.relevant_end_slot):
            y = self._slot_y_for_slot.get(ordinal)
            if y is None:
                continue
            center = QPoint(MARGIN_WIDTH - HIGHLIGHT_SIZE - 4, y + HIGHLIGHT_SIZE // 2)
            rect = QRect(
                center.x() - HIGHLIGHT_SIZE // 2,
                center.y() - HIGHLIGHT_SIZE // 2,
                HIGHLIGHT_SIZE,
                HIGHLIGHT_SIZE,
            )
            if rect.contains(pos):
                return self._message_id_for_ordinal(ordinal)
        return None

    def _message_id_for_ordinal(self, ordinal: int) -> str | None:
        return self._owner.thread_ordinal_to_message_id.get(ordinal)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        hit_id = self._hit_control_at(event.position().toPoint())
        if hit_id is not None:
            self.hit_message_selected.emit(hit_id)
            return
        highlight_id = self._highlight_control_at(event.position().toPoint())
        if highlight_id is not None:
            self.highlight_toggled.emit(highlight_id)
            return
        boundary = self._boundary_at(event.position().toPoint())
        if boundary is not None:
            self._drag_boundary = boundary

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_boundary is None:
            return
        slot = self._nearest_slot_for_y(int(event.position().y()))
        self.boundary_moved.emit(self._drag_boundary, slot)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._drag_boundary is not None:
            slot = self._nearest_slot_for_y(int(event.position().y()))
            self.boundary_released.emit(self._drag_boundary, slot)
            self._drag_boundary = None

    def _nearest_slot_for_y(self, y: int) -> int:
        if not self._slot_y_for_slot:
            return 0
        best_slot = 0
        best_distance = 10**9
        for slot, slot_y in self._slot_y_for_slot.items():
            distance = abs(slot_y - y)
            if distance < best_distance:
                best_distance = distance
                best_slot = slot
        return best_slot

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        overlay = self._active_overlay()
        if overlay is None:
            return
        pen = QPen(QColor("#4a6741"))
        pen.setWidth(2)
        painter.setPen(pen)
        for boundary_name in ALL_BOUNDARIES:
            slot = self._slot_for_boundary(boundary_name)
            if slot is None:
                continue
            y = self._slot_y_for_slot.get(slot)
            if y is None:
                continue
            painter.drawLine(0, y, MARGIN_WIDTH, y)
            painter.fillRect(QRect(0, y - HANDLE_HEIGHT // 2, MARGIN_WIDTH, HANDLE_HEIGHT), QColor("#8fbc8f"))

        for ordinal in range(overlay.relevant_start_slot, overlay.relevant_end_slot):
            message_id = self._message_id_for_ordinal(ordinal)
            if message_id is None:
                continue
            y = self._slot_y_for_slot.get(ordinal)
            if y is None:
                continue
            is_hit = message_id == overlay.core_hit_message_id
            is_highlight = message_id in overlay.highlighted_message_ids
            hit_center = QPoint(HIT_RADIUS + 4, y + HIT_RADIUS + 4)
            painter.setPen(QPen(QColor("#333333")))
            painter.setBrush(QColor("#ffffff") if not is_hit else QColor("#2e7d32"))
            painter.drawEllipse(
                hit_center.x() - HIT_RADIUS,
                hit_center.y() - HIT_RADIUS,
                HIT_RADIUS * 2,
                HIT_RADIUS * 2,
            )
            if is_hit:
                painter.setPen(QPen(QColor("#ffffff")))
                painter.drawLine(hit_center.x() - 3, hit_center.y(), hit_center.x() + 3, hit_center.y())
                painter.drawLine(hit_center.x(), hit_center.y() - 3, hit_center.x(), hit_center.y() + 3)

            box = QRect(
                MARGIN_WIDTH - HIGHLIGHT_SIZE - 8,
                y + 2,
                HIGHLIGHT_SIZE,
                HIGHLIGHT_SIZE,
            )
            painter.setPen(QPen(QColor("#666666")))
            painter.setBrush(QColor("#fff59d") if is_highlight else QColor("#ffffff"))
            painter.drawRect(box)
            if is_highlight:
                painter.drawLine(box.left() + 3, box.center().y(), box.left() + 5, box.bottom() - 3)
                painter.drawLine(box.left() + 5, box.bottom() - 3, box.right() - 3, box.top() + 3)
