"""Tests for Load Dataset pipeline (T55)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from message_evidence_workstation.app_bootstrap import StartupLoadOptions, bootstrap_app
from message_evidence_workstation.dataset_load_pipeline import (
    DatasetLoadRequest,
    LARGEST_THREAD_WARNING_THRESHOLD,
    run_dataset_load_pipeline,
    run_embedding_pipeline,
    run_import_pipeline,
)
from message_evidence_workstation.db import repositories
from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.domain.constants import (
    IMPORT_VALIDITY_FAILED,
    IMPORT_VALIDITY_READY,
    NORMALIZED_FORMAT_VERSION,
)
from message_evidence_workstation.importers.normalized_loader import get_workspace_import_validity
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.ui.main_window import MainWindow
from message_evidence_workstation.ui.settings_tab import SettingsTab

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_dataset"


@pytest.fixture
def workspace(tmp_path):
    db_path = tmp_path / "pipeline.evw"
    conn = connect(db_path)
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    yield conn, logger, db_path
    conn.close()


def test_cli_bootstrap_defers_dataset_load(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MEW_DB_PATH", str(tmp_path / "cli.evw"))
    context = bootstrap_app(
        startup_load=StartupLoadOptions(
            dataset_path=FIXTURE_DIR,
            skip_embedding=True,
        ),
    )
    assert context.dataset_id is None

    result = run_import_pipeline(
        context.conn,
        context.logger,
        DatasetLoadRequest(
            dataset_path=FIXTURE_DIR,
            skip_import_if_existing=False,
            skip_embedding=True,
        ),
    )
    assert result.import_succeeded
    assert result.dataset_id is not None
    row = context.conn.execute(
        "SELECT COUNT(*) FROM message WHERE dataset_id = ?",
        (result.dataset_id,),
    ).fetchone()
    assert int(row[0]) > 0


def test_failed_import_leaves_tabs_disabled(tmp_path, qapp, monkeypatch) -> None:
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
    context = bootstrap_app()
    window = MainWindow(context)
    window.home_tab._selected_path = bad_dir
    window.home_tab.run_import_only(reload=True)

    assert window.context.dataset_id is None
    assert window.tabs.tabText(window._home_tab_index or 0) == "Home"
    assert not window.tabs.isTabEnabled(window.tabs.indexOf(window.simple_search_tab))
    assert window.tabs.isTabEnabled(window.tabs.indexOf(window.settings_tab))
    assert get_workspace_import_validity(context.conn) == IMPORT_VALIDITY_FAILED


def test_main_window_disables_dataset_tabs_before_load(tmp_path, qapp, monkeypatch) -> None:
    monkeypatch.setenv("MEW_DB_PATH", str(tmp_path / "ui.evw"))
    monkeypatch.setattr(
        "message_evidence_workstation.ui.home_tab.preload_embedding_model",
        lambda *args, **kwargs: False,
    )
    context = bootstrap_app()
    window = MainWindow(context)

    assert window.context.dataset_id is None
    assert window.tabs.tabText(window._home_tab_index or 0) == "Home"
    assert not window.tabs.isTabEnabled(window.tabs.indexOf(window.simple_search_tab))
    assert not window.tabs.isTabEnabled(window.tabs.indexOf(window.conversational_tab))
    assert window.tabs.isTabEnabled(window.tabs.indexOf(window.settings_tab))


def test_successful_load_keeps_home_tab_and_disables_load_button(tmp_path, qapp, monkeypatch) -> None:
    import time

    monkeypatch.setenv("MEW_DB_PATH", str(tmp_path / "ui.evw"))
    monkeypatch.setattr(
        "message_evidence_workstation.ui.home_tab.preload_embedding_model",
        lambda *args, **kwargs: False,
    )
    startup_load = StartupLoadOptions(dataset_path=FIXTURE_DIR, skip_embedding=True)
    context = bootstrap_app(startup_load=startup_load)
    window = MainWindow(context, startup_load=startup_load)
    window.show()
    deadline = time.perf_counter() + 30.0
    while time.perf_counter() < deadline:
        qapp.processEvents()
        if window.context.dataset_id is not None:
            break
        time.sleep(0.01)

    assert window.context.dataset_id is not None
    assert window._home_tab_index is not None
    assert window.tabs.widget(window._home_tab_index) is window.home_tab
    assert not window.home_tab.load_button.isEnabled()
    assert window.tabs.isTabEnabled(window.tabs.indexOf(window.simple_search_tab))
    window.close()
    qapp.processEvents()


def test_embedding_skip_smoke(workspace, monkeypatch) -> None:
    conn, logger, _db_path = workspace
    import_result = run_import_pipeline(
        conn,
        logger,
        DatasetLoadRequest(dataset_path=FIXTURE_DIR, skip_import_if_existing=False),
    )
    assert import_result.import_succeeded
    assert import_result.dataset_id is not None

    def _mock_create_adapter(*_args, **_kwargs):
        adapter = MagicMock()
        adapter.load.side_effect = RuntimeError("mock embedding failure")
        return adapter

    monkeypatch.setattr(
        "message_evidence_workstation.embeddings.adapters.create_adapter",
        _mock_create_adapter,
    )
    embed_result = run_embedding_pipeline(conn, logger, import_result.dataset_id)
    assert embed_result.import_succeeded
    assert embed_result.embedding_available is False
    assert embed_result.embedding_error


def test_largest_thread_watchdog_narrated(workspace) -> None:
    conn, logger, _db_path = workspace
    dataset_dir = Path(workspace[2]).parent / "large_thread_dataset"
    dataset_dir.mkdir()
    (dataset_dir / "dataset.json").write_text(
        json.dumps({"name": "Large Thread", "normalized_format_version": NORMALIZED_FORMAT_VERSION}),
        encoding="utf-8",
    )
    thread = {
        "source_thread_id": "thread_big",
        "source_platform": "messenger",
        "platform_thread_id": "big",
        "display_title": "Big",
        "participant_summary": "A",
        "start_ts": "2024-01-01T08:00:00+00:00",
        "end_ts": "2024-01-02T08:00:00+00:00",
        "metadata_json": {},
    }
    (dataset_dir / "source_threads.jsonl").write_text(json.dumps(thread) + "\n", encoding="utf-8")
    message_lines = []
    for index in range(1, LARGEST_THREAD_WARNING_THRESHOLD + 2):
        message_lines.append(
            json.dumps(
                {
                    "message_id": f"msg_{index:05d}",
                    "source_thread_id": "thread_big",
                    "source_platform": "messenger",
                    "source_message_id": f"big-{index}",
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
        )
    (dataset_dir / "messages.jsonl").write_text("\n".join(message_lines) + "\n", encoding="utf-8")

    narration: list[str] = []
    result = run_import_pipeline(
        conn,
        logger,
        DatasetLoadRequest(dataset_path=dataset_dir, skip_import_if_existing=False),
        narrator=narration.append,
    )
    assert result.import_succeeded
    assert any("virtualized scrolling" in line for line in narration)


def test_open_existing_dataset_skips_import(workspace) -> None:
    conn, logger, _db_path = workspace
    first = run_import_pipeline(
        conn,
        logger,
        DatasetLoadRequest(dataset_path=FIXTURE_DIR, skip_import_if_existing=False),
    )
    second = run_import_pipeline(
        conn,
        logger,
        DatasetLoadRequest(dataset_path=FIXTURE_DIR, skip_import_if_existing=True),
        narrator=lambda _line: None,
    )
    assert first.dataset_id == second.dataset_id
    assert any("existing dataset" in line.lower() for line in second.narration)


def test_full_pipeline_skip_embedding(workspace) -> None:
    conn, logger, _db_path = workspace
    result = run_dataset_load_pipeline(
        conn,
        logger,
        DatasetLoadRequest(
            dataset_path=FIXTURE_DIR,
            skip_import_if_existing=False,
            skip_embedding=True,
        ),
    )
    assert result.import_succeeded
    assert result.dataset_id is not None
    assert result.embedding_available is False
    assert get_workspace_import_validity(conn) == IMPORT_VALIDITY_READY


def test_import_pipeline_does_not_create_transcript_sessions(workspace, monkeypatch) -> None:
    conn, logger, _db_path = workspace

    result = run_import_pipeline(
        conn,
        logger,
        DatasetLoadRequest(dataset_path=FIXTURE_DIR, skip_import_if_existing=False),
    )

    assert result.import_succeeded
    assert result.dataset_id is not None
    table_row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'transcript_session'"
    ).fetchall()
    assert table_row == []


def test_background_import_leaves_ui_connection_usable(tmp_path, qapp, monkeypatch) -> None:
    import time

    monkeypatch.setenv("MEW_DB_PATH", str(tmp_path / "ui.evw"))
    monkeypatch.setattr(
        "message_evidence_workstation.ui.home_tab.preload_embedding_model",
        lambda *args, **kwargs: False,
    )
    startup_load = StartupLoadOptions(dataset_path=FIXTURE_DIR, skip_embedding=True)
    context = bootstrap_app(startup_load=startup_load)
    window = MainWindow(context, startup_load=startup_load)
    window.show()
    deadline = time.perf_counter() + 30.0
    while time.perf_counter() < deadline:
        qapp.processEvents()
        if window.context.dataset_id is not None:
            break
        time.sleep(0.01)

    assert window.context.dataset_id is not None
    row = context.conn.execute(
        "SELECT COUNT(*) FROM message WHERE dataset_id = ?",
        (window.context.dataset_id,),
    ).fetchone()
    assert int(row[0]) > 0
    threads = repositories.list_source_threads(context.conn, window.context.dataset_id)
    assert threads
    window.close()
    qapp.processEvents()
