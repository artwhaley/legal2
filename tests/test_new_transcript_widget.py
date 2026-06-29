"""Tests for the document-backed NewTranscriptWidget (T74-T80)."""

from __future__ import annotations

from pathlib import Path

import pytest

from message_evidence_workstation.db import evidence_blocks
from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.db.workspace import import_into_workspace
from message_evidence_workstation.domain.models import EvidenceBlock, Message
from message_evidence_workstation.domain.slots import (
    BOUNDARY_CONTEXT_END,
    BOUNDARY_CONTEXT_START,
    BOUNDARY_RELEVANT_END,
    BOUNDARY_RELEVANT_START,
)
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.ui.main_window import MainWindow
from message_evidence_workstation.ui.new_transcript_widget import NewTranscriptWidget, TranscriptBlockUserData
from message_evidence_workstation.ui.new_transcript_widget_tab import NewTranscriptWidgetTab
from message_evidence_workstation.ui.settings_tab import SettingsTab
from message_evidence_workstation.ui.transcript_data_source import InMemoryTranscriptDataSource

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_dataset"


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def workspace_db(tmp_path):
    evw_path = tmp_path / "new_transcript.evw"
    conn = connect(evw_path)
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    dataset_id = import_into_workspace(conn, logger, FIXTURE_DIR)
    return conn, logger, dataset_id


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


def _large_widget(qapp, *, count: int = 600, visible: bool = False) -> NewTranscriptWidget:
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    conn = connect(Path(":memory:"))
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    thread_id = "thread_large"
    messages = [_sample_message(index, thread_id) for index in range(count)]
    data_source = InMemoryTranscriptDataSource({thread_id: messages})

    host = QWidget()
    host.resize(900, 600)
    layout = QVBoxLayout(host)
    widget = NewTranscriptWidget(conn, logger, host)
    layout.addWidget(widget)
    widget.dataset_id = 1
    widget._data_source = data_source
    widget._source_thread_id = thread_id
    widget._message_count = count
    widget._build_document_from_sql(thread_id)
    if visible:
        host.show()
    widget._pytest_host = host
    qapp.processEvents()
    return widget


def test_new_transcript_tab_loads_thread(qapp, workspace_db) -> None:
    conn, logger, dataset_id = workspace_db
    tab = NewTranscriptWidgetTab(conn, logger)
    tab.set_dataset(dataset_id)
    tab.ensure_document_loaded()
    qapp.processEvents()

    assert tab.thread_combo.count() == 1
    widget = tab.transcript_widget
    assert widget.source_thread_id == "thread_001"
    assert widget.message_count == 100
    assert widget.document_block_count() == 100


def test_new_transcript_thread_load_populates_metadata_maps(qapp, workspace_db) -> None:
    conn, logger, dataset_id = workspace_db
    widget = NewTranscriptWidget(conn, logger)
    widget.set_dataset(dataset_id)
    widget.load_source_thread("thread_001")

    user_data = widget.message_block_user_data("msg_001")
    assert user_data is not None
    assert user_data.message_id == "msg_001"
    block = widget.block_for_ordinal(user_data.thread_ordinal)
    assert block is not None
    assert isinstance(block.userData(), TranscriptBlockUserData)


def test_new_transcript_text_is_read_only(qapp, workspace_db) -> None:
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    conn, logger, dataset_id = workspace_db
    widget = NewTranscriptWidget(conn, logger)
    widget.set_dataset(dataset_id)
    widget.load_source_thread("thread_001")
    before_text = widget.document.toPlainText()
    event = QKeyEvent(
        QEvent.Type.KeyPress,
        Qt.Key.Key_X,
        Qt.KeyboardModifier.NoModifier,
        "X",
    )
    widget.text_edit.keyPressEvent(event)
    assert widget.document.toPlainText() == before_text


def test_new_transcript_batched_load_large_thread(qapp) -> None:
    widget = _large_widget(qapp)
    assert widget.document_block_count() == 600
    assert widget.message_block_user_data("msg_00599") is not None
    assert "body 0" in widget.document.toPlainText()


def test_new_transcript_deep_overlay_formatting_is_bounded(qapp, monkeypatch) -> None:
    widget = _large_widget(qapp, count=15319, visible=True)
    format_calls = 0
    original_apply = widget._apply_block_format

    def counted_apply(block, fmt) -> None:
        nonlocal format_calls
        format_calls += 1
        original_apply(block, fmt)

    def fail_full_scan(message_index: int):
        raise AssertionError(f"deep overlay should not scan to message {message_index}")

    monkeypatch.setattr(widget, "_apply_block_format", counted_apply)
    monkeypatch.setattr(widget, "_header_block_for_message_index", fail_full_scan)

    block = EvidenceBlock(
        evidence_block_id=77,
        dataset_id=1,
        category_id=1,
        source_thread_id="thread_large",
        title="Deep evidence",
        summary="",
        core_hit_message_id="msg_15000",
        context_start_slot=14990,
        relevant_start_slot=14995,
        relevant_end_slot=15002,
        context_end_slot=15008,
        highlighted_message_ids=frozenset({"msg_15001"}),
        created_by="test",
        created_at="2024-01-01T00:00:00+00:00",
        updated_at="2024-01-01T00:00:00+00:00",
    )
    widget.append_evidence_block(block)
    widget.set_active_evidence_block(block.evidence_block_id)
    qapp.processEvents()

    assert format_calls <= 50
    assert widget.scroll_to_message("msg_15000")


def test_new_transcript_load_without_overlays_does_not_measure_all_slots(qapp, workspace_db, monkeypatch) -> None:
    conn, logger, dataset_id = workspace_db
    widget = NewTranscriptWidget(conn, logger)
    widget.set_dataset(dataset_id)

    def fail_slot_measurement() -> dict[int, int]:
        raise AssertionError("slot geometry should not be measured when there are no overlays")

    monkeypatch.setattr(widget, "_slot_y_positions", fail_slot_measurement)
    widget.load_source_thread("thread_001")

    assert widget.document_block_count() == 100
    assert "allergy form" in widget.document.toPlainText()


def test_new_transcript_scroll_to_ordinal(qapp) -> None:
    widget = _large_widget(qapp, visible=True)
    assert widget.scroll_to_ordinal(50)
    qapp.processEvents()
    center = widget.viewport_center_ordinal()
    assert center is not None
    assert 45 <= center <= 55

    assert widget.scroll_to_ordinal(500)
    qapp.processEvents()
    center = widget.viewport_center_ordinal()
    assert center is not None
    assert 495 <= center <= 505


def test_new_transcript_create_block_from_message(qapp, workspace_db) -> None:
    conn, logger, dataset_id = workspace_db
    widget = NewTranscriptWidget(conn, logger)
    widget.set_dataset(dataset_id)
    widget.load_source_thread("thread_001")

    block = widget.create_evidence_block_for_message("msg_010")
    assert block is not None
    assert block.core_hit_message_id == "msg_010"
    stored = evidence_blocks.get_evidence_block(conn, block.evidence_block_id)
    assert stored is not None
    assert stored.core_hit_message_id == "msg_010"


def test_new_transcript_boundary_persist_reload(qapp, workspace_db) -> None:
    conn, logger, dataset_id = workspace_db
    widget = NewTranscriptWidget(conn, logger)
    widget.set_dataset(dataset_id)
    widget.load_source_thread("thread_001")
    block = widget.create_evidence_block_for_message("msg_020")
    assert block is not None

    widget.move_boundary(block.evidence_block_id, BOUNDARY_CONTEXT_START, 5, persist=True)
    widget.move_boundary(block.evidence_block_id, BOUNDARY_RELEVANT_START, 18, persist=True)
    widget.move_boundary(block.evidence_block_id, BOUNDARY_RELEVANT_END, 22, persist=True)
    widget.move_boundary(block.evidence_block_id, BOUNDARY_CONTEXT_END, 25, persist=True)
    widget.persist_all_overlays()

    reloaded = evidence_blocks.get_evidence_block(conn, block.evidence_block_id)
    assert reloaded is not None
    assert reloaded.context_start_slot == 5
    assert reloaded.relevant_start_slot == 18
    assert reloaded.relevant_end_slot == 22
    assert reloaded.context_end_slot == 25

    widget.reload_current_thread()
    qapp.processEvents()
    overlay2 = widget.overlay_by_id(block.evidence_block_id)
    assert overlay2 is not None
    assert overlay2.context_start_slot == 5
    assert overlay2.context_end_slot == 25


def test_new_transcript_hit_and_highlight_persist_reload(qapp, workspace_db) -> None:
    conn, logger, dataset_id = workspace_db
    widget = NewTranscriptWidget(conn, logger)
    widget.set_dataset(dataset_id)
    widget.load_source_thread("thread_001")
    block = widget.create_evidence_block_for_message("msg_030")
    assert block is not None

    widget.move_boundary(block.evidence_block_id, BOUNDARY_RELEVANT_END, 34, persist=True)
    widget.set_hit_message(block.evidence_block_id, "msg_031", persist=True)
    widget.toggle_highlight(block.evidence_block_id, "msg_032", persist=True)
    widget.toggle_highlight(block.evidence_block_id, "msg_033", persist=True)
    widget.persist_all_overlays()

    stored = evidence_blocks.get_evidence_block(conn, block.evidence_block_id)
    assert stored is not None
    assert stored.core_hit_message_id == "msg_031"
    assert "msg_032" in stored.highlighted_message_ids
    assert "msg_033" in stored.highlighted_message_ids

    widget.reload_current_thread()
    qapp.processEvents()
    overlay = widget.overlay_by_id(block.evidence_block_id)
    assert overlay is not None
    assert overlay.core_hit_message_id == "msg_031"
    assert "msg_032" in overlay.highlighted_message_ids


def test_main_window_includes_parallel_new_transcript_tab(tmp_path, qapp, monkeypatch) -> None:
    from tests.test_ui_smoke import _bootstrap_ui_context

    monkeypatch.setattr(SettingsTab, "start_embedding_model_preload", lambda self: None)
    context = _bootstrap_ui_context(tmp_path, monkeypatch)
    window = MainWindow(context)
    labels = [window.tabs.tabText(index) for index in range(window.tabs.count())]
    assert "Transcript Widget" in labels
    assert "New Transcript Widget" in labels


def test_new_transcript_overlay_state_after_load(qapp, workspace_db) -> None:
    conn, logger, dataset_id = workspace_db
    widget = NewTranscriptWidget(conn, logger)
    widget.set_dataset(dataset_id)
    widget.load_source_thread("thread_001")
    block = widget.create_evidence_block_for_message("msg_005")
    assert block is not None
    overlay = widget.overlay_by_id(block.evidence_block_id)
    assert overlay is not None
    assert overlay.is_active is True


@pytest.mark.scale
def test_new_transcript_large_thread_load_smoke(qapp) -> None:
    widget = _large_widget(qapp, count=1500, visible=True)
    assert widget.document_block_count() == 1500
    assert widget.scroll_to_ordinal(1400)
    qapp.processEvents()
    center = widget.viewport_center_ordinal()
    assert center is not None
    assert center >= 1390
