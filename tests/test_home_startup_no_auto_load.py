"""Home tab cold-start behavior."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from message_evidence_workstation.app_bootstrap import bootstrap_app
from message_evidence_workstation.config.paths import default_dataset_path
from message_evidence_workstation.ui.main_window import MainWindow


@pytest.fixture
def donor_available() -> bool:
    return default_dataset_path() is not None


def test_home_startup_no_auto_load(tmp_path, qapp, monkeypatch, donor_available) -> None:
    monkeypatch.setenv("MEW_DB_PATH", str(tmp_path / "ui.evw"))
    monkeypatch.setattr(
        "message_evidence_workstation.ui.home_tab.preload_embedding_model",
        lambda *args, **kwargs: False,
    )
    with patch.object(Path, "exists", return_value=True):
        context = bootstrap_app()
        window = MainWindow(context)
        window.show()
        qapp.processEvents()

    assert context.dataset_id is None
    assert window.tabs.tabText(window._home_tab_index or 0) == "Home"
    assert not window.tabs.isTabEnabled(window.tabs.indexOf(window.simple_search_tab))
    assert window.home_tab.load_button.isEnabled()


def test_home_startup_no_reopen_activate(tmp_path, qapp, monkeypatch) -> None:
    from message_evidence_workstation.dataset_load_pipeline import DatasetLoadRequest, run_import_pipeline

    db_path = tmp_path / "ui.evw"
    monkeypatch.setenv("MEW_DB_PATH", str(db_path))
    monkeypatch.setattr(
        "message_evidence_workstation.ui.home_tab.preload_embedding_model",
        lambda *args, **kwargs: False,
    )
    context = bootstrap_app()
    run_import_pipeline(
        context.conn,
        context.logger,
        DatasetLoadRequest(
            dataset_path=Path(__file__).parent / "fixtures" / "sample_dataset",
            skip_import_if_existing=False,
            skip_embedding=True,
        ),
    )
    context.conn.close()

    context = bootstrap_app()
    window = MainWindow(context)
    window.show()
    qapp.processEvents()

    assert context.dataset_id is None
    assert not window.tabs.isTabEnabled(window.tabs.indexOf(window.simple_search_tab))
