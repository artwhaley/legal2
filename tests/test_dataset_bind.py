"""Dataset bind must not load all messages into Python maps (T66)."""

from pathlib import Path

import pytest

from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.db.workspace import import_into_workspace
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.ui.conversational_tab import ConversationalTab
from message_evidence_workstation.ui.simple_search_tab import SimpleSearchTab

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
    evw_path = tmp_path / "dataset_bind.evw"
    conn = connect(evw_path)
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    dataset_id = import_into_workspace(conn, logger, FIXTURE_DIR)
    return conn, logger, dataset_id, evw_path


@pytest.mark.parametrize("tab_factory", [SimpleSearchTab, ConversationalTab])
def test_set_dataset_does_not_query_all_messages(qapp, workspace_db, tab_factory) -> None:
    conn, logger, dataset_id, db_path = workspace_db
    captured: list[str] = []

    def trace_callback(statement: str) -> None:
        captured.append(statement)

    conn.set_trace_callback(trace_callback)
    tab = tab_factory(conn, logger, db_path=db_path)
    tab.set_dataset(dataset_id)
    conn.set_trace_callback(None)
    forbidden = [
        statement
        for statement in captured
        if "FROM message WHERE dataset_id" in statement and "message_id" in statement
    ]
    assert forbidden == []
