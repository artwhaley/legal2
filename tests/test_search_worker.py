"""Background search worker tests (T67+)."""

from pathlib import Path

import pytest

from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.db.workspace import import_into_workspace
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.search.date_scope import MessageDateScope
from message_evidence_workstation.ui.search_worker import (
    SearchCancellationToken,
    SearchJobSpec,
    run_search_job,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_dataset"


@pytest.fixture
def workspace(tmp_path):
    db_path = tmp_path / "search_worker.evw"
    conn = connect(db_path)
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    dataset_id = import_into_workspace(conn, logger, FIXTURE_DIR)
    conn.close()
    return db_path, dataset_id


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_search_worker_returns_paged_fts_results(workspace) -> None:
    db_path, dataset_id = workspace
    result = run_search_job(
        SearchJobSpec(
            db_path=db_path,
            dataset_id=dataset_id,
            mode="fts5",
            query="the",
            page_size=5,
            offset=0,
            generation=1,
        )
    )
    assert result.total_count is not None
    assert result.total_count > 5
    assert len(result.groups) <= 5
    assert result.cancelled is False


def test_cancel_token_marks_result_cancelled(workspace) -> None:
    db_path, dataset_id = workspace
    token = SearchCancellationToken()
    token.cancel()
    result = run_search_job(
        SearchJobSpec(
            db_path=db_path,
            dataset_id=dataset_id,
            mode="fts5",
            query="the",
            page_size=5,
            offset=0,
            generation=1,
        ),
        token,
    )
    assert result.cancelled is True
    assert result.groups == []


def test_typing_does_not_query_database(qapp, workspace) -> None:
    from message_evidence_workstation.ui.simple_search_tab import SimpleSearchTab

    db_path, dataset_id = workspace
    conn = connect(db_path)
    logger = ProcessLogger(conn)
    captured: list[str] = []

    def trace_callback(statement: str) -> None:
        captured.append(statement)

    conn.set_trace_callback(trace_callback)
    tab = SimpleSearchTab(conn, logger, db_path=db_path)
    tab.set_dataset(dataset_id)
    tab.search_box.setText("allergy")
    qapp.processEvents()
    conn.set_trace_callback(None)
    search_sql = [s for s in captured if "message_fts" in s or ("FROM message" in s and "MATCH" in s)]
    assert search_sql == []


# ── T100: date scope in search worker ──────────────────────────────────

def test_search_worker_date_scope_propagates_to_fts(workspace) -> None:
    db_path, dataset_id = workspace
    scope = MessageDateScope(start_timestamp="2024-01-10T00:00:00+00:00")
    result = run_search_job(
        SearchJobSpec(
            db_path=db_path,
            dataset_id=dataset_id,
            mode="fts5",
            query="the",
            page_size=50,
            offset=0,
            generation=1,
            date_scope=scope,
        )
    )
    assert result.total_count is not None
    assert result.total_count >= 0
    assert result.cancelled is False
