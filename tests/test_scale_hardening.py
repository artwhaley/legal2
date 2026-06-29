"""Pre-scale hardening regression tests (T63).

Heavy fixtures are marked ``@pytest.mark.scale`` and excluded from the default
``python -m pytest -q`` run. Run manually or in nightly CI:

    python -m pytest -m scale -q
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from message_evidence_workstation.app_bootstrap import bootstrap_app
from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.domain.constants import (
    IMPORT_VALIDITY_FAILED,
    IMPORT_VALIDITY_LOADING,
    NORMALIZED_FORMAT_VERSION,
)
from message_evidence_workstation.domain.models import Message
from message_evidence_workstation.importers.normalized_loader import (
    get_dataset_import_validity,
    get_workspace_import_validity,
    load_normalized_dataset,
)
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.search.window_planner import build_token_bounded_windows_for_dataset
from message_evidence_workstation.ui.main_window import MainWindow
from message_evidence_workstation.ui.settings_tab import SettingsTab
from message_evidence_workstation.ui.transcript_data_source import InMemoryTranscriptDataSource
from message_evidence_workstation.ui.transcript_surface import (
    EvidenceTranscriptModel,
    Gen2TranscriptSurfaceWidget,
)

SCALE_THREAD_ID = "thread_scale"


def _write_scaled_dataset(
    dataset_dir: Path,
    *,
    message_count: int,
    name: str = "Scale Dataset",
) -> None:
    dataset_dir.mkdir(parents=True, exist_ok=True)
    (dataset_dir / "dataset.json").write_text(
        json.dumps(
            {
                "name": name,
                "normalized_format_version": NORMALIZED_FORMAT_VERSION,
            }
        ),
        encoding="utf-8",
    )
    thread = {
        "source_thread_id": SCALE_THREAD_ID,
        "source_platform": "messenger",
        "platform_thread_id": "scale-thread",
        "display_title": "Scale Thread",
        "participant_summary": "A",
        "start_ts": "2024-01-01T08:00:00+00:00",
        "end_ts": "2024-01-02T08:00:00+00:00",
        "metadata_json": {},
    }
    (dataset_dir / "source_threads.jsonl").write_text(json.dumps(thread) + "\n", encoding="utf-8")
    with (dataset_dir / "messages.jsonl").open("w", encoding="utf-8") as messages_file:
        for index in range(1, message_count + 1):
            messages_file.write(
                json.dumps(
                    {
                        "message_id": f"msg_{index:06d}",
                        "source_thread_id": SCALE_THREAD_ID,
                        "source_platform": "messenger",
                        "source_message_id": f"scale-{index}",
                        "timestamp": "2024-01-01T08:00:00+00:00",
                        "sender_id": "a",
                        "sender_display": "A",
                        "body": f"Message {index}",
                        "has_attachment": False,
                        "attachment_summary": "",
                        "sort_index": index,
                        "source_metadata_json": {},
                    }
                )
                + "\n"
            )


def _sample_message(index: int, thread_id: str = SCALE_THREAD_ID) -> Message:
    return Message(
        message_id=f"msg_{index:06d}",
        dataset_id=1,
        source_thread_id=thread_id,
        source_platform="messenger",
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


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.mark.scale
def test_streaming_import_100k_messages(tmp_path) -> None:
    dataset_dir = tmp_path / "100k_dataset"
    _write_scaled_dataset(dataset_dir, message_count=100_000)

    conn = connect(tmp_path / "100k.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    dataset_id = load_normalized_dataset(
        conn,
        logger,
        dataset_dir,
        run_post_import_steps=False,
    )

    stored = conn.execute(
        "SELECT COUNT(*) FROM message WHERE dataset_id = ?",
        (dataset_id,),
    ).fetchone()[0]
    assert stored == 100_000
    assert get_dataset_import_validity(conn, dataset_id) == IMPORT_VALIDITY_LOADING
    assert get_workspace_import_validity(conn) == IMPORT_VALIDITY_LOADING


@pytest.mark.scale
def test_failed_import_leaves_stale_state_and_disabled_tabs(tmp_path, qapp, monkeypatch) -> None:
    bad_dir = tmp_path / "bad_dataset"
    bad_dir.mkdir()
    (bad_dir / "dataset.json").write_text(json.dumps({"name": "Bad"}), encoding="utf-8")
    (bad_dir / "source_threads.jsonl").write_text("", encoding="utf-8")
    (bad_dir / "messages.jsonl").write_text("{not json}\n", encoding="utf-8")

    monkeypatch.setenv("MEW_DB_PATH", str(tmp_path / "ui.evw"))
    monkeypatch.setattr(
        "message_evidence_workstation.ui.home_tab.preload_embedding_model",
        lambda *args, **kwargs: False,
    )
    window.home_tab._selected_path = bad_dir
    window.home_tab.run_import_only(reload=True)

    assert window.context.dataset_id is None
    assert window.tabs.tabText(window._home_tab_index or 0) == "Home"
    assert not window.tabs.isTabEnabled(window.tabs.indexOf(window.simple_search_tab))
    assert window.tabs.isTabEnabled(window.tabs.indexOf(window.settings_tab))
    assert get_workspace_import_validity(context.conn) == IMPORT_VALIDITY_FAILED


@pytest.mark.scale
def test_50k_transcript_navigation_smoke(qapp) -> None:
    from PySide6.QtWidgets import QWidget

    messages = [_sample_message(index) for index in range(50_000)]
    data_source = InMemoryTranscriptDataSource({SCALE_THREAD_ID: messages})
    model = EvidenceTranscriptModel()
    model.load_thread_virtualized(data_source, SCALE_THREAD_ID, [])

    host = QWidget()
    host.resize(900, 600)
    surface = Gen2TranscriptSurfaceWidget(model, parent=host)
    surface.resize(900, 600)
    qapp.processEvents()

    started = time.perf_counter()
    surface.scroll_to_message_index(47_500)
    qapp.processEvents()
    elapsed_ms = (time.perf_counter() - started) * 1000

    center = surface.viewport_center_message_index()
    assert center is not None
    assert 47_480 <= center <= 47_520
    assert elapsed_ms < 2_000


@pytest.mark.scale
def test_50k_exhaustive_scan_planner_bounded(tmp_path, monkeypatch) -> None:
    from types import SimpleNamespace

    from message_evidence_workstation.search import window_planner

    dataset_dir = tmp_path / "50k_dataset"
    _write_scaled_dataset(dataset_dir, message_count=50_000, name="Planner Scale")

    conn = connect(tmp_path / "50k.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    dataset_id = load_normalized_dataset(
        conn,
        logger,
        dataset_dir,
        run_post_import_steps=False,
    )

    load_calls = 0
    original = window_planner.load_thread_messages

    def counting_load(*args, **kwargs):
        nonlocal load_calls
        load_calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(window_planner, "load_thread_messages", counting_load)

    streamed = sum(
        1
        for _ in window_planner.iter_thread_messages_for_window_planning(
            conn,
            dataset_id,
            SCALE_THREAD_ID,
        )
    )
    assert streamed == 50_000
    assert load_calls == 0

    def fast_serialize(messages, **kwargs):
        message_ids = [message.message_id for message in messages]
        return SimpleNamespace(text="\n".join(message_ids), message_ids=message_ids)

    def fast_estimate(text, model_id):
        return SimpleNamespace(estimated_tokens=max(1, len(text) // 8))

    monkeypatch.setattr(window_planner, "serialize_messages", fast_serialize)
    monkeypatch.setattr(window_planner, "estimate_tokens", fast_estimate)
    windows = build_token_bounded_windows_for_dataset(
        conn,
        dataset_id,
        target_tokens=50_000,
        overlap_messages=0,
        model_id="test-model",
    )

    assert load_calls == 0
    assert windows
    covered = {message_id for window in windows for message_id in window.message_ids}
    assert len(covered) == 50_000
