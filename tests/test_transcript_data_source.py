"""TranscriptDataSource paging tests (T56)."""

from pathlib import Path

import pytest

from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.db.repositories import (
    fetch_message_ids_for_thread,
    list_messages_for_thread,
    message_index_in_thread,
    thread_message_count,
)
from message_evidence_workstation.db.workspace import import_into_workspace
from message_evidence_workstation.domain.models import Message
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.ui.transcript_data_source import InMemoryTranscriptDataSource, SqlTranscriptDataSource
from message_evidence_workstation.ui.transcript_surface import WINDOW_OVERSCAN, EvidenceTranscriptModel

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_dataset"


@pytest.fixture
def workspace_db(tmp_path):
    evw_path = tmp_path / "transcript_data_source.evw"
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
    )


def test_sql_transcript_data_source_paging(workspace_db) -> None:
    conn, _logger, dataset_id = workspace_db
    data_source = SqlTranscriptDataSource(conn, dataset_id)
    assert data_source.message_count("thread_001") == 100
    page = data_source.fetch_messages("thread_001", 10, 5)
    assert [message.message_id for message in page] == [
        f"msg_{index:03d}" for index in range(11, 16)
    ]
    assert data_source.message_index_for_id("thread_001", "msg_050") == 49
    assert data_source.ordered_message_ids("thread_001")[:3] == ["msg_001", "msg_002", "msg_003"]


def test_repository_thread_helpers(workspace_db) -> None:
    conn, _logger, dataset_id = workspace_db
    assert thread_message_count(conn, dataset_id, "thread_001") == 100
    assert message_index_in_thread(conn, dataset_id, "thread_001", "msg_010") == 9
    assert fetch_message_ids_for_thread(conn, dataset_id, "thread_001")[-1] == "msg_100"


def test_in_memory_data_source_windowing() -> None:
    messages = [_sample_message(index) for index in range(250)]
    data_source = InMemoryTranscriptDataSource({"thread_large": messages})
    assert data_source.message_count("thread_large") == 250
    window = data_source.fetch_messages("thread_large", 100, 20)
    assert len(window) == 20
    assert window[0].message_id == "msg_00100"
    assert data_source.message_index_for_id("thread_large", "msg_00200") == 200


def test_virtualized_model_keeps_window_only() -> None:
    messages = [_sample_message(index) for index in range(500)]
    data_source = InMemoryTranscriptDataSource({"thread_large": messages})
    model = EvidenceTranscriptModel()
    model.load_thread_virtualized(data_source, "thread_large", [])
    assert model.message_count() == 500
    assert model.rowCount() == (500 * 2) + 1
    assert len(model._messages) < 500
    model.ensure_window(300, 320)
    assert len(model._messages) <= (320 - 300 + 1) + (WINDOW_OVERSCAN * 2)
    assert model._message_at(310) is not None
    assert model._message_at(310).message_id == "msg_00310"
    assert len(model._messages) < 500


@pytest.mark.scale
def test_virtualized_surface_layout_change_does_not_recurse(qapp) -> None:
    from PySide6.QtWidgets import QWidget

    from message_evidence_workstation.ui.transcript_surface import Gen2TranscriptSurfaceWidget

    messages = [_sample_message(index) for index in range(2_000)]
    data_source = InMemoryTranscriptDataSource({"thread_large": messages})
    model = EvidenceTranscriptModel()
    model.load_thread_virtualized(data_source, "thread_large", [])

    host = QWidget()
    host.resize(900, 600)
    surface = Gen2TranscriptSurfaceWidget(model, parent=host)
    surface.resize(900, 600)
    qapp.processEvents()

    model.ensure_window(1500, 1550)
    qapp.processEvents()
    surface.scroll_to_message_index(1525)
    qapp.processEvents()

    center = surface.viewport_center_message_index()
    assert center is not None
    assert 1500 <= center <= 1550


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.mark.scale
def test_build_transcript_model_for_thread_avoids_full_thread_load(workspace_db, monkeypatch) -> None:
    from message_evidence_workstation.db import repositories
    from message_evidence_workstation.ui.transcript_surface import build_transcript_model_for_thread

    conn, _logger, dataset_id = workspace_db
    calls = 0
    original = repositories.list_messages_for_thread

    def counting_list(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(repositories, "list_messages_for_thread", counting_list)
    model = build_transcript_model_for_thread(conn, dataset_id, "thread_001")
    assert calls == 0
    assert model.message_count() == 100

    import time

    from PySide6.QtWidgets import QWidget

    from message_evidence_workstation.ui.transcript_surface import Gen2TranscriptSurfaceWidget

    messages = [_sample_message(index) for index in range(10_000)]
    data_source = InMemoryTranscriptDataSource({"thread_large": messages})
    model = EvidenceTranscriptModel()
    model.load_thread_virtualized(data_source, "thread_large", [])

    host = QWidget()
    host.resize(900, 600)
    surface = Gen2TranscriptSurfaceWidget(model, parent=host)
    surface.resize(900, 600)
    qapp.processEvents()

    started = time.perf_counter()
    surface.scroll_to_message_index(9500)
    qapp.processEvents()
    elapsed_ms = (time.perf_counter() - started) * 1000

    center = surface.viewport_center_message_index()
    assert center is not None
    assert 9480 <= center <= 9520
    assert elapsed_ms < 500
