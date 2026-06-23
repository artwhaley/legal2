"""Shared evidence transcript model and reusable transcript surfaces."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import QAbstractListModel, QModelIndex, QObject, QPoint, QRect, QSize, Qt, Signal, Slot
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QListView,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from message_evidence_workstation.db import evidence_blocks, repositories
from message_evidence_workstation.domain.constants import (
    BOUNDARY_CONTEXT_END,
    BOUNDARY_CONTEXT_START,
    BOUNDARY_RELEVANT_END,
    BOUNDARY_RELEVANT_START,
)
from message_evidence_workstation.domain.models import EvidenceBlock, Message
from message_evidence_workstation.domain.slots import default_slots_for_hit_index

ENTRY_SEPARATOR = "separator"
ENTRY_MESSAGE = "message"
PAPER_BG = QColor("#f8f3e8")
PAGE_TEXT = QColor("#222222")
PAGE_META = QColor("#666666")
RULE_NEUTRAL = QColor("#d8cebd")
CONTEXT_LINE_COLOR = QColor("#0b6dd8")
RELEVANT_LINE_COLOR = QColor("#222222")
BOUNDARY_FAINT_ALPHA = 90
HIGHLIGHT_ICON_ON = QColor("#d09400")
HIGHLIGHT_ICON_OFF = QColor("#9a9a9a")
HIGHLIGHT_WASH = QColor("#fff5bf")
CORE_HIT_COLOR = QColor("#0b6dd8")

BOUNDARY_ACTIVE = "active"
BOUNDARY_INACTIVE = "inactive"


def _friendly_date_parts(timestamp: str) -> tuple[str, str]:
    try:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return timestamp, ""
    friendly_date = f"{dt.strftime('%B')} {dt.day}, {dt.year}"
    friendly_time = dt.strftime("%H:%M")
    return friendly_date, friendly_time


@dataclass(slots=True)
class TranscriptMessage:
    message_id: str
    timestamp: str
    friendly_date: str
    friendly_time: str
    sender_display: str
    body: str
    attachment_summary: str
    has_attachment: bool
    highlighted: bool = False
    is_core_hit: bool = False


@dataclass(slots=True)
class BlockOverlay:
    evidence_block_id: int
    context_start_slot: int
    relevant_start_slot: int
    relevant_end_slot: int
    context_end_slot: int
    core_hit_message_id: str
    highlighted_message_ids: frozenset[str]
    is_active: bool = False


class EvidenceTranscriptModel(QAbstractListModel):
    state_changed = Signal()

    EntryKindRole = int(Qt.ItemDataRole.UserRole) + 1
    SlotIndexRole = EntryKindRole + 1
    MessageIdRole = SlotIndexRole + 1
    FriendlyDateRole = MessageIdRole + 1
    FriendlyTimeRole = FriendlyDateRole + 1
    SenderRole = FriendlyTimeRole + 1
    BodyRole = SenderRole + 1
    AttachmentRole = BodyRole + 1
    HighlightedRole = AttachmentRole + 1
    CoreHitRole = HighlightedRole + 1
    ContextStartBoundaryRole = CoreHitRole + 1
    ContextEndBoundaryRole = ContextStartBoundaryRole + 1
    RelevantStartBoundaryRole = ContextEndBoundaryRole + 1
    RelevantEndBoundaryRole = RelevantStartBoundaryRole + 1

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._messages: list[TranscriptMessage] = []
        self._overlays: list[BlockOverlay] = []
        self._active_block_id: int | None = None
        self._draft_slots = (0, 0, 1, 1)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        if not self._messages:
            return 0
        return (len(self._messages) * 2) + 1

    def data(self, index: QModelIndex, role: int = int(Qt.ItemDataRole.DisplayRole)) -> object:
        if not index.isValid() or not (0 <= index.row() < self.rowCount()):
            return None
        visual_row = index.row()
        if self._is_separator_row(visual_row):
            slot_index = self._slot_index_for_separator_row(visual_row)
            if role == self.EntryKindRole:
                return ENTRY_SEPARATOR
            if role == self.SlotIndexRole:
                return slot_index
            if role == self.ContextStartBoundaryRole:
                return self._boundary_strength(BOUNDARY_CONTEXT_START, slot_index)
            if role == self.ContextEndBoundaryRole:
                return self._boundary_strength(BOUNDARY_CONTEXT_END, slot_index)
            if role == self.RelevantStartBoundaryRole:
                return self._boundary_strength(BOUNDARY_RELEVANT_START, slot_index)
            if role == self.RelevantEndBoundaryRole:
                return self._boundary_strength(BOUNDARY_RELEVANT_END, slot_index)
            return None

        message = self._messages[self._message_index_for_visual_row(visual_row)]
        if role == int(Qt.ItemDataRole.DisplayRole):
            return f"{message.sender_display}: {message.body}"
        if role == self.EntryKindRole:
            return ENTRY_MESSAGE
        if role == self.MessageIdRole:
            return message.message_id
        if role == self.FriendlyDateRole:
            return message.friendly_date
        if role == self.FriendlyTimeRole:
            return message.friendly_time
        if role == self.SenderRole:
            return message.sender_display
        if role == self.BodyRole:
            return message.body
        if role == self.AttachmentRole:
            return message.attachment_summary if message.has_attachment else ""
        if role == self.HighlightedRole:
            return message.highlighted
        if role == self.CoreHitRole:
            return message.is_core_hit
        return None

    def roleNames(self) -> dict[int, bytes]:
        return {
            self.EntryKindRole: b"entryKind",
            self.SlotIndexRole: b"slotIndex",
            self.MessageIdRole: b"messageId",
            self.FriendlyDateRole: b"friendlyDate",
            self.FriendlyTimeRole: b"friendlyTime",
            self.SenderRole: b"senderDisplay",
            self.BodyRole: b"body",
            self.AttachmentRole: b"attachmentSummary",
            self.HighlightedRole: b"highlighted",
            self.CoreHitRole: b"isCoreHit",
            self.ContextStartBoundaryRole: b"contextStartBoundary",
            self.ContextEndBoundaryRole: b"contextEndBoundary",
            self.RelevantStartBoundaryRole: b"relevantStartBoundary",
            self.RelevantEndBoundaryRole: b"relevantEndBoundary",
        }

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def load_messages(self, messages: list[Message]) -> None:
        transcript_messages: list[TranscriptMessage] = []
        for message in messages:
            friendly_date, friendly_time = _friendly_date_parts(message.timestamp)
            transcript_messages.append(
                TranscriptMessage(
                    message_id=message.message_id,
                    timestamp=message.timestamp,
                    friendly_date=friendly_date,
                    friendly_time=friendly_time,
                    sender_display=message.sender_display,
                    body=message.body,
                    attachment_summary=message.attachment_summary,
                    has_attachment=message.has_attachment,
                )
            )
        self.beginResetModel()
        self._messages = transcript_messages
        self._overlays = []
        self._active_block_id = None
        if transcript_messages:
            self._draft_slots = default_slots_for_hit_index(len(transcript_messages), 0)
        else:
            self._draft_slots = (0, 0, 0, 0)
        self.endResetModel()
        self.state_changed.emit()

    def load_thread_blocks(
        self,
        messages: list[Message],
        blocks: list[EvidenceBlock],
        *,
        active_block_id: int | None = None,
    ) -> None:
        self.load_messages(messages)
        if not blocks:
            return
        self.beginResetModel()
        self._overlays = [
            BlockOverlay(
                evidence_block_id=block.evidence_block_id,
                context_start_slot=block.context_start_slot,
                relevant_start_slot=block.relevant_start_slot,
                relevant_end_slot=block.relevant_end_slot,
                context_end_slot=block.context_end_slot,
                core_hit_message_id=block.core_hit_message_id,
                highlighted_message_ids=block.highlighted_message_ids,
                is_active=block.evidence_block_id == active_block_id,
            )
            for block in blocks
        ]
        if active_block_id is None and self._overlays:
            self._overlays[0].is_active = True
            active_block_id = self._overlays[0].evidence_block_id
        self._active_block_id = active_block_id
        self._apply_overlay_state_to_messages()
        self.endResetModel()
        self.state_changed.emit()

    def set_active_block(self, evidence_block_id: int | None) -> None:
        self._active_block_id = evidence_block_id
        for overlay in self._overlays:
            overlay.is_active = overlay.evidence_block_id == evidence_block_id
        self._apply_overlay_state_to_messages()
        self._emit_all_separator_changes()
        self._emit_all_message_changes()
        self.state_changed.emit()

    def active_block_id(self) -> int | None:
        return self._active_block_id

    def active_slots(self) -> tuple[int, int, int, int]:
        overlay = self._active_overlay()
        if overlay is None:
            return self._draft_slots
        return (
            overlay.context_start_slot,
            overlay.relevant_start_slot,
            overlay.relevant_end_slot,
            overlay.context_end_slot,
        )

    def highlighted_message_ids(self) -> list[str]:
        overlay = self._active_overlay()
        if overlay is None:
            return [message.message_id for message in self._messages if message.highlighted]
        return sorted(overlay.highlighted_message_ids)

    @Slot(int)
    def toggle_highlight_row(self, visual_row: int) -> None:
        if self._is_separator_row(visual_row):
            return
        message_index = self._message_index_for_visual_row(visual_row)
        if not (0 <= message_index < len(self._messages)):
            return
        message = self._messages[message_index]
        message.highlighted = not message.highlighted
        overlay = self._active_overlay()
        if overlay is not None:
            highlights = set(overlay.highlighted_message_ids)
            if message.highlighted:
                highlights.add(message.message_id)
            else:
                highlights.discard(message.message_id)
            overlay.highlighted_message_ids = frozenset(highlights)
        model_index = self.index(visual_row, 0)
        self.dataChanged.emit(model_index, model_index, [self.HighlightedRole])
        self.state_changed.emit()

    @Slot(int)
    def set_core_hit_row(self, visual_row: int) -> None:
        if self._is_separator_row(visual_row):
            return
        message_index = self._message_index_for_visual_row(visual_row)
        if not (0 <= message_index < len(self._messages)):
            return
        message = self._messages[message_index]
        overlay = self._active_overlay()
        if overlay is None:
            return
        overlay.core_hit_message_id = message.message_id
        self._apply_overlay_state_to_messages()
        self._emit_all_message_changes()
        self.state_changed.emit()

    @Slot(str, int)
    def move_boundary(self, boundary_name: str, slot_index: int) -> None:
        if not (0 <= slot_index <= len(self._messages)):
            return
        overlay = self._active_overlay()
        if overlay is None:
            self._move_draft_boundary(boundary_name, slot_index)
            return
        slots = {
            BOUNDARY_CONTEXT_START: overlay.context_start_slot,
            BOUNDARY_RELEVANT_START: overlay.relevant_start_slot,
            BOUNDARY_RELEVANT_END: overlay.relevant_end_slot,
            BOUNDARY_CONTEXT_END: overlay.context_end_slot,
        }
        if boundary_name not in slots:
            return
        previous_slots = list(slots.values())
        slots[boundary_name] = slot_index
        if not self._slots_are_valid(*slots.values()):
            return
        overlay.context_start_slot = slots[BOUNDARY_CONTEXT_START]
        overlay.relevant_start_slot = slots[BOUNDARY_RELEVANT_START]
        overlay.relevant_end_slot = slots[BOUNDARY_RELEVANT_END]
        overlay.context_end_slot = slots[BOUNDARY_CONTEXT_END]
        for previous_slot in set(previous_slots + [slot_index]):
            self._emit_separator_change(previous_slot)
        self._apply_overlay_state_to_messages()
        self._emit_all_message_changes()
        self.state_changed.emit()

    @Slot(str, int)
    def move_boundary_to_visual_row(self, boundary_name: str, visual_row: int) -> None:
        if not self._is_separator_row(visual_row):
            return
        self.move_boundary(boundary_name, self._slot_index_for_separator_row(visual_row))

    def summary_text(self) -> str:
        context_start, relevant_start, relevant_end, context_end = self.active_slots()
        highlighted = len(self.highlighted_message_ids())
        active = self._active_block_id
        active_label = f"block {active}" if active is not None else "draft"
        return (
            f"Active: {active_label} | "
            f"Context: {self._slot_label(context_start)} .. {self._slot_label(context_end)} | "
            f"Relevant: {self._slot_label(relevant_start)} .. {self._slot_label(relevant_end)} | "
            f"Highlighted: {highlighted} | Overlays: {len(self._overlays)}"
        )

    def _move_draft_boundary(self, boundary_name: str, slot_index: int) -> None:
        slots = {
            BOUNDARY_CONTEXT_START: self._draft_slots[0],
            BOUNDARY_RELEVANT_START: self._draft_slots[1],
            BOUNDARY_RELEVANT_END: self._draft_slots[2],
            BOUNDARY_CONTEXT_END: self._draft_slots[3],
        }
        if boundary_name not in slots:
            return
        previous_slots = list(slots.values())
        slots[boundary_name] = slot_index
        if not self._slots_are_valid(*slots.values()):
            return
        self._draft_slots = (
            slots[BOUNDARY_CONTEXT_START],
            slots[BOUNDARY_RELEVANT_START],
            slots[BOUNDARY_RELEVANT_END],
            slots[BOUNDARY_CONTEXT_END],
        )
        for previous_slot in set(previous_slots + [slot_index]):
            self._emit_separator_change(previous_slot)
        self.state_changed.emit()

    def _slots_are_valid(
        self,
        context_start: int,
        relevant_start: int,
        relevant_end: int,
        context_end: int,
    ) -> bool:
        upper = len(self._messages)
        return (
            0 <= context_start <= relevant_start <= relevant_end <= context_end <= upper
        )

    def _active_overlay(self) -> BlockOverlay | None:
        for overlay in self._overlays:
            if overlay.is_active:
                return overlay
        return None

    def _apply_overlay_state_to_messages(self) -> None:
        active = self._active_overlay()
        for message in self._messages:
            message.highlighted = False
            message.is_core_hit = False
        if active is None:
            return
        for message in self._messages:
            if message.message_id in active.highlighted_message_ids:
                message.highlighted = True
            if message.message_id == active.core_hit_message_id:
                message.is_core_hit = True

    def _boundary_strength(self, boundary_name: str, slot_index: int) -> str:
        active_match = False
        inactive_match = False
        for overlay in self._overlays:
            slot_value = {
                BOUNDARY_CONTEXT_START: overlay.context_start_slot,
                BOUNDARY_CONTEXT_END: overlay.context_end_slot,
                BOUNDARY_RELEVANT_START: overlay.relevant_start_slot,
                BOUNDARY_RELEVANT_END: overlay.relevant_end_slot,
            }[boundary_name]
            if slot_value != slot_index:
                continue
            if overlay.is_active:
                active_match = True
            else:
                inactive_match = True
        if active_match:
            return BOUNDARY_ACTIVE
        if inactive_match:
            return BOUNDARY_INACTIVE
        if not self._overlays:
            draft_slots = {
                BOUNDARY_CONTEXT_START: self._draft_slots[0],
                BOUNDARY_CONTEXT_END: self._draft_slots[3],
                BOUNDARY_RELEVANT_START: self._draft_slots[1],
                BOUNDARY_RELEVANT_END: self._draft_slots[2],
            }
            if draft_slots[boundary_name] == slot_index:
                return BOUNDARY_ACTIVE
        return ""

    def _emit_separator_change(self, slot_index: int) -> None:
        if slot_index < 0:
            return
        visual_row = self._separator_row_for_slot(slot_index)
        model_index = self.index(visual_row, 0)
        self.dataChanged.emit(
            model_index,
            model_index,
            [
                self.ContextStartBoundaryRole,
                self.ContextEndBoundaryRole,
                self.RelevantStartBoundaryRole,
                self.RelevantEndBoundaryRole,
            ],
        )

    def _emit_all_separator_changes(self) -> None:
        for slot_index in range(len(self._messages) + 1):
            self._emit_separator_change(slot_index)

    def _emit_all_message_changes(self) -> None:
        if not self._messages:
            return
        first = self.index(1, 0)
        last = self.index(self.rowCount() - 1, 0)
        self.dataChanged.emit(first, last, [self.HighlightedRole, self.CoreHitRole])

    def _slot_label(self, slot_index: int) -> str:
        if slot_index < 0:
            return "-"
        if slot_index == 0 and self._messages:
            return f"before {self._messages[0].message_id}"
        if slot_index == len(self._messages) and self._messages:
            return f"after {self._messages[-1].message_id}"
        if 0 < slot_index < len(self._messages):
            return (
                f"between {self._messages[slot_index - 1].message_id} / "
                f"{self._messages[slot_index].message_id}"
            )
        return "-"

    @staticmethod
    def _is_separator_row(visual_row: int) -> bool:
        return visual_row % 2 == 0

    @staticmethod
    def _slot_index_for_separator_row(visual_row: int) -> int:
        return visual_row // 2

    @staticmethod
    def _message_index_for_visual_row(visual_row: int) -> int:
        return (visual_row - 1) // 2

    @staticmethod
    def _separator_row_for_slot(slot_index: int) -> int:
        return slot_index * 2


TranscriptLineModel = EvidenceTranscriptModel


class TranscriptItemDelegate(QStyledItemDelegate):
    page_margin = 22
    divider_height = 26
    handle_size = 14
    icon_size = 18
    core_hit_size = 16
    sender_col_width = 140

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        painter.save()
        painter.fillRect(option.rect, PAPER_BG)
        entry_kind = str(index.data(EvidenceTranscriptModel.EntryKindRole) or "")
        if entry_kind == ENTRY_SEPARATOR:
            self._paint_separator(painter, option.rect, index)
        else:
            self._paint_message(painter, option, index)
        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        entry_kind = str(index.data(EvidenceTranscriptModel.EntryKindRole) or "")
        if entry_kind == ENTRY_SEPARATOR:
            return QSize(option.rect.width(), self.divider_height)
        width = option.widget.viewport().width() if option.widget is not None else 700
        body_width = max(180, width - (self.page_margin * 2) - self.sender_col_width - self.icon_size - 26)
        body = str(index.data(EvidenceTranscriptModel.BodyRole) or "")
        attachment = str(index.data(EvidenceTranscriptModel.AttachmentRole) or "")
        body_height = option.fontMetrics.boundingRect(
            QRect(0, 0, body_width, 2000),
            Qt.TextFlag.TextWordWrap,
            body,
        ).height()
        attachment_height = 18 if attachment else 0
        total_height = 18 + max(22, body_height) + 10 + 18 + attachment_height + 14
        return QSize(width, max(84, total_height))

    def separator_handle_rect(self, rect: QRect, boundary_name: str) -> QRect:
        offsets = {
            BOUNDARY_CONTEXT_START: 0,
            BOUNDARY_RELEVANT_START: 18,
            BOUNDARY_RELEVANT_END: 36,
            BOUNDARY_CONTEXT_END: 54,
        }
        x = rect.left() + self.page_margin + offsets.get(boundary_name, 0)
        y = rect.center().y() - (self.handle_size // 2)
        return QRect(x, y, self.handle_size, self.handle_size)

    def highlight_icon_rect(self, rect: QRect) -> QRect:
        return QRect(rect.right() - self.icon_size - self.page_margin, rect.top() + 18, self.icon_size, self.icon_size)

    def core_hit_icon_rect(self, rect: QRect) -> QRect:
        return QRect(
            rect.right() - self.icon_size - self.page_margin - self.core_hit_size - 8,
            rect.top() + 19,
            self.core_hit_size,
            self.core_hit_size,
        )

    def boundary_at_pos(self, rect: QRect, pos, index: QModelIndex) -> str | None:
        role_by_boundary = {
            BOUNDARY_CONTEXT_START: EvidenceTranscriptModel.ContextStartBoundaryRole,
            BOUNDARY_RELEVANT_START: EvidenceTranscriptModel.RelevantStartBoundaryRole,
            BOUNDARY_RELEVANT_END: EvidenceTranscriptModel.RelevantEndBoundaryRole,
            BOUNDARY_CONTEXT_END: EvidenceTranscriptModel.ContextEndBoundaryRole,
        }
        for boundary_name, role in role_by_boundary.items():
            if str(index.data(role) or "") and self.separator_handle_rect(rect, boundary_name).contains(pos):
                return boundary_name
        return None

    def is_highlight_icon_hit(self, rect: QRect, pos) -> bool:
        return self.highlight_icon_rect(rect).contains(pos)

    def _paint_separator(self, painter: QPainter, rect: QRect, index: QModelIndex) -> None:
        painter.setPen(QPen(RULE_NEUTRAL, 1))
        painter.drawLine(
            rect.left() + self.page_margin,
            rect.center().y(),
            rect.right() - self.page_margin,
            rect.center().y(),
        )
        self._paint_boundary_marker(
            painter,
            rect,
            index,
            BOUNDARY_CONTEXT_START,
            EvidenceTranscriptModel.ContextStartBoundaryRole,
            CONTEXT_LINE_COLOR,
        )
        self._paint_boundary_marker(
            painter,
            rect,
            index,
            BOUNDARY_RELEVANT_START,
            EvidenceTranscriptModel.RelevantStartBoundaryRole,
            RELEVANT_LINE_COLOR,
        )
        self._paint_boundary_marker(
            painter,
            rect,
            index,
            BOUNDARY_RELEVANT_END,
            EvidenceTranscriptModel.RelevantEndBoundaryRole,
            RELEVANT_LINE_COLOR,
        )
        self._paint_boundary_marker(
            painter,
            rect,
            index,
            BOUNDARY_CONTEXT_END,
            EvidenceTranscriptModel.ContextEndBoundaryRole,
            CONTEXT_LINE_COLOR,
        )

    def _paint_boundary_marker(
        self,
        painter: QPainter,
        rect: QRect,
        index: QModelIndex,
        boundary_name: str,
        role: int,
        color: QColor,
    ) -> None:
        strength = str(index.data(role) or "")
        if not strength:
            return
        handle_rect = self.separator_handle_rect(rect, boundary_name)
        line_y = rect.center().y()
        paint_color = QColor(color)
        if strength == BOUNDARY_INACTIVE:
            paint_color.setAlpha(BOUNDARY_FAINT_ALPHA)
        line_width = 2 if strength == BOUNDARY_ACTIVE else 1
        painter.setPen(QPen(paint_color, line_width))
        painter.drawLine(
            handle_rect.right() + 8,
            line_y,
            rect.right() - self.page_margin,
            line_y,
        )
        path = QPainterPath()
        path.moveTo(handle_rect.left(), handle_rect.top())
        path.lineTo(handle_rect.right(), handle_rect.center().y())
        path.lineTo(handle_rect.left(), handle_rect.bottom())
        path.closeSubpath()
        painter.fillPath(path, paint_color)

    def _paint_message(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> None:
        rect = option.rect
        if bool(index.data(EvidenceTranscriptModel.HighlightedRole)):
            painter.fillRect(rect.adjusted(self.page_margin, 4, -self.page_margin, -4), HIGHLIGHT_WASH)

        icon_rect = self.highlight_icon_rect(rect)
        self._paint_highlight_icon(
            painter,
            icon_rect,
            bool(index.data(EvidenceTranscriptModel.HighlightedRole)),
        )
        if bool(index.data(EvidenceTranscriptModel.CoreHitRole)):
            self._paint_core_hit_icon(painter, self.core_hit_icon_rect(rect))

        sender = str(index.data(EvidenceTranscriptModel.SenderRole) or "")
        body = str(index.data(EvidenceTranscriptModel.BodyRole) or "")
        friendly_date = str(index.data(EvidenceTranscriptModel.FriendlyDateRole) or "")
        friendly_time = str(index.data(EvidenceTranscriptModel.FriendlyTimeRole) or "")
        attachment = str(index.data(EvidenceTranscriptModel.AttachmentRole) or "")

        content_left = rect.left() + self.page_margin
        sender_rect = QRect(content_left, rect.top() + 16, self.sender_col_width, 24)
        body_left = sender_rect.right() + 12
        body_width = icon_rect.left() - 16 - body_left
        body_rect = QRect(body_left, rect.top() + 16, body_width, rect.height())

        sender_font = QFont(option.font)
        sender_font.setBold(True)
        painter.setFont(sender_font)
        painter.setPen(PAGE_TEXT)
        painter.drawText(
            sender_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
            f"{sender}:",
        )

        painter.setFont(option.font)
        painter.drawText(body_rect, Qt.TextFlag.TextWordWrap, body)
        body_height = option.fontMetrics.boundingRect(
            QRect(0, 0, body_width, 2000),
            Qt.TextFlag.TextWordWrap,
            body,
        ).height()

        meta_top = rect.top() + 16 + max(22, body_height) + 10
        painter.setPen(PAGE_META)
        painter.drawText(
            QRect(body_left, meta_top, body_width, 18),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            f"{friendly_date}       -   {friendly_time}",
        )
        if attachment:
            painter.drawText(
                QRect(body_left, meta_top + 18, body_width, 18),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                f"Attachment: {attachment}",
            )

    def _paint_highlight_icon(self, painter: QPainter, icon_rect: QRect, active: bool) -> None:
        color = HIGHLIGHT_ICON_ON if active else HIGHLIGHT_ICON_OFF
        painter.setPen(QPen(color, 2))
        painter.setBrush(color if active else Qt.BrushStyle.NoBrush)
        painter.drawEllipse(icon_rect)

    def _paint_core_hit_icon(self, painter: QPainter, icon_rect: QRect) -> None:
        painter.setPen(QPen(CORE_HIT_COLOR, 2))
        painter.setBrush(CORE_HIT_COLOR)
        center = icon_rect.center()
        half = icon_rect.width() // 2
        painter.drawEllipse(center, half, half)


class TranscriptListView(QListView):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setUniformItemSizes(False)
        self.setWordWrap(True)
        self.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self.setStyleSheet("QListView { background: #f8f3e8; border: none; }")
        self._drag_boundary: str | None = None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        index = self.indexAt(event.position().toPoint())
        delegate = self.itemDelegate()
        if index.isValid() and isinstance(delegate, TranscriptItemDelegate):
            entry_kind = str(index.data(EvidenceTranscriptModel.EntryKindRole) or "")
            if entry_kind == ENTRY_SEPARATOR:
                rect = self.visualRect(index)
                boundary_name = delegate.boundary_at_pos(rect, event.position().toPoint(), index)
                if boundary_name is not None:
                    self._drag_boundary = boundary_name
                    self._move_boundary_to_index(index)
                    event.accept()
                    return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_boundary is None:
            super().mouseMoveEvent(event)
            return
        index = self.indexAt(event.position().toPoint())
        if index.isValid() and str(index.data(EvidenceTranscriptModel.EntryKindRole) or "") == ENTRY_SEPARATOR:
            self._move_boundary_to_index(index)
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        index = self.indexAt(event.position().toPoint())
        delegate = self.itemDelegate()
        if self._drag_boundary is not None:
            if index.isValid() and str(index.data(EvidenceTranscriptModel.EntryKindRole) or "") == ENTRY_SEPARATOR:
                self._move_boundary_to_index(index)
            self._drag_boundary = None
            event.accept()
            return
        if index.isValid() and isinstance(delegate, TranscriptItemDelegate):
            if str(index.data(EvidenceTranscriptModel.EntryKindRole) or "") == ENTRY_MESSAGE:
                rect = self.visualRect(index)
                if delegate.is_highlight_icon_hit(rect, event.position().toPoint()):
                    model = self.model()
                    if isinstance(model, EvidenceTranscriptModel):
                        model.toggle_highlight_row(index.row())
                    event.accept()
                    return
        super().mouseReleaseEvent(event)

    def _move_boundary_to_index(self, index: QModelIndex) -> None:
        model = self.model()
        if self._drag_boundary is None or not isinstance(model, EvidenceTranscriptModel):
            return
        model.move_boundary_to_visual_row(self._drag_boundary, index.row())


class TranscriptSurfaceWidget(QWidget):
    def __init__(self, model: EvidenceTranscriptModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.view = TranscriptListView()
        self.view.setModel(model)
        self.view.setItemDelegate(TranscriptItemDelegate(self.view))
        layout.addWidget(self.view)


class Gen2TranscriptSurfaceWidget(QAbstractScrollArea):
    """Custom-painted paper transcript with draggable evidence boundary gutters."""

    paper_margin = 18
    top_margin = 28
    bottom_margin = 42
    gutter_width = 92
    page_padding = 24
    sender_width = 150
    icon_width = 54
    handle_size = 16
    min_message_height = 78

    def __init__(self, model: EvidenceTranscriptModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model = model
        self._separator_y: list[int] = []
        self._drag_boundary: str | None = None
        self.setMouseTracking(True)
        self.setStyleSheet("QAbstractScrollArea { border: none; background: #d8d0c2; }")
        self.verticalScrollBar().valueChanged.connect(lambda _value: self.viewport().update())
        self._model.modelReset.connect(self._reflow)
        self._model.dataChanged.connect(self._on_model_changed)
        self._model.state_changed.connect(self.viewport().update)
        self._reflow()

    def resizeEvent(self, event) -> None:  # noqa: ANN001
        super().resizeEvent(event)
        self._reflow()

    def paintEvent(self, event) -> None:  # noqa: ANN001
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        viewport_rect = self.viewport().rect()
        scroll_y = self.verticalScrollBar().value()
        painter.fillRect(viewport_rect, QColor("#d8d0c2"))
        page_rect = QRect(
            self.paper_margin,
            self.top_margin - scroll_y,
            max(0, viewport_rect.width() - (self.paper_margin * 2)),
            max(viewport_rect.height(), self._document_height()),
        )
        painter.fillRect(page_rect, QColor("#fbf7ee"))
        painter.setPen(QPen(QColor("#c6bca9"), 1))
        painter.drawRect(page_rect.adjusted(0, 0, -1, -1))

        self._paint_messages(painter, scroll_y, viewport_rect)
        self._paint_separator_rules(painter, scroll_y, viewport_rect)
        self._paint_boundaries(painter, scroll_y, viewport_rect)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        boundary = self._boundary_at_point(event.position().toPoint())
        if boundary is not None:
            self._drag_boundary = boundary
            self._move_drag_boundary(event.position().toPoint())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_boundary is not None:
            self._move_drag_boundary(event.position().toPoint())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._drag_boundary is not None:
            self._move_drag_boundary(event.position().toPoint())
            self._drag_boundary = None
            event.accept()
            return
        point = event.position().toPoint()
        message_index = self._message_index_at_point(point)
        if message_index is not None:
            if self._highlight_icon_rect(message_index).translated(0, -self.verticalScrollBar().value()).contains(point):
                self._model.toggle_highlight_row((message_index * 2) + 1)
                event.accept()
                return
            if self._core_icon_rect(message_index).translated(0, -self.verticalScrollBar().value()).contains(point):
                self._model.set_core_hit_row((message_index * 2) + 1)
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def _on_model_changed(self, _top_left: QModelIndex, _bottom_right: QModelIndex, _roles: list[int]) -> None:
        self.viewport().update()

    def _reflow(self) -> None:
        y = self.top_margin
        self._separator_y = [y]
        for message_index in range(self._message_count()):
            y += self._message_height(message_index)
            self._separator_y.append(y)
        total_height = y + self.bottom_margin
        scrollbar = self.verticalScrollBar()
        scrollbar.setPageStep(self.viewport().height())
        scrollbar.setRange(0, max(0, total_height - self.viewport().height()))
        self.viewport().update()

    def _paint_messages(self, painter: QPainter, scroll_y: int, viewport_rect: QRect) -> None:
        for message_index in range(self._message_count()):
            top = self._separator_y[message_index]
            bottom = self._separator_y[message_index + 1]
            screen_rect = QRect(0, top - scroll_y, viewport_rect.width(), bottom - top)
            if not screen_rect.intersects(viewport_rect.adjusted(0, -60, 0, 60)):
                continue
            if self._message_bool(message_index, EvidenceTranscriptModel.HighlightedRole):
                painter.fillRect(
                    self._message_content_rect(message_index).translated(0, -scroll_y),
                    HIGHLIGHT_WASH,
                )
            self._paint_message_text(painter, message_index, scroll_y)
            self._paint_message_icons(painter, message_index, scroll_y)

    def _paint_separator_rules(self, painter: QPainter, scroll_y: int, viewport_rect: QRect) -> None:
        left = self.paper_margin + self.gutter_width
        right = viewport_rect.width() - self.paper_margin - self.page_padding
        painter.setPen(QPen(QColor("#ddd3c3"), 1))
        for y in self._separator_y:
            screen_y = y - scroll_y
            if -4 <= screen_y <= viewport_rect.height() + 4:
                painter.drawLine(left, screen_y, right, screen_y)

    def _paint_boundaries(self, painter: QPainter, scroll_y: int, viewport_rect: QRect) -> None:
        boundaries = (
            (BOUNDARY_CONTEXT_START, EvidenceTranscriptModel.ContextStartBoundaryRole, CONTEXT_LINE_COLOR),
            (BOUNDARY_RELEVANT_START, EvidenceTranscriptModel.RelevantStartBoundaryRole, RELEVANT_LINE_COLOR),
            (BOUNDARY_RELEVANT_END, EvidenceTranscriptModel.RelevantEndBoundaryRole, RELEVANT_LINE_COLOR),
            (BOUNDARY_CONTEXT_END, EvidenceTranscriptModel.ContextEndBoundaryRole, CONTEXT_LINE_COLOR),
        )
        for slot_index, y in enumerate(self._separator_y):
            screen_y = y - scroll_y
            if not (-12 <= screen_y <= viewport_rect.height() + 12):
                continue
            separator_index = self._model.index(slot_index * 2, 0)
            for boundary_name, role, base_color in boundaries:
                strength = str(separator_index.data(role) or "")
                if not strength:
                    continue
                color = QColor(base_color)
                if strength == BOUNDARY_INACTIVE:
                    color.setAlpha(BOUNDARY_FAINT_ALPHA)
                painter.setPen(QPen(color, 3 if strength == BOUNDARY_ACTIVE else 1))
                handle_rect = self._boundary_handle_rect(slot_index, boundary_name).translated(0, -scroll_y)
                painter.drawLine(
                    handle_rect.right() + 8,
                    screen_y,
                    viewport_rect.width() - self.paper_margin - self.page_padding,
                    screen_y,
                )
                self._paint_caret(painter, handle_rect, color)

    def _paint_message_text(self, painter: QPainter, message_index: int, scroll_y: int) -> None:
        index = self._message_model_index(message_index)
        rect = self._message_content_rect(message_index).translated(0, -scroll_y)
        sender = str(index.data(EvidenceTranscriptModel.SenderRole) or "")
        body = str(index.data(EvidenceTranscriptModel.BodyRole) or "")
        friendly_date = str(index.data(EvidenceTranscriptModel.FriendlyDateRole) or "")
        friendly_time = str(index.data(EvidenceTranscriptModel.FriendlyTimeRole) or "")
        attachment = str(index.data(EvidenceTranscriptModel.AttachmentRole) or "")

        baseline_top = rect.top() + 12
        sender_rect = QRect(rect.left(), baseline_top, self.sender_width, 24)
        body_left = sender_rect.right() + 12
        icon_left = self.viewport().width() - self.paper_margin - self.page_padding - self.icon_width
        body_rect = QRect(body_left, baseline_top, icon_left - body_left - 16, rect.height() - 34)

        sender_font = QFont(self.font())
        sender_font.setBold(True)
        painter.setFont(sender_font)
        painter.setPen(PAGE_TEXT)
        painter.drawText(sender_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, f"{sender}:")

        painter.setFont(self.font())
        painter.drawText(body_rect, Qt.TextFlag.TextWordWrap, body)
        body_height = self.fontMetrics().boundingRect(
            QRect(0, 0, body_rect.width(), 4000),
            Qt.TextFlag.TextWordWrap,
            body,
        ).height()

        painter.setPen(PAGE_META)
        meta_top = baseline_top + max(22, body_height) + 8
        painter.drawText(
            QRect(body_left, meta_top, body_rect.width(), 20),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            f"{friendly_date}       -   {friendly_time}",
        )
        if attachment:
            painter.drawText(
                QRect(body_left, meta_top + 20, body_rect.width(), 20),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                f"Attachment: {attachment}",
            )

    def _paint_message_icons(self, painter: QPainter, message_index: int, scroll_y: int) -> None:
        highlight_rect = self._highlight_icon_rect(message_index).translated(0, -scroll_y)
        core_rect = self._core_icon_rect(message_index).translated(0, -scroll_y)
        highlight_on = self._message_bool(message_index, EvidenceTranscriptModel.HighlightedRole)
        core_on = self._message_bool(message_index, EvidenceTranscriptModel.CoreHitRole)

        painter.setPen(QPen(HIGHLIGHT_ICON_ON if highlight_on else HIGHLIGHT_ICON_OFF, 2))
        painter.setBrush(HIGHLIGHT_ICON_ON if highlight_on else Qt.BrushStyle.NoBrush)
        painter.drawEllipse(highlight_rect)

        painter.setPen(QPen(CORE_HIT_COLOR if core_on else QColor("#9a9a9a"), 2))
        painter.setBrush(CORE_HIT_COLOR if core_on else Qt.BrushStyle.NoBrush)
        diamond = QPainterPath()
        diamond.moveTo(core_rect.center().x(), core_rect.top())
        diamond.lineTo(core_rect.right(), core_rect.center().y())
        diamond.lineTo(core_rect.center().x(), core_rect.bottom())
        diamond.lineTo(core_rect.left(), core_rect.center().y())
        diamond.closeSubpath()
        painter.drawPath(diamond)

    def _paint_caret(self, painter: QPainter, rect: QRect, color: QColor) -> None:
        path = QPainterPath()
        path.moveTo(rect.left(), rect.top())
        path.lineTo(rect.right(), rect.center().y())
        path.lineTo(rect.left(), rect.bottom())
        path.closeSubpath()
        painter.fillPath(path, color)

    def _move_drag_boundary(self, point: QPoint) -> None:
        if self._drag_boundary is None:
            return
        slot_index = self._nearest_slot_for_y(point.y() + self.verticalScrollBar().value())
        self._model.move_boundary(self._drag_boundary, slot_index)

    def _boundary_at_point(self, point: QPoint) -> str | None:
        doc_point = QPoint(point.x(), point.y() + self.verticalScrollBar().value())
        boundary_order = (
            BOUNDARY_RELEVANT_START,
            BOUNDARY_RELEVANT_END,
            BOUNDARY_CONTEXT_START,
            BOUNDARY_CONTEXT_END,
        )
        for slot_index in range(len(self._separator_y)):
            separator_index = self._model.index(slot_index * 2, 0)
            for boundary_name in boundary_order:
                role = {
                    BOUNDARY_CONTEXT_START: EvidenceTranscriptModel.ContextStartBoundaryRole,
                    BOUNDARY_CONTEXT_END: EvidenceTranscriptModel.ContextEndBoundaryRole,
                    BOUNDARY_RELEVANT_START: EvidenceTranscriptModel.RelevantStartBoundaryRole,
                    BOUNDARY_RELEVANT_END: EvidenceTranscriptModel.RelevantEndBoundaryRole,
                }[boundary_name]
                if not str(separator_index.data(role) or ""):
                    continue
                handle_rect = self._boundary_handle_rect(slot_index, boundary_name)
                if handle_rect.adjusted(-4, -6, 4, 6).contains(doc_point):
                    return boundary_name
                if abs(doc_point.y() - self._separator_y[slot_index]) <= 5 and doc_point.x() >= handle_rect.right():
                    return boundary_name
        return None

    def _message_index_at_point(self, point: QPoint) -> int | None:
        doc_y = point.y() + self.verticalScrollBar().value()
        for message_index in range(self._message_count()):
            if self._separator_y[message_index] <= doc_y <= self._separator_y[message_index + 1]:
                return message_index
        return None

    def _nearest_slot_for_y(self, y: int) -> int:
        if not self._separator_y:
            return 0
        return min(range(len(self._separator_y)), key=lambda slot_index: abs(self._separator_y[slot_index] - y))

    def _boundary_handle_rect(self, slot_index: int, boundary_name: str) -> QRect:
        lane_offsets = {
            BOUNDARY_CONTEXT_START: 12,
            BOUNDARY_RELEVANT_START: 32,
            BOUNDARY_RELEVANT_END: 52,
            BOUNDARY_CONTEXT_END: 72,
        }
        y = self._separator_y[slot_index] - (self.handle_size // 2)
        x = self.paper_margin + lane_offsets[boundary_name]
        return QRect(x, y, self.handle_size, self.handle_size)

    def _message_content_rect(self, message_index: int) -> QRect:
        left = self.paper_margin + self.gutter_width + self.page_padding
        right = self.viewport().width() - self.paper_margin - self.page_padding
        top = self._separator_y[message_index]
        bottom = self._separator_y[message_index + 1]
        return QRect(left, top + 1, max(0, right - left), max(0, bottom - top - 1))

    def _highlight_icon_rect(self, message_index: int) -> QRect:
        content_rect = self._message_content_rect(message_index)
        x = self.viewport().width() - self.paper_margin - self.page_padding - 44
        return QRect(x, content_rect.top() + 15, 17, 17)

    def _core_icon_rect(self, message_index: int) -> QRect:
        content_rect = self._message_content_rect(message_index)
        x = self.viewport().width() - self.paper_margin - self.page_padding - 20
        return QRect(x, content_rect.top() + 15, 17, 17)

    def _message_height(self, message_index: int) -> int:
        index = self._message_model_index(message_index)
        width = max(160, self.viewport().width())
        body_width = max(
            180,
            width
            - (self.paper_margin * 2)
            - self.gutter_width
            - (self.page_padding * 2)
            - self.sender_width
            - self.icon_width
            - 40,
        )
        body = str(index.data(EvidenceTranscriptModel.BodyRole) or "")
        attachment = str(index.data(EvidenceTranscriptModel.AttachmentRole) or "")
        body_height = self.fontMetrics().boundingRect(
            QRect(0, 0, body_width, 4000),
            Qt.TextFlag.TextWordWrap,
            body,
        ).height()
        attachment_height = 20 if attachment else 0
        return max(self.min_message_height, body_height + attachment_height + 54)

    def _document_height(self) -> int:
        if not self._separator_y:
            return self.viewport().height()
        return self._separator_y[-1] + self.bottom_margin

    def _message_count(self) -> int:
        row_count = self._model.rowCount()
        if row_count <= 0:
            return 0
        return (row_count - 1) // 2

    def _message_model_index(self, message_index: int) -> QModelIndex:
        return self._model.index((message_index * 2) + 1, 0)

    def _message_bool(self, message_index: int, role: int) -> bool:
        return bool(self._message_model_index(message_index).data(role))


def build_transcript_model_for_thread(
    conn: sqlite3.Connection,
    dataset_id: int,
    source_thread_id: str,
    *,
    active_block_id: int | None = None,
) -> tuple[EvidenceTranscriptModel, list[Message]]:
    messages = repositories.list_messages_for_thread(conn, dataset_id, source_thread_id)
    blocks = evidence_blocks.list_evidence_blocks(
        conn,
        dataset_id,
        source_thread_id=source_thread_id,
    )
    model = EvidenceTranscriptModel()
    model.load_thread_blocks(messages, blocks, active_block_id=active_block_id)
    return model, messages
