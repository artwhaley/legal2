"""Annotation geometry helpers for the virtual transcript widget."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRect

from message_evidence_workstation.domain.slots import (
    ALL_BOUNDARIES,
    BOUNDARY_CONTEXT_END,
    BOUNDARY_CONTEXT_START,
    BOUNDARY_RELEVANT_END,
    BOUNDARY_RELEVANT_START,
)
from message_evidence_workstation.ui.virtual_transcript_model import VirtualEvidenceOverlay

BOUNDARY_LABELS = {
    BOUNDARY_CONTEXT_START: "Context start",
    BOUNDARY_RELEVANT_START: "Relevant start",
    BOUNDARY_RELEVANT_END: "Relevant end",
    BOUNDARY_CONTEXT_END: "Context end",
}

HANDLE_HEIGHT = 10
HANDLE_WIDTH = 112
HIT_RADIUS = 8
HIGHLIGHT_SIZE = 12
CONTROL_TOP_OFFSET = 20
CONTROL_COLUMN_WIDTH = 48


@dataclass(slots=True)
class MessageLayoutRect:
    ordinal: int
    top: float
    height: float
    content_left: int
    content_width: int


@dataclass(slots=True)
class BoundaryHandleRect:
    boundary_name: str
    evidence_block_id: int
    label: str
    rect: QRect


def zone_for_ordinal(overlay: VirtualEvidenceOverlay, ordinal: int) -> str | None:
    if ordinal < overlay.context_start_slot or ordinal >= overlay.context_end_slot:
        return None
    if overlay.relevant_start_slot <= ordinal < overlay.relevant_end_slot:
        return "relevant"
    return "context"


def boundary_y_for_ordinal(layout: MessageLayoutRect) -> float:
    return layout.top


def boundary_handles_for_layouts(
    overlay: VirtualEvidenceOverlay,
    layouts: list[MessageLayoutRect],
) -> list[BoundaryHandleRect]:
    layout_by_ordinal = {layout.ordinal: layout for layout in layouts}
    handles: list[BoundaryHandleRect] = []
    boundary_slots = {
        BOUNDARY_CONTEXT_START: overlay.context_start_slot,
        BOUNDARY_RELEVANT_START: overlay.relevant_start_slot,
        BOUNDARY_RELEVANT_END: overlay.relevant_end_slot,
        BOUNDARY_CONTEXT_END: overlay.context_end_slot,
    }
    for boundary_name in ALL_BOUNDARIES:
        ordinal = boundary_slots[boundary_name]
        layout = layout_by_ordinal.get(ordinal)
        if layout is None:
            continue
        top = int(boundary_y_for_ordinal(layout))
        rect = QRect(layout.content_left - HANDLE_WIDTH - 8, top - 2, HANDLE_WIDTH, HANDLE_HEIGHT)
        handles.append(
            BoundaryHandleRect(
                boundary_name=boundary_name,
                evidence_block_id=overlay.evidence_block_id,
                label=BOUNDARY_LABELS[boundary_name],
                rect=rect,
            )
        )
    return handles


def hit_icon_rect(
    layout: MessageLayoutRect,
    overlay_index: int = 0,
    overlay_count: int = 1,
) -> QRect:
    column_left = layout.content_left + layout.content_width + 18
    slot_width = CONTROL_COLUMN_WIDTH / max(1, overlay_count)
    size = HIT_RADIUS * 2
    x = int(column_left + (overlay_index * slot_width) + ((slot_width - size) / 2))
    return QRect(
        x,
        int(layout.top + CONTROL_TOP_OFFSET),
        size,
        size,
    )


def highlight_icon_rect(
    layout: MessageLayoutRect,
    overlay_index: int = 0,
    overlay_count: int = 1,
) -> QRect:
    column_left = layout.content_left + layout.content_width + 72
    slot_width = (CONTROL_COLUMN_WIDTH + 16) / max(1, overlay_count)
    x = int(column_left + (overlay_index * slot_width) + ((slot_width - HIGHLIGHT_SIZE) / 2))
    return QRect(
        x,
        int(layout.top + CONTROL_TOP_OFFSET + 2),
        HIGHLIGHT_SIZE,
        HIGHLIGHT_SIZE,
    )


def hit_header_rect(layout: MessageLayoutRect) -> QRect:
    return QRect(
        layout.content_left + layout.content_width,
        int(layout.top + 2),
        CONTROL_COLUMN_WIDTH + 16,
        20,
    )


def highlight_header_rect(layout: MessageLayoutRect) -> QRect:
    return QRect(
        layout.content_left + layout.content_width + CONTROL_COLUMN_WIDTH,
        int(layout.top + 2),
        CONTROL_COLUMN_WIDTH + 16,
        16,
    )
