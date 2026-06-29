"""Large-dataset performance regression tests (T72).

Heavy fixtures are marked ``@pytest.mark.scale`` and excluded from the default
``python -m pytest -q`` run. Run manually or in nightly CI:

    python -m pytest -m scale -q
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import pytest

from message_evidence_workstation.db import repositories
from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.importers.normalized_loader import load_normalized_dataset
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.search import fts
from message_evidence_workstation.ui.search_worker import (
    SearchCancellationToken,
    SearchJobResult,
    SearchJobSpec,
    run_search_job,
)
from tests.test_scale_hardening import SCALE_THREAD_ID, _write_scaled_dataset

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_dataset"


@pytest.fixture
def workspace_db(tmp_path):
    evw_path = tmp_path / "regression_transcript.evw"
    conn = connect(evw_path)
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    from message_evidence_workstation.db.workspace import import_into_workspace

    dataset_id = import_into_workspace(conn, logger, FIXTURE_DIR)
    return conn, logger, dataset_id


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.mark.scale
def test_common_token_fts_first_page_bounded_on_large_fixture(tmp_path) -> None:
    dataset_dir = tmp_path / "fts_scale_dataset"
    _write_scaled_dataset(dataset_dir, message_count=20_000)

    conn = connect(tmp_path / "fts_scale.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    dataset_id = load_normalized_dataset(conn, logger, dataset_dir, run_post_import_steps=True)

    started = time.perf_counter()
    page = fts.search_messages(conn, logger, dataset_id, "message", limit=25, offset=0)
    elapsed_ms = (time.perf_counter() - started) * 1000

    assert page["total_count"] == 20_000
    assert len(page["hits"]) == 25
    assert page["has_more"] is True
    assert page["next_offset"] == 25
    assert elapsed_ms < 5_000

    fetch_calls: list[int] = []
    original = repositories.fetch_messages_by_ids

    def counting_fetch(connection, ds_id, message_ids):
        fetch_calls.append(len(message_ids))
        return original(connection, ds_id, message_ids)

    with patch(
        "message_evidence_workstation.db.repositories.fetch_messages_by_ids",
        side_effect=counting_fetch,
    ):
        hydrated = repositories.fetch_messages_by_ids(
            conn,
            dataset_id,
            [hit.message_id for hit in page["hits"]],
        )

    assert len(hydrated) == 25
    assert fetch_calls == [25]


@pytest.mark.scale
def test_no_search_on_typing_large_dataset_tab(qapp, tmp_path) -> None:
    from message_evidence_workstation.ui.simple_search_tab import SimpleSearchTab

    conn = connect(tmp_path / "typing_scale.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    dataset_id = load_normalized_dataset(conn, logger, FIXTURE_DIR)

    captured: list[str] = []

    def trace_callback(statement: str) -> None:
        captured.append(statement)

    conn.set_trace_callback(trace_callback)
    tab = SimpleSearchTab(conn, logger, db_path=tmp_path / "typing_scale.db")
    tab.set_dataset(dataset_id)
    tab.search_box.setText("message")
    qapp.processEvents()
    conn.set_trace_callback(None)

    search_sql = [s for s in captured if "message_fts" in s or ("FROM message" in s and "MATCH" in s)]
    assert search_sql == []


@pytest.mark.scale
def test_cancelled_search_suppresses_stale_results(qapp, tmp_path) -> None:
    from message_evidence_workstation.ui.simple_search_tab import SimpleSearchTab

    conn = connect(tmp_path / "cancel_scale.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    dataset_id = load_normalized_dataset(conn, logger, FIXTURE_DIR)

    tab = SimpleSearchTab(conn, logger, db_path=tmp_path / "cancel_scale.db")
    tab.set_dataset(dataset_id)
    tab.search_box.setText("the")

    tab._search_generation = 1
    stale_result = SearchJobResult(
        generation=0,
        mode="fts5",
        query="the",
        groups=[],
        total_count=999,
        page_size=25,
        offset=0,
        has_more=False,
        next_offset=None,
        elapsed_ms=1,
    )

    tab._apply_search_result(stale_result)
    assert tab._fts_total_count == 0
    assert tab.results_list.count() == 0

    token = SearchCancellationToken()
    token.cancel()
    cancelled = run_search_job(
        SearchJobSpec(
            db_path=tmp_path / "cancel_scale.db",
            dataset_id=dataset_id,
            mode="fts5",
            query="the",
            page_size=25,
            offset=0,
            generation=1,
        ),
        token,
    )
    assert cancelled.cancelled is True
    tab._search_generation = 1
    tab._apply_search_result(cancelled)
    assert tab._fts_total_count == 0
    assert "cancelled" in tab.status_label.text().lower()


@pytest.mark.scale
def test_transcript_deep_scroll_uses_indexed_ordinals(workspace_db, qapp, monkeypatch) -> None:
    from message_evidence_workstation.ui.transcript_surface import (
        Gen2TranscriptSurfaceWidget,
        build_transcript_model_for_thread,
    )

    conn, _logger, dataset_id = workspace_db
    slot_fetch_calls = 0
    original = repositories.fetch_messages_for_slot_range

    def counting_slot_fetch(*args, **kwargs):
        nonlocal slot_fetch_calls
        slot_fetch_calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(repositories, "fetch_messages_for_slot_range", counting_slot_fetch)
    model = build_transcript_model_for_thread(conn, dataset_id, "thread_001")
    assert model.message_count() == 100

    host = __import__("PySide6.QtWidgets", fromlist=["QWidget"]).QWidget()
    host.resize(900, 600)
    surface = Gen2TranscriptSurfaceWidget(model, parent=host)
    surface.resize(900, 600)
    qapp.processEvents()

    started = time.perf_counter()
    surface.scroll_to_message_index(90)
    qapp.processEvents()
    elapsed_ms = (time.perf_counter() - started) * 1000

    center = surface.viewport_center_message_index()
    assert center is not None
    assert 80 <= center <= 95
    assert elapsed_ms < 2_000
    assert slot_fetch_calls >= 1
