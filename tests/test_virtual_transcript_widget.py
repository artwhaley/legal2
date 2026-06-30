"""Tests for virtual transcript widget."""

from __future__ import annotations

from pathlib import Path

import pytest

from message_evidence_workstation.db import evidence_blocks
from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.domain.models import Message
from message_evidence_workstation.domain.slots import (
    BOUNDARY_CONTEXT_START,
    BOUNDARY_RELEVANT_START,
)
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.ui.transcript_data_source import InMemoryTranscriptDataSource
from message_evidence_workstation.ui.virtual_transcript_annotations import (
    boundary_handles_for_layouts,
    highlight_icon_rect,
    hit_icon_rect,
    zone_for_ordinal,
)
from message_evidence_workstation.ui.virtual_transcript_model import VirtualEvidenceOverlay
from message_evidence_workstation.ui.virtual_transcript_widget import VirtualTranscriptWidget, WINDOW_OVERSCAN


def _sample_message(index: int, thread_id: str = "thread_large") -> Message:
    return Message(
        message_id=f"msg_{index:05d}",
        dataset_id=1,
        source_thread_id=thread_id,
        source_platform="facebook",
        source_message_id=f"s{index}",
        timestamp=f"2024-01-01T10:{index % 60:02d}:00+00:00",
        sender_id="a",
        sender_display="Alice",
        body=f"body {index}",
        body_normalized=f"body {index}",
        has_attachment=False,
        attachment_summary="",
        sort_index=index,
        source_metadata_json={},
        thread_ordinal=index,
    )


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _widget(qapp, *, count: int = 600) -> VirtualTranscriptWidget:
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    conn = connect(Path(":memory:"))
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    conn.execute(
        """
        INSERT INTO dataset (dataset_id, name, created_at, schema_version)
        VALUES (1, 'test', '2024-01-01T00:00:00+00:00', 1)
        """
    )
    conn.commit()
    thread_id = "thread_large"
    messages = [_sample_message(index, thread_id) for index in range(count)]
    host = QWidget()
    host.resize(900, 600)
    layout = QVBoxLayout(host)
    widget = VirtualTranscriptWidget(conn, logger, host)
    layout.addWidget(widget)
    widget.set_dataset(1)
    widget.model._data_source = InMemoryTranscriptDataSource({thread_id: messages})
    widget.load_source_thread(thread_id)
    widget._pytest_host = host
    qapp.processEvents()
    return widget


def test_virtual_widget_initial_paint_bounded(qapp) -> None:
    widget = _widget(qapp, count=1500)
    assert widget.message_count == 1500
    assert widget.cached_message_count <= WINDOW_OVERSCAN * 4 + 20
    assert widget.measured_height_count <= WINDOW_OVERSCAN * 4 + 20


def test_virtual_widget_scroll_to_ordinal(qapp) -> None:
    widget = _widget(qapp, count=1500)
    assert widget.scroll_to_ordinal(50)
    start, end = widget.visible_ordinal_range
    assert start <= 50 <= end


def test_virtual_widget_deep_jump(qapp) -> None:
    widget = _widget(qapp, count=15_000)
    assert widget.scroll_to_ordinal(14_000)
    assert widget.cached_message_count < 15_000


def test_create_evidence_block_preserves_scroll_position(qapp) -> None:
    widget = _widget(qapp, count=500)
    widget.scroll_to_ordinal(200)
    qapp.processEvents()
    anchor = widget._scroll_offset_y
    block = widget.create_evidence_block_from_viewport_center(source_action="test")
    qapp.processEvents()
    assert block is not None
    assert widget._scroll_offset_y == anchor


def test_scroll_to_center_ordinal_aligns_viewport_center(qapp) -> None:
    widget = _widget(qapp, count=200)
    widget.scroll_to_ordinal(80)
    qapp.processEvents()
    assert widget.scroll_to_center_ordinal(120)
    qapp.processEvents()
    assert widget.viewport_center_ordinal() == 120


def test_virtual_widget_create_block_near_end(qapp) -> None:
    widget = _widget(qapp, count=15_000)
    widget.scroll_to_ordinal(14_000)
    block = widget.create_evidence_block_for_message("msg_14000", source_action="test")
    assert block is not None
    assert block.core_hit_message_id == "msg_14000"


def test_boundary_handles_labeled() -> None:
    overlay = VirtualEvidenceOverlay(
        evidence_block_id=1,
        context_start_slot=10,
        relevant_start_slot=12,
        relevant_end_slot=13,
        context_end_slot=15,
        core_hit_message_id="msg_00012",
        highlighted_message_ids=frozenset(),
        is_active=True,
    )
    from message_evidence_workstation.ui.virtual_transcript_annotations import MessageLayoutRect

    layouts = [
        MessageLayoutRect(ordinal=10, top=100.0, height=72.0, content_left=24, content_width=400),
        MessageLayoutRect(ordinal=12, top=244.0, height=72.0, content_left=24, content_width=400),
    ]
    handles = boundary_handles_for_layouts(overlay, layouts)
    labels = {handle.boundary_name: handle.label for handle in handles}
    assert BOUNDARY_CONTEXT_START in labels
    assert BOUNDARY_RELEVANT_START in labels
    assert "Context start" in labels.values()


def test_boundary_y_changes_with_scroll_offset(qapp) -> None:
    widget = _widget(qapp, count=1500)
    widget.scroll_to_ordinal(0)
    qapp.processEvents()
    first_layouts = list(widget._screen_layouts())
    widget.scroll_to_ordinal(200)
    qapp.processEvents()
    second_layouts = list(widget._screen_layouts())
    if first_layouts and second_layouts:
        assert first_layouts[0].top != second_layouts[0].top


def test_hit_and_highlight_controls_are_relevant_window_only(qapp) -> None:
    widget = _widget(qapp, count=100)
    block = widget.create_evidence_block_for_message("msg_00050", source_action="test")
    assert block is not None
    widget.scroll_to_center_ordinal(50)
    qapp.processEvents()
    overlay = widget.model.overlay_for_block(block.evidence_block_id)
    assert overlay is not None

    screen_layouts = {
        layout.ordinal: layout
        for layout in widget._screen_layouts()
        if overlay.context_start_slot <= layout.ordinal < overlay.context_end_slot
    }
    context_ordinal = overlay.context_start_slot
    relevant_ordinal = overlay.relevant_start_slot
    assert zone_for_ordinal(overlay, context_ordinal) == "context"
    assert zone_for_ordinal(overlay, relevant_ordinal) == "relevant"
    assert widget.model.message_zone(relevant_ordinal) == "relevant"
    assert context_ordinal in screen_layouts
    assert relevant_ordinal in screen_layouts

    relevant_hit = hit_icon_rect(screen_layouts[relevant_ordinal])
    relevant_highlight = highlight_icon_rect(screen_layouts[relevant_ordinal])
    assert relevant_hit.left() > screen_layouts[relevant_ordinal].content_left
    assert relevant_highlight.left() > relevant_hit.left()


def test_multiple_blocks_all_visible_without_active_selection(qapp) -> None:
    widget = _widget(qapp, count=100)
    block_a = widget.create_evidence_block_for_message("msg_00020", source_action="test")
    block_b = widget.create_evidence_block_for_message("msg_00060", source_action="test")
    assert block_a is not None
    assert block_b is not None
    qapp.processEvents()
    overlays = widget.model.block_overlays()
    assert len(overlays) == 2
    assert widget.model.message_zone(20) == "relevant"
    assert widget.model.message_zone(60) == "relevant"
    overlay_a = widget.model.overlay_for_block(block_a.evidence_block_id)
    overlay_b = widget.model.overlay_for_block(block_b.evidence_block_id)
    assert overlay_a is not None
    assert overlay_b is not None

    widget.scroll_to_ordinal(20)
    qapp.processEvents()
    handles_a = boundary_handles_for_layouts(overlay_a, widget._screen_layouts())
    assert handles_a

    widget.scroll_to_ordinal(60)
    qapp.processEvents()
    handles_b = boundary_handles_for_layouts(overlay_b, widget._screen_layouts())
    assert handles_b


def test_viewport_center_ordinal_tracks_scroll(qapp) -> None:
    widget = _widget(qapp, count=500)
    widget.scroll_to_ordinal(200)
    qapp.processEvents()
    center = widget.viewport_center_ordinal()
    assert center is not None
    start, end = widget.visible_ordinal_range
    assert start <= center <= end
    content_y = widget._viewport_center_content_y()
    layout = next(layout for layout in widget._layout_rects if layout.ordinal == center)
    assert layout.top <= content_y < layout.top + layout.height


def test_viewport_center_ordinal_matches_marker_with_variable_heights(qapp) -> None:
    conn = connect(Path(":memory:"))
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    conn.execute(
        """
        INSERT INTO dataset (dataset_id, name, created_at, schema_version)
        VALUES (1, 'test', '2024-01-01T00:00:00+00:00', 1)
        """
    )
    conn.commit()
    thread_id = "thread_large"
    messages = []
    for index in range(120):
        body = f"body {index}" if index % 5 else ("long body " * 40) + str(index)
        messages.append(
            Message(
                message_id=f"msg_{index:05d}",
                dataset_id=1,
                source_thread_id=thread_id,
                source_platform="facebook",
                source_message_id=f"s{index}",
                timestamp=f"2024-01-01T10:{index % 60:02d}:00+00:00",
                sender_id="a",
                sender_display="Alice",
                body=body,
                body_normalized=body,
                has_attachment=False,
                attachment_summary="",
                sort_index=index,
                source_metadata_json={},
                thread_ordinal=index,
            )
        )
    from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

    host = QWidget()
    host.resize(900, 600)
    layout = QVBoxLayout(host)
    widget = VirtualTranscriptWidget(conn, logger, host)
    layout.addWidget(widget)
    widget.set_dataset(1)
    widget.model._data_source = InMemoryTranscriptDataSource({thread_id: messages})
    widget.load_source_thread(thread_id)
    widget.scroll_to_ordinal(60)
    qapp.processEvents()
    center = widget.viewport_center_ordinal()
    assert center is not None
    content_y = widget._viewport_center_content_y()
    layout_rect = next(item for item in widget._layout_rects if item.ordinal == center)
    assert layout_rect.top <= content_y < layout_rect.top + layout_rect.height
    create_ordinal = widget.viewport_center_ordinal()
    assert create_ordinal == center


def test_delete_evidence_block_at_center(qapp) -> None:
    widget = _widget(qapp, count=100)
    block = widget.create_evidence_block_for_message("msg_00050", source_action="test")
    assert block is not None
    widget.scroll_to_ordinal(50)
    qapp.processEvents()
    overlay = widget.evidence_block_at_viewport_center()
    assert overlay is not None
    assert overlay.evidence_block_id == block.evidence_block_id
    widget._delete_evidence_block(block.evidence_block_id)
    qapp.processEvents()
    assert widget.model.overlay_for_block(block.evidence_block_id) is None
    assert widget.evidence_block_at_viewport_center() is None
