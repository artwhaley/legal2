"""sqlite-vec backend tests."""

import pytest

from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.embeddings.sqlite_vec_backend import validate_sqlite_vec
from message_evidence_workstation.logging_ui.process_log import ProcessLogger

pytest.importorskip("sqlite_vec", reason="sqlite-vec extension not installed")


def _sqlite_vec_available() -> bool:
    try:
        import sqlite_vec  # noqa: F401

        return True
    except ImportError:
        return False


@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "vec.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    return conn, logger


def test_validate_sqlite_vec_smoke(db) -> None:
    conn, logger = db
    result = validate_sqlite_vec(conn, logger, dimensions=4)
    if not result.success and "not authorized" in result.message:
        pytest.skip("sqlite-vec extension load not authorized in this SQLite build")
    assert result.success, result.message
