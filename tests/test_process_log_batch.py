"""Process log batch mode tests."""

from __future__ import annotations

import pytest

from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.logging_ui.process_log import ProcessLogger


@pytest.fixture
def log_db(tmp_path):
    conn = connect(tmp_path / "process_log.db")
    logger = ProcessLogger(conn, log_bus=None)
    initialize_schema(conn, logger)
    return conn, logger


def _test_log_count(conn) -> int:
    return int(
        conn.execute(
            "SELECT COUNT(*) FROM process_log WHERE component = 'test.batch'"
        ).fetchone()[0]
    )


def test_batch_context_commits_once_for_short_operation(log_db) -> None:
    conn, logger = log_db
    with logger.batch() as blog:
        blog.info("test.batch", "batch", "one")
        blog.info("test.batch", "batch", "two")
        blog.info("test.batch", "batch", "three")
    assert _test_log_count(conn) == 3


def test_batch_context_flushes_on_exception(log_db) -> None:
    conn, logger = log_db
    with pytest.raises(RuntimeError):
        with logger.batch() as blog:
            blog.info("test.batch", "batch", "before-error")
            raise RuntimeError("boom")
    assert _test_log_count(conn) == 1


def test_batch_error_logs_immediately(log_db) -> None:
    conn, logger = log_db
    with logger.batch() as blog:
        blog.info("test.batch", "batch", "queued")
        blog.error("test.batch", "batch", "fatal", exc=ValueError("bad"))
    rows = conn.execute(
        """
        SELECT severity, message FROM process_log
        WHERE component = 'test.batch'
        ORDER BY process_log_id
        """
    ).fetchall()
    assert [row["severity"] for row in rows] == ["info", "error"]
    assert rows[1]["message"] == "fatal"
