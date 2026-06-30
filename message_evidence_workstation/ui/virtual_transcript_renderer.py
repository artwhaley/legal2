"""Layout and paint helpers for virtual transcript messages."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import QApplication

from message_evidence_workstation.domain.models import Message
from message_evidence_workstation.ui.transcript_display import format_timestamp_label, normalize_speaker_tints
from message_evidence_workstation.ui.virtual_transcript_annotations import MessageLayoutRect

DOCUMENT_MARGIN = 24
HEADER_HEIGHT = 18
BODY_TOP_GAP = 4
MESSAGE_GAP = 10
DATE_HEIGHT = 16
TEXT_TOP_PAD = 2
TEXT_BASELINE_NUDGE = -1
SHADING_TOP_INSET = 1
ANNOTATION_COLUMNS_WIDTH = 112
DEFAULT_ESTIMATED_HEIGHT = 72.0


@dataclass(slots=True)
class TranscriptRenderStyle:
    body_font: QFont
    header_font: QFont
    relevant_body_font: QFont
    date_font: QFont
    content_width: int
    annotation_left: int


class VirtualTranscriptRenderer:
    """Measure and paint transcript message blocks."""

    def __init__(self) -> None:
        self._speaker_tints = normalize_speaker_tints(None)
        self._participant_map: dict[str, int] = {}

    def set_participant_map(self, participant_map: dict[str, int]) -> None:
        self._participant_map = dict(participant_map)

    def style_for_width(self, viewport_width: int) -> TranscriptRenderStyle:
        content_width = max(120, viewport_width - DOCUMENT_MARGIN * 2 - ANNOTATION_COLUMNS_WIDTH)
        body_font = QFont("Segoe UI", 10)
        header_font = QFont("Segoe UI", 10)
        header_font.setWeight(QFont.Weight.DemiBold)
        relevant_body_font = QFont(body_font)
        relevant_body_font.setWeight(QFont.Weight.DemiBold)
        date_font = QFont("Segoe UI", 8)
        return TranscriptRenderStyle(
            body_font=body_font,
            header_font=header_font,
            relevant_body_font=relevant_body_font,
            date_font=date_font,
            content_width=content_width,
            annotation_left=DOCUMENT_MARGIN + content_width + 12,
        )

    def estimate_height(self, style: TranscriptRenderStyle) -> float:
        del style
        return DEFAULT_ESTIMATED_HEIGHT

    def measure_message(self, message: Message, style: TranscriptRenderStyle) -> float:
        sender_metrics = QFontMetrics(style.header_font)
        body_font = style.body_font
        body_metrics = QFontMetrics(body_font)
        wrapped = body_metrics.boundingRect(
            QRect(0, 0, style.content_width, 10_000),
            int(Qt.TextFlag.TextWordWrap),
            message.body or "",
        )
        sender_block = sender_metrics.height()
        body_block = wrapped.height()
        return float(
            TEXT_TOP_PAD
            + sender_block
            + BODY_TOP_GAP
            + body_block
            + DATE_HEIGHT
            + MESSAGE_GAP
        )

    def layout_messages(
        self,
        messages: list[Message],
        *,
        start_ordinal: int,
        start_y: float,
        style: TranscriptRenderStyle,
    ) -> tuple[list[MessageLayoutRect], float]:
        layouts: list[MessageLayoutRect] = []
        y = start_y
        for index, message in enumerate(messages):
            ordinal = start_ordinal + index
            height = self.measure_message(message, style)
            layouts.append(
                MessageLayoutRect(
                    ordinal=ordinal,
                    top=y,
                    height=height,
                    content_left=DOCUMENT_MARGIN,
                    content_width=style.content_width,
                )
            )
            y += height
        return layouts, y

    def paint_message(
        self,
        painter: QPainter,
        message: Message,
        layout: MessageLayoutRect,
        style: TranscriptRenderStyle,
        *,
        background_color: str | None = None,
        is_context: bool = False,
        is_relevant: bool = False,
        is_highlighted: bool = False,
        is_delete_preview: bool = False,
    ) -> None:
        if background_color:
            painter.fillRect(
                layout.content_left - 8,
                int(layout.top + SHADING_TOP_INSET),
                layout.content_width + 16,
                max(1, int(layout.height - SHADING_TOP_INSET * 2)),
                background_color,
            )
        if is_delete_preview:
            sender_font = QFont(style.header_font)
            sender_font.setWeight(QFont.Weight.Bold)
            painter.setFont(sender_font)
        else:
            painter.setFont(style.header_font)
        sender_metrics = QFontMetrics(style.header_font)
        sender_key = (message.sender_id or message.sender_display or "").strip()
        participant_index = self._participant_map.get(sender_key, 0)
        tint = self._speaker_tints[participant_index % len(self._speaker_tints)]
        sender_top = int(layout.top + TEXT_TOP_PAD)
        if not is_context:
            painter.fillRect(
                layout.content_left - 4,
                sender_top,
                layout.content_width + 8,
                sender_metrics.height() + 2,
                tint,
            )
        painter.setPen("#111111" if is_delete_preview else ("#8a8a8a" if is_context else "#111111"))
        sender_baseline = sender_top + sender_metrics.ascent() + TEXT_BASELINE_NUDGE
        painter.drawText(
            layout.content_left,
            sender_baseline,
            message.sender_display or message.sender_id or "Unknown",
        )
        if is_highlighted or is_delete_preview:
            body_font = QFont(style.relevant_body_font)
            body_font.setWeight(QFont.Weight.Bold)
        elif is_relevant:
            body_font = style.relevant_body_font
        else:
            body_font = style.body_font
        painter.setFont(body_font)
        painter.setPen("#111111" if is_delete_preview else ("#777777" if is_context else "#111111"))
        body_top = sender_baseline + sender_metrics.descent() + BODY_TOP_GAP
        body_rect = QRect(
            layout.content_left,
            body_top,
            layout.content_width,
            max(1, int(layout.height - (body_top - layout.top) - DATE_HEIGHT - MESSAGE_GAP)),
        )
        painter.drawText(
            body_rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap),
            message.body or "",
        )
        painter.setFont(style.date_font)
        painter.setPen("#9a9a9a" if is_context else "#666666")
        date_metrics = QFontMetrics(style.date_font)
        timestamp = format_timestamp_label(message.timestamp)
        date_baseline = int(layout.top + layout.height - MESSAGE_GAP - date_metrics.descent())
        painter.drawText(
            layout.content_left,
            date_baseline,
            timestamp,
        )

    def paint_annotation_column_headers(self, painter: QPainter, *, hit_rect: QRect, highlight_rect: QRect) -> None:
        painter.setPen("#555555")
        painter.setFont(QFont("Segoe UI", 7, QFont.Weight.DemiBold))
        painter.drawText(
            hit_rect,
            int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap),
            "Primary Key",
        )
        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
        painter.drawText(highlight_rect, int(Qt.AlignmentFlag.AlignCenter), "Highlight")

    def paint_boundary_handle(
        self,
        painter: QPainter,
        *,
        label: str,
        rect: QRect,
        active: bool,
    ) -> None:
        painter.fillRect(rect, "#ffffff" if active else "#f5f5f5")
        painter.setPen("#0b6dd8" if active else "#666666")
        painter.drawRect(rect)
        painter.setFont(QFont("Segoe UI", 8))
        painter.drawText(rect.adjusted(4, 0, -4, 0), int(Qt.AlignmentFlag.AlignVCenter), label)

    def paint_hit_marker(self, painter: QPainter, rect: QRect, *, active: bool) -> None:
        painter.setBrush("#0b6dd8" if active else "#ffffff")
        painter.setPen("#0b6dd8" if active else "#777777")
        painter.drawEllipse(rect)
        if active:
            inner = rect.adjusted(4, 4, -4, -4)
            painter.setBrush("#ffffff")
            painter.setPen("#ffffff")
            painter.drawEllipse(inner)

    def paint_highlight_marker(self, painter: QPainter, rect: QRect, *, active: bool) -> None:
        painter.fillRect(rect, "#fff4ad" if active else "#ffffff")
        painter.setPen("#b88900" if active else "#777777")
        painter.drawRect(rect)
        if active:
            painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), "✓")

    @staticmethod
    def ensure_application_fonts() -> None:
        if QApplication.instance() is None:
            return
