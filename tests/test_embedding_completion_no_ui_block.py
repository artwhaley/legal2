"""Regression: embedding index-build completion must not block the UI thread."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from message_evidence_workstation.embeddings.index_jobs import IndexBuildResult
from message_evidence_workstation.ui.ui_callback_watchdog import run_ui_callback


def test_ui_callback_watchdog_asserts_on_slow_callback(monkeypatch) -> None:
    monkeypatch.setenv("MEW_STRICT_UI_CALLBACKS", "1")

    def slow() -> None:
        time.sleep(0.2)

    with pytest.raises(AssertionError, match="blocked UI thread"):
        run_ui_callback("test.slow", slow)


def test_index_build_on_success_completes_quickly(qapp, monkeypatch, tmp_path) -> None:
    from message_evidence_workstation.db.connection import connect
    from message_evidence_workstation.db.migrations import initialize_schema
    from message_evidence_workstation.logging_ui.process_log import ProcessLogger
    from message_evidence_workstation.ui.settings_tab import SettingsTab

    from message_evidence_workstation.logging_ui.log_bus import get_log_bus

    monkeypatch.setenv("MEW_STRICT_UI_CALLBACKS", "1")
    conn = connect(tmp_path / "ui.evw")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)

    tab = SettingsTab(conn, logger, get_log_bus(), dataset_id=1, db_path=tmp_path / "ui.evw")
    tab._embedding_model_ready = True
    tab.dataset_id = 1

    build = IndexBuildResult(
        success=True,
        count=10,
        elapsed_ms=1,
        model_name="test-model",
        dimensions=4,
        total_target=10,
    )

    def on_success(result: object) -> None:
        tab.build_message_index_button.setEnabled(True)
        if isinstance(result, IndexBuildResult) and result.success:
            tab.embedding_status.setText("ready")

    started = time.perf_counter()
    run_ui_callback("test.on_success", lambda: on_success(build))
    elapsed = time.perf_counter() - started
    assert elapsed < 0.05
