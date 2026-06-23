"""Shared evidence transcript model and reusable transcript surfaces."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from PySide6.QtCore import QAbstractListModel, QModelIndex, QObject, QPoint, QRect, QSize, Qt, Signal, Slot
from PySide6.QtGui import QColor, QFont, QFontMetrics, QMouseEvent, QPainter, QPainterPath, QPen, QWheelEvent
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
from message_evidence_workstation.ui.transcript_display import (
    build_sender_participant_map,
    format_timestamp_label,
    normalize_speaker_tints,
)

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
CONTEXT_REGION_ACTIVE = QColor(11, 109, 216, 28)
CONTEXT_REGION_INACTIVE = QColor(11, 109, 216, 12)
RELEVANT_REGION_ACTIVE = QColor(34, 34, 34, 22)
RELEVANT_REGION_INACTIVE = QColor(34, 34, 34, 10)
CONTEXT_ROW_FILL = QColor("#ece9e4")
BLOCK_ZONE_NONE = "none"
BLOCK_ZONE_CONTEXT = "context"
BLOCK_ZONE_RELEVANT = "relevant"

BOUNDARY_ACTIVE = "active"
BOUNDARY_INACTIVE = "inactive"
BOUNDARY_LANE_CONTEXT = 12
BOUNDARY_TAB_STOP = 20
BOUNDARY_LANE_RELEVANT = BOUNDARY_LANE_CONTEXT + BOUNDARY_TAB_STOP


def _friendly_date_parts(timestamp: str) -> tuple[str, str]:
    label = format_timestamp_label(timestamp)
    return label, label


@dataclass(slots=True)
class TranscriptMessage:
    message_id: str
    timestamp: str
    friendly_date: str
    friendly_time: str
    timestamp_label: str
    sender_id: str
    sender_display: str
    participant_index: int
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
    overlay_edited = Signal(int)

    EntryKindRole = int(Qt.ItemDataRole.UserRole) + 1
    SlotIndexRole = EntryKindRole + 1
    MessageIdRole = SlotIndexRole + 1
    FriendlyDateRole = MessageIdRole + 1
    FriendlyTimeRole = FriendlyDateRole + 1
    SenderRole = FriendlyTimeRole + 1
    TimestampLabelRole = SenderRole + 1
    ParticipantIndexRole = TimestampLabelRole + 1
    BodyRole = ParticipantIndexRole + 1
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
        if role == self.TimestampLabelRole:
            return message.timestamp_label
        if role == self.ParticipantIndexRole:
            return message.participant_index
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
            self.TimestampLabelRole: b"timestampLabel",
            self.ParticipantIndexRole: b"participantIndex",
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
        participant_map = build_sender_participant_map(messages)
        transcript_messages: list[TranscriptMessage] = []
        for message in messages:
            sender_key = (message.sender_id or message.sender_display or "").strip()
            timestamp_label = format_timestamp_label(message.timestamp)
            transcript_messages.append(
                TranscriptMessage(
                    message_id=message.message_id,
                    timestamp=message.timestamp,
                    friendly_date=timestamp_label,
                    friendly_time=timestamp_label,
                    timestamp_label=timestamp_label,
                    sender_id=sender_key,
                    sender_display=message.sender_display,
                    participant_index=participant_map.get(sender_key, 0),
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
        del active_block_id
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
                is_active=False,
            )
            for block in blocks
        ]
        self._active_block_id = None
        self.endResetModel()
        self.state_changed.emit()

    def append_evidence_block(self, block: EvidenceBlock) -> None:
        if self.overlay_by_id(block.evidence_block_id) is not None:
            return
        self._overlays.append(
            BlockOverlay(
                evidence_block_id=block.evidence_block_id,
                context_start_slot=block.context_start_slot,
                relevant_start_slot=block.relevant_start_slot,
                relevant_end_slot=block.relevant_end_slot,
                context_end_slot=block.context_end_slot,
                core_hit_message_id=block.core_hit_message_id,
                highlighted_message_ids=block.highlighted_message_ids,
                is_active=False,
            )
        )
        self._emit_all_separator_changes()
        self.state_changed.emit()

    def set_active_block(self, evidence_block_id: int | None) -> None:
        self._active_block_id = evidence_block_id
        for overlay in self._overlays:
            overlay.is_active = overlay.evidence_block_id == evidence_block_id
        self._emit_all_separator_changes()
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

    def message_count(self) -> int:
        return len(self._messages)

    def ordered_message_ids(self) -> list[str]:
        return [message.message_id for message in self._messages]

    def message_preview_at(self, message_index: int) -> str:
        if not (0 <= message_index < len(self._messages)):
            return ""
        message = self._messages[message_index]
        return message.body or message.message_id

    def block_overlays(self) -> list[BlockOverlay]:
        return list(self._overlays)

    def overlay_by_id(self, evidence_block_id: int) -> BlockOverlay | None:
        for overlay in self._overlays:
            if overlay.evidence_block_id == evidence_block_id:
                return overlay
        return None

    def overlays_for_relevant_message(self, message_index: int) -> list[BlockOverlay]:
        return [
            overlay
            for overlay in self._overlays
            if overlay.relevant_start_slot <= message_index < overlay.relevant_end_slot
        ]

    def message_is_highlighted_in_any_block(self, message_id: str) -> bool:
        return any(message_id in overlay.highlighted_message_ids for overlay in self._overlays)

    def set_anchor_message(self, evidence_block_id: int, message_id: str) -> None:
        overlay = self.overlay_by_id(evidence_block_id)
        if overlay is None:
            return
        overlay.core_hit_message_id = message_id
        self.state_changed.emit()
        self.overlay_edited.emit(evidence_block_id)

    def toggle_highlight_for_block(self, evidence_block_id: int, message_id: str) -> None:
        overlay = self.overlay_by_id(evidence_block_id)
        if overlay is None:
            return
        highlights = set(overlay.highlighted_message_ids)
        if message_id in highlights:
            highlights.discard(message_id)
        else:
            highlights.add(message_id)
        overlay.highlighted_message_ids = frozenset(highlights)
        self.state_changed.emit()
        self.overlay_edited.emit(evidence_block_id)

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

    @Slot(int, str, int)
    def move_boundary_for_block(self, evidence_block_id: int, boundary_name: str, slot_index: int) -> None:
        if not (0 <= slot_index <= len(self._messages)):
            return
        overlay = self.overlay_by_id(evidence_block_id)
        if overlay is None:
            return
        resolved = self._resolve_boundary_move(
            boundary_name,
            slot_index,
            context_start=overlay.context_start_slot,
            relevant_start=overlay.relevant_start_slot,
            relevant_end=overlay.relevant_end_slot,
            context_end=overlay.context_end_slot,
        )
        if resolved is None:
            return
        previous_slots = [
            overlay.context_start_slot,
            overlay.relevant_start_slot,
            overlay.relevant_end_slot,
            overlay.context_end_slot,
        ]
        (
            overlay.context_start_slot,
            overlay.relevant_start_slot,
            overlay.relevant_end_slot,
            overlay.context_end_slot,
        ) = resolved
        for previous_slot in set(previous_slots + list(resolved)):
            self._emit_separator_change(previous_slot)
        self.state_changed.emit()

    def notify_overlay_edited(self, evidence_block_id: int) -> None:
        if self.overlay_by_id(evidence_block_id) is not None:
            self.overlay_edited.emit(evidence_block_id)

    @Slot(str, int)
    def move_boundary(self, boundary_name: str, slot_index: int) -> None:
        if not (0 <= slot_index <= len(self._messages)):
            return
        overlay = self._active_overlay()
        if overlay is None:
            self._move_draft_boundary(boundary_name, slot_index)
            return
        self.move_boundary_for_block(overlay.evidence_block_id, boundary_name, slot_index)

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
        resolved = self._resolve_boundary_move(
            boundary_name,
            slot_index,
            context_start=self._draft_slots[0],
            relevant_start=self._draft_slots[1],
            relevant_end=self._draft_slots[2],
            context_end=self._draft_slots[3],
        )
        if resolved is None:
            return
        previous_slots = list(self._draft_slots)
        self._draft_slots = resolved
        for previous_slot in set(previous_slots + list(resolved)):
            self._emit_separator_change(previous_slot)
        self.state_changed.emit()

    def _resolve_boundary_move(
        self,
        boundary_name: str,
        slot_index: int,
        *,
        context_start: int,
        relevant_start: int,
        relevant_end: int,
        context_end: int,
    ) -> tuple[int, int, int, int] | None:
        slots = {
            BOUNDARY_CONTEXT_START: context_start,
            BOUNDARY_RELEVANT_START: relevant_start,
            BOUNDARY_RELEVANT_END: relevant_end,
            BOUNDARY_CONTEXT_END: context_end,
        }
        if boundary_name not in slots:
            return None
        slots[boundary_name] = slot_index
        if boundary_name == BOUNDARY_RELEVANT_START and slot_index < slots[BOUNDARY_CONTEXT_START]:
            slots[BOUNDARY_CONTEXT_START] = max(0, slot_index - 1)
        elif boundary_name == BOUNDARY_RELEVANT_END and slot_index > slots[BOUNDARY_CONTEXT_END]:
            slots[BOUNDARY_CONTEXT_END] = min(len(self._messages), slot_index + 1)
        resolved = (
            slots[BOUNDARY_CONTEXT_START],
            slots[BOUNDARY_RELEVANT_START],
            slots[BOUNDARY_RELEVANT_END],
            slots[BOUNDARY_CONTEXT_END],
        )
        if not self._slots_are_valid(*resolved):
            return None
        return resolved

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
        for overlay in self._overlays:
            slot_value = {
                BOUNDARY_CONTEXT_START: overlay.context_start_slot,
                BOUNDARY_CONTEXT_END: overlay.context_end_slot,
                BOUNDARY_RELEVANT_START: overlay.relevant_start_slot,
                BOUNDARY_RELEVANT_END: overlay.relevant_end_slot,
            }[boundary_name]
            if slot_value == slot_index:
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
        lane = BOUNDARY_LANE_CONTEXT
        if boundary_name in (BOUNDARY_RELEVANT_START, BOUNDARY_RELEVANT_END):
            lane = BOUNDARY_LANE_RELEVANT
        x = rect.left() + self.page_margin + lane
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
    top_margin = 12
    bottom_margin = 42
    header_height = 28
    boundary_gutter_width = 32
    page_padding = 16
    sender_width = 150
    datetime_width = 210
    control_icon_size = 17
    control_spacing = 22
    handle_size = 16
    min_message_height = 38
    row_padding_y = 10
    message_font_size_delta = 2

    def __init__(
        self,
        model: EvidenceTranscriptModel,
        *,
        speaker_tints: list[str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._model = model
        self._speaker_tints = normalize_speaker_tints(speaker_tints)
        self._separator_y: list[int] = []
        self._drag_target: tuple[str, int] | None = None
        self.setMouseTracking(True)
        self.setStyleSheet("QAbstractScrollArea { border: none; background: #d8d0c2; }")
        self.verticalScrollBar().valueChanged.connect(lambda _value: self.viewport().update())
        self._model.modelReset.connect(self._reflow)
        self._model.dataChanged.connect(self._on_model_changed)
        self._model.state_changed.connect(self._reflow_and_repaint)
        self._reflow()

    def set_speaker_tints(self, tints: list[str]) -> None:
        self._speaker_tints = normalize_speaker_tints(tints)
        self._reflow_and_repaint()

    def resizeEvent(self, event) -> None:  # noqa: ANN001
        super().resizeEvent(event)
        self._reflow()

    def minimumSizeHint(self) -> QSize:
        return QSize(240, 160)

    def sizeHint(self) -> QSize:
        return QSize(640, 480)

    def paintEvent(self, event) -> None:  # noqa: ANN001
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        viewport_rect = self.viewport().rect()
        scroll_y = self.verticalScrollBar().value()
        painter.fillRect(viewport_rect, QColor("#d8d0c2"))

        self._paint_column_headers(painter, viewport_rect)
        painter.save()
        painter.setClipRect(0, self.header_height, viewport_rect.width(), viewport_rect.height() - self.header_height)

        page_top = self._doc_to_screen(self.top_margin, scroll_y)
        page_rect = QRect(
            self.paper_margin,
            page_top,
            max(0, viewport_rect.width() - (self.paper_margin * 2)),
            max(viewport_rect.height(), self._document_height()),
        )
        painter.fillRect(page_rect, QColor("#fbf7ee"))
        painter.setPen(QPen(QColor("#c6bca9"), 1))
        painter.drawRect(page_rect.adjusted(0, 0, -1, -1))

        self._paint_messages(painter, scroll_y, viewport_rect)
        self._paint_separator_rules(painter, scroll_y, viewport_rect)
        self._paint_boundaries(painter, scroll_y, viewport_rect)
        painter.restore()

    def viewport_center_message_index(self) -> int | None:
        if self._message_count() <= 0 or not self._separator_y:
            return None
        scroll_y = self.verticalScrollBar().value()
        center_screen = self.header_height + (self.viewport().height() - self.header_height) // 2
        return self._nearest_message_index_for_y(self._screen_to_doc_y(center_screen, scroll_y))

    def scroll_to_message_index(self, message_index: int) -> None:
        if not self._separator_y or not (0 <= message_index < self._message_count()):
            return
        top = self._separator_y[message_index]
        bottom = self._separator_y[message_index + 1]
        center = (top + bottom) // 2
        content_height = max(1, self.viewport().height() - self.header_height)
        self.verticalScrollBar().setValue(max(0, center - content_height // 2))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.position().y() < self.header_height:
            return
        drag_target = self._boundary_at_point(event.position().toPoint())
        if drag_target is not None:
            self._drag_target = drag_target
            self._move_drag_boundary(event.position().toPoint())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_target is not None:
            self._move_drag_boundary(event.position().toPoint())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._drag_target is not None:
            self._move_drag_boundary(event.position().toPoint())
            _boundary_name, evidence_block_id = self._drag_target
            self._drag_target = None
            self._model.notify_overlay_edited(evidence_block_id)
            event.accept()
            return
        if event.position().y() < self.header_height:
            return
        point = event.position().toPoint()
        message_index = self._message_index_at_point(point)
        if message_index is None:
            super().mouseReleaseEvent(event)
            return
        message_id = str(self._message_model_index(message_index).data(EvidenceTranscriptModel.MessageIdRole) or "")
        scroll_y = self.verticalScrollBar().value()
        for overlay_index, overlay in enumerate(self._model.overlays_for_relevant_message(message_index)):
            if self._control_icon_screen_rect(
                message_index, overlay_index, self._anchor_left(), scroll_y
            ).contains(point):
                self._model.set_anchor_message(overlay.evidence_block_id, message_id)
                event.accept()
                return
            if self._control_icon_screen_rect(
                message_index, overlay_index, self._highlight_left(), scroll_y
            ).contains(point):
                self._model.toggle_highlight_for_block(overlay.evidence_block_id, message_id)
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def _reflow_and_repaint(self) -> None:
        self._reflow()

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
        scrollbar.setSingleStep(max(24, self.min_message_height // 2))
        scrollbar.setPageStep(max(1, self.viewport().height() - self.header_height))
        scrollbar.setRange(0, max(0, total_height - (self.viewport().height() - self.header_height)))
        self.viewport().update()

    def wheelEvent(self, event: QWheelEvent) -> None:
        scrollbar = self.verticalScrollBar()
        pixel_delta = event.pixelDelta().y()
        if pixel_delta != 0:
            scrollbar.setValue(scrollbar.value() - pixel_delta)
            event.accept()
            return
        angle_delta = event.angleDelta().y()
        if angle_delta == 0:
            super().wheelEvent(event)
            return
        notch_lines = 3
        scroll_amount = (angle_delta // 120) * notch_lines * scrollbar.singleStep()
        if scroll_amount == 0:
            scroll_amount = 1 if angle_delta > 0 else -1
        scrollbar.setValue(scrollbar.value() - scroll_amount)
        event.accept()

    def _doc_to_screen(self, doc_y: int, scroll_y: int) -> int:
        return self.header_height + doc_y - scroll_y

    def _screen_to_doc_y(self, screen_y: int, scroll_y: int) -> int:
        return screen_y - self.header_height + scroll_y

    def _control_column_width(self) -> int:
        overlay_count = max(1, len(self._model.block_overlays()))
        return max(56, overlay_count * self.control_spacing + 8)

    def _table_left(self) -> int:
        return self.paper_margin + self.boundary_gutter_width

    def _anchor_left(self) -> int:
        return self._table_left()

    def _sender_left(self) -> int:
        return self._anchor_left() + self._control_column_width()

    def _highlight_left(self) -> int:
        return self.viewport().width() - self.paper_margin - self.page_padding - self._control_column_width()

    def _datetime_left(self) -> int:
        return self._highlight_left() - 8 - self.datetime_width

    def _message_left(self) -> int:
        return self._sender_left() + self.sender_width + 12

    def _message_body_width(self) -> int:
        return max(80, self._datetime_left() - self._message_left() - 8)

    def _message_width(self) -> int:
        return self._message_body_width()

    def _paint_column_headers(self, painter: QPainter, viewport_rect: QRect) -> None:
        header_rect = QRect(0, 0, viewport_rect.width(), self.header_height)
        painter.fillRect(header_rect, QColor("#efe8d8"))
        painter.setPen(QPen(QColor("#c6bca9"), 1))
        painter.drawLine(0, self.header_height - 1, viewport_rect.width(), self.header_height - 1)

        header_font = QFont(self.font())
        header_font.setBold(True)
        painter.setFont(header_font)
        painter.setPen(PAGE_META)
        for label, left, width in (
            ("Anchor", self._anchor_left(), self._control_column_width()),
            ("Sender", self._sender_left(), self.sender_width),
            ("Message", self._message_left(), self._message_width()),
            ("Highlight", self._highlight_left(), self._control_column_width()),
        ):
            painter.drawText(
                QRect(left, 0, width, self.header_height),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                label,
            )

    def _paint_block_regions(self, painter: QPainter, scroll_y: int, viewport_rect: QRect) -> None:
        for overlay in self._model.block_overlays():
            self._paint_slot_region(
                painter,
                scroll_y,
                viewport_rect,
                overlay.context_start_slot,
                overlay.relevant_start_slot,
                CONTEXT_REGION_ACTIVE,
            )
            self._paint_slot_region(
                painter,
                scroll_y,
                viewport_rect,
                overlay.relevant_start_slot,
                overlay.relevant_end_slot,
                RELEVANT_REGION_ACTIVE,
            )
            self._paint_slot_region(
                painter,
                scroll_y,
                viewport_rect,
                overlay.relevant_end_slot,
                overlay.context_end_slot,
                CONTEXT_REGION_ACTIVE,
            )

    def _paint_slot_region(
        self,
        painter: QPainter,
        scroll_y: int,
        viewport_rect: QRect,
        start_slot: int,
        end_slot: int,
        color: QColor,
    ) -> None:
        if end_slot <= start_slot or not self._separator_y:
            return
        top = self._doc_to_screen(self._separator_y[start_slot], scroll_y)
        bottom = self._doc_to_screen(self._separator_y[end_slot], scroll_y)
        region_rect = QRect(
            self._sender_left(),
            top,
            max(0, viewport_rect.width() - self._sender_left() - self.paper_margin - self.page_padding),
            bottom - top,
        )
        if region_rect.intersects(viewport_rect.adjusted(0, self.header_height, 0, 0)):
            painter.fillRect(region_rect, color)

    def _row_content_right(self, viewport_rect: QRect) -> int:
        return viewport_rect.width() - self.paper_margin - self.page_padding

    def _message_block_zone(self, message_index: int) -> str:
        in_relevant = any(
            overlay.relevant_start_slot <= message_index < overlay.relevant_end_slot
            for overlay in self._model.block_overlays()
        )
        if in_relevant:
            return BLOCK_ZONE_RELEVANT
        in_context = any(
            (overlay.context_start_slot <= message_index < overlay.relevant_start_slot)
            or (overlay.relevant_end_slot <= message_index < overlay.context_end_slot)
            for overlay in self._model.block_overlays()
        )
        if in_context:
            return BLOCK_ZONE_CONTEXT
        return BLOCK_ZONE_NONE

    def _paint_messages(self, painter: QPainter, scroll_y: int, viewport_rect: QRect) -> None:
        for message_index in range(self._message_count()):
            top = self._doc_to_screen(self._separator_y[message_index], scroll_y)
            bottom = self._doc_to_screen(self._separator_y[message_index + 1], scroll_y)
            screen_rect = QRect(0, top, viewport_rect.width(), bottom - top)
            if not screen_rect.intersects(viewport_rect.adjusted(0, self.header_height - 60, 0, 60)):
                continue
            message_id = str(
                self._message_model_index(message_index).data(EvidenceTranscriptModel.MessageIdRole) or ""
            )
            participant_index = int(
                self._message_model_index(message_index).data(EvidenceTranscriptModel.ParticipantIndexRole) or 0
            )
            tint_color = QColor(self._speaker_tints[participant_index % 8])
            zone = self._message_block_zone(message_index)
            row_fill = QRect(
                self._anchor_left(),
                top + 1,
                self._row_content_right(viewport_rect) - self._anchor_left(),
                bottom - top - 1,
            )
            if zone == BLOCK_ZONE_CONTEXT:
                painter.fillRect(row_fill, CONTEXT_ROW_FILL)
            elif zone == BLOCK_ZONE_RELEVANT:
                painter.fillRect(
                    QRect(self._sender_left(), top + 1, self.sender_width, bottom - top - 1),
                    tint_color,
                )
            else:
                painter.fillRect(row_fill, tint_color)
            if self._model.message_is_highlighted_in_any_block(message_id):
                painter.fillRect(
                    QRect(self._message_left(), top + 1, self._message_width(), bottom - top - 1),
                    HIGHLIGHT_WASH,
                )
            self._paint_message_text(painter, message_index, scroll_y, zone)
            self._paint_message_controls(painter, message_index, scroll_y, message_id)

    def _paint_separator_rules(self, painter: QPainter, scroll_y: int, viewport_rect: QRect) -> None:
        left = self._table_left()
        right = viewport_rect.width() - self.paper_margin - self.page_padding
        painter.setPen(QPen(QColor("#ddd3c3"), 1))
        for y in self._separator_y:
            screen_y = self._doc_to_screen(y, scroll_y)
            if self.header_height - 4 <= screen_y <= viewport_rect.height() + 4:
                painter.drawLine(left, screen_y, right, screen_y)

    def _paint_boundaries(self, painter: QPainter, scroll_y: int, viewport_rect: QRect) -> None:
        boundaries = (
            (BOUNDARY_CONTEXT_START, CONTEXT_LINE_COLOR),
            (BOUNDARY_RELEVANT_START, RELEVANT_LINE_COLOR),
            (BOUNDARY_RELEVANT_END, RELEVANT_LINE_COLOR),
            (BOUNDARY_CONTEXT_END, CONTEXT_LINE_COLOR),
        )
        slot_values = {
            BOUNDARY_CONTEXT_START: lambda overlay: overlay.context_start_slot,
            BOUNDARY_RELEVANT_START: lambda overlay: overlay.relevant_start_slot,
            BOUNDARY_RELEVANT_END: lambda overlay: overlay.relevant_end_slot,
            BOUNDARY_CONTEXT_END: lambda overlay: overlay.context_end_slot,
        }
        for overlay in self._model.block_overlays():
            for boundary_name, base_color in boundaries:
                slot_index = slot_values[boundary_name](overlay)
                if not (0 <= slot_index < len(self._separator_y)):
                    continue
                screen_y = self._doc_to_screen(self._separator_y[slot_index], scroll_y)
                if not (self.header_height - 12 <= screen_y <= viewport_rect.height() + 12):
                    continue
                color = QColor(base_color)
                painter.setPen(QPen(color, 2))
                handle_rect = self._boundary_handle_rect(slot_index, boundary_name)
                screen_handle = handle_rect.translated(0, -scroll_y + self.header_height)
                painter.drawLine(
                    screen_handle.right() + 8,
                    screen_y,
                    viewport_rect.width() - self.paper_margin - self.page_padding,
                    screen_y,
                )
                self._paint_caret(painter, screen_handle, color)

    def _message_font(self, *, bold: bool = True) -> QFont:
        font = QFont(self.font())
        font.setPointSize(max(1, font.pointSize() + self.message_font_size_delta))
        font.setBold(bold)
        return font

    def _sender_font(self, *, bold: bool = True) -> QFont:
        return self._message_font(bold=bold)

    def _timestamp_font(self) -> QFont:
        font = QFont(self.font())
        font.setPointSize(max(1, font.pointSize()))
        return font

    def _paint_message_text(self, painter: QPainter, message_index: int, scroll_y: int, zone: str) -> None:
        index = self._message_model_index(message_index)
        top = self._doc_to_screen(self._separator_y[message_index], scroll_y)
        bottom = self._doc_to_screen(self._separator_y[message_index + 1], scroll_y)
        row_height = bottom - top
        sender = str(index.data(EvidenceTranscriptModel.SenderRole) or "")
        body = str(index.data(EvidenceTranscriptModel.BodyRole) or "")
        timestamp_label = str(index.data(EvidenceTranscriptModel.TimestampLabelRole) or "")
        attachment = str(index.data(EvidenceTranscriptModel.AttachmentRole) or "")
        use_bold = zone == BLOCK_ZONE_RELEVANT

        content_top = top + self.row_padding_y
        content_height = max(1, row_height - (self.row_padding_y * 2))
        sender_rect = QRect(self._sender_left(), content_top, self.sender_width, content_height)
        body_rect = QRect(self._message_left(), content_top, self._message_body_width(), content_height)
        datetime_rect = QRect(self._datetime_left(), content_top, self.datetime_width, content_height)

        painter.setFont(self._sender_font(bold=use_bold))
        painter.setPen(PAGE_TEXT)
        painter.drawText(
            sender_rect,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            sender,
        )

        message_font = self._message_font(bold=use_bold)
        painter.setFont(message_font)
        painter.setPen(PAGE_TEXT)
        painter.drawText(
            body_rect,
            Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignTop,
            body,
        )

        painter.setFont(self._timestamp_font())
        painter.setPen(PAGE_META)
        painter.drawText(
            datetime_rect,
            Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
            timestamp_label,
        )

        if attachment:
            message_metrics = QFontMetrics(message_font)
            body_height = message_metrics.boundingRect(
                QRect(0, 0, body_rect.width(), 4000),
                Qt.TextFlag.TextWordWrap,
                body,
            ).height()
            attach_top = content_top + body_height + 4
            painter.setFont(self._timestamp_font())
            painter.setPen(PAGE_META)
            painter.drawText(
                QRect(self._message_left(), attach_top, body_rect.width(), 18),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                f"Attachment: {attachment}",
            )

    def _paint_message_controls(self, painter: QPainter, message_index: int, scroll_y: int, message_id: str) -> None:
        overlays = self._model.overlays_for_relevant_message(message_index)
        for overlay_index, overlay in enumerate(overlays):
            anchor_rect = self._anchor_icon_rect(message_index, overlay_index)
            highlight_rect = self._highlight_icon_rect(message_index, overlay_index)
            screen_anchor = anchor_rect.translated(0, self.header_height - scroll_y)
            screen_highlight = highlight_rect.translated(0, self.header_height - scroll_y)
            anchor_on = overlay.core_hit_message_id == message_id
            highlight_on = message_id in overlay.highlighted_message_ids
            self._paint_radio_icon(painter, screen_anchor, anchor_on)
            self._paint_checkbox_icon(painter, screen_highlight, highlight_on)

    def _paint_checkbox_icon(self, painter: QPainter, rect: QRect, checked: bool) -> None:
        painter.setPen(QPen(HIGHLIGHT_ICON_ON if checked else HIGHLIGHT_ICON_OFF, 2))
        painter.setBrush(HIGHLIGHT_ICON_ON if checked else Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, 3, 3)
        if checked:
            painter.setPen(QPen(Qt.GlobalColor.white, 2))
            inset = rect.adjusted(4, 4, -4, -4)
            painter.drawLine(inset.left(), inset.center().y(), inset.center().x() - 1, inset.bottom() - 1)
            painter.drawLine(inset.center().x() - 1, inset.bottom() - 1, inset.right(), inset.top() + 1)

    def _paint_radio_icon(self, painter: QPainter, rect: QRect, selected: bool) -> None:
        color = CORE_HIT_COLOR if selected else QColor("#9a9a9a")
        painter.setPen(QPen(color, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(rect)
        if selected:
            inset = rect.adjusted(4, 4, -4, -4)
            painter.setBrush(color)
            painter.drawEllipse(inset)

    def _paint_caret(self, painter: QPainter, rect: QRect, color: QColor) -> None:
        path = QPainterPath()
        path.moveTo(rect.left(), rect.top())
        path.lineTo(rect.right(), rect.center().y())
        path.lineTo(rect.left(), rect.bottom())
        path.closeSubpath()
        painter.fillPath(path, color)

    def _move_drag_boundary(self, point: QPoint) -> None:
        if self._drag_target is None:
            return
        boundary_name, evidence_block_id = self._drag_target
        slot_index = self._nearest_slot_for_y(self._screen_to_doc_y(point.y(), self.verticalScrollBar().value()))
        self._model.move_boundary_for_block(evidence_block_id, boundary_name, slot_index)

    def _boundary_at_point(self, point: QPoint) -> tuple[str, int] | None:
        doc_y = self._screen_to_doc_y(point.y(), self.verticalScrollBar().value())
        doc_point = QPoint(point.x(), doc_y)
        boundary_order = (
            BOUNDARY_RELEVANT_START,
            BOUNDARY_RELEVANT_END,
            BOUNDARY_CONTEXT_START,
            BOUNDARY_CONTEXT_END,
        )
        slot_values = {
            BOUNDARY_CONTEXT_START: lambda overlay: overlay.context_start_slot,
            BOUNDARY_CONTEXT_END: lambda overlay: overlay.context_end_slot,
            BOUNDARY_RELEVANT_START: lambda overlay: overlay.relevant_start_slot,
            BOUNDARY_RELEVANT_END: lambda overlay: overlay.relevant_end_slot,
        }
        for overlay in reversed(self._model.block_overlays()):
            for boundary_name in boundary_order:
                slot_index = slot_values[boundary_name](overlay)
                if not (0 <= slot_index < len(self._separator_y)):
                    continue
                handle_rect = self._boundary_handle_rect(slot_index, boundary_name)
                if handle_rect.adjusted(-4, -6, 4, 6).contains(doc_point):
                    return boundary_name, overlay.evidence_block_id
                if abs(doc_point.y() - self._separator_y[slot_index]) <= 5 and doc_point.x() >= handle_rect.right():
                    return boundary_name, overlay.evidence_block_id
        return None

    def _message_index_at_point(self, point: QPoint) -> int | None:
        doc_y = self._screen_to_doc_y(point.y(), self.verticalScrollBar().value())
        for message_index in range(self._message_count()):
            if self._separator_y[message_index] <= doc_y <= self._separator_y[message_index + 1]:
                return message_index
        return None

    def _nearest_slot_for_y(self, y: int) -> int:
        if not self._separator_y:
            return 0
        return min(range(len(self._separator_y)), key=lambda slot_index: abs(self._separator_y[slot_index] - y))

    def _nearest_message_index_for_y(self, y: int) -> int:
        if self._message_count() <= 0:
            return 0
        best_index = 0
        best_distance = float("inf")
        for message_index in range(self._message_count()):
            top = self._separator_y[message_index]
            bottom = self._separator_y[message_index + 1]
            center = (top + bottom) / 2
            distance = abs(center - y)
            if distance < best_distance:
                best_distance = distance
                best_index = message_index
        return best_index

    def _boundary_handle_rect(self, slot_index: int, boundary_name: str) -> QRect:
        lane = BOUNDARY_LANE_CONTEXT
        if boundary_name in (BOUNDARY_RELEVANT_START, BOUNDARY_RELEVANT_END):
            lane = BOUNDARY_LANE_RELEVANT
        y = self._separator_y[slot_index] - (self.handle_size // 2)
        x = self.paper_margin + lane
        return QRect(x, y, self.handle_size, self.handle_size)

    def _control_icon_rect(self, message_index: int, overlay_index: int, column_left: int) -> QRect:
        overlays = self._model.overlays_for_relevant_message(message_index)
        slot_width = self._control_column_width() / max(1, len(overlays))
        row_top = self._separator_y[message_index]
        row_bottom = self._separator_y[message_index + 1]
        row_height = row_bottom - row_top
        top = row_top + max(0, (row_height - self.control_icon_size) // 2)
        x = int(column_left + (overlay_index * slot_width) + ((slot_width - self.control_icon_size) / 2))
        return QRect(x, top, self.control_icon_size, self.control_icon_size)

    def _control_icon_screen_rect(
        self,
        message_index: int,
        overlay_index: int,
        column_left: int,
        scroll_y: int,
    ) -> QRect:
        doc_rect = self._control_icon_rect(message_index, overlay_index, column_left)
        return QRect(
            doc_rect.left(),
            self._doc_to_screen(doc_rect.top(), scroll_y),
            doc_rect.width(),
            doc_rect.height(),
        )

    def _anchor_icon_rect(self, message_index: int, overlay_index: int) -> QRect:
        return self._control_icon_rect(message_index, overlay_index, self._anchor_left())

    def _highlight_icon_rect(self, message_index: int, overlay_index: int) -> QRect:
        return self._control_icon_rect(message_index, overlay_index, self._highlight_left())

    def _message_height(self, message_index: int) -> int:
        index = self._message_model_index(message_index)
        body_width = self._message_body_width()
        body = str(index.data(EvidenceTranscriptModel.BodyRole) or "")
        attachment = str(index.data(EvidenceTranscriptModel.AttachmentRole) or "")
        use_bold = self._message_block_zone(message_index) == BLOCK_ZONE_RELEVANT
        message_font = self._message_font(bold=use_bold)
        body_height = QFontMetrics(message_font).boundingRect(
            QRect(0, 0, body_width, 4000),
            Qt.TextFlag.TextWordWrap,
            body,
        ).height()
        attachment_height = 22 if attachment else 0
        return max(
            self.min_message_height,
            (self.row_padding_y * 2) + body_height + attachment_height,
        )

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
