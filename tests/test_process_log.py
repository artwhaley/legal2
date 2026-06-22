"""Process log service tests."""

import sqlite3

import pytest

from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.logging_ui.log_bus import LogBus
from message_evidence_workstation.logging_ui.process_log import ProcessLogger, fetch_process_logs


@pytest.fixture
def logger_setup(tmp_path):
    from message_evidence_workstation.db.connection import connect

    conn = connect(tmp_path / "test.db")
    bus = LogBus()
    logger = ProcessLogger(conn, log_bus=bus)
    initialize_schema(conn, logger)
    return conn, logger, bus


def test_process_log_insert_and_retrieve(logger_setup) -> None:
    conn, logger, _bus = logger_setup
    logger.info(
        component="tests.process_log",
        operation="insert_info",
        message="hello process log",
        details={"foo": "bar"},
    )
    rows = fetch_process_logs(conn)
    assert any(row.message == "hello process log" for row in rows)
    assert any(row.details_json == {"foo": "bar"} for row in rows)


def test_process_log_exception_fields(logger_setup) -> None:
    conn, logger, _bus = logger_setup
    try:
        raise ValueError("boom")
    except ValueError as exc:
        logger.error(
            component="tests.process_log",
            operation="forced_exception",
            message="exception test",
            exc=exc,
        )
    rows = fetch_process_logs(conn, severity="error")
    error_rows = [row for row in rows if row.operation == "forced_exception"]
    assert len(error_rows) == 1
    row = error_rows[0]
    assert row.exception_type == "ValueError"
    assert row.stack_trace is not None
    assert "boom" in row.stack_trace


def test_log_bus_receives_live_entries(logger_setup) -> None:
    from PySide6.QtWidgets import QApplication

    _conn, logger, bus = logger_setup
    app = QApplication.instance() or QApplication([])
    received: list[dict] = []
    bus.subscribe(received.append)
    logger.warning(
        component="tests.process_log",
        operation="bus_publish",
        message="live bus entry",
    )
    app.processEvents()
    assert received
    assert received[-1]["message"] == "live bus entry"
