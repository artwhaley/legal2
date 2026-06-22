"""Evidence workspace (.evw) file tests."""

from pathlib import Path

import pytest

from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.migrations import get_schema_version, initialize_schema
from message_evidence_workstation.db.workspace import (
    EVW_EXTENSION,
    WorkspaceError,
    create_workspace,
    get_workspace_metadata,
    import_into_workspace,
    open_workspace,
    open_or_create_workspace,
    validate_workspace,
)
from message_evidence_workstation.domain.constants import SCHEMA_VERSION, WORKSPACE_FORMAT_ID
from message_evidence_workstation.logging_ui.process_log import ProcessLogger

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_dataset"


@pytest.fixture
def logger(tmp_path):
    conn = connect(tmp_path / "logger.db")
    return ProcessLogger(conn)


def test_create_workspace_uses_evw_extension(tmp_path, logger) -> None:
    path = tmp_path / "case_alpha"
    conn = create_workspace(path, logger)
    assert path.with_suffix(EVW_EXTENSION).exists()
    metadata = validate_workspace(conn)
    assert metadata["format_id"] == WORKSPACE_FORMAT_ID
    assert metadata["display_name"] == "case_alpha"


def test_open_workspace_rejects_missing_file(tmp_path, logger) -> None:
    with pytest.raises(WorkspaceError):
        open_workspace(tmp_path / "missing.evw", logger)


def test_import_into_workspace_loads_dataset_and_metadata(tmp_path, logger) -> None:
    evw_path = tmp_path / "workspace.evw"
    conn = create_workspace(evw_path, logger)
    dataset_id = import_into_workspace(conn, logger, FIXTURE_DIR)
    assert dataset_id == 1
    row = conn.execute("SELECT COUNT(*) AS count FROM message WHERE dataset_id = ?", (dataset_id,)).fetchone()
    assert int(row["count"]) == 5
    metadata = get_workspace_metadata(conn)
    assert metadata["format_id"] == WORKSPACE_FORMAT_ID
    assert "updated_at" in metadata


def test_open_or_create_workspace_is_idempotent(tmp_path, logger, monkeypatch) -> None:
    evw_path = tmp_path / "repeat.evw"
    monkeypatch.setenv("MEW_WORKSPACE_PATH", str(evw_path))
    first = open_or_create_workspace(evw_path, logger)
    second = open_or_create_workspace(evw_path, logger)
    assert get_schema_version(first) == SCHEMA_VERSION
    assert get_schema_version(second) == SCHEMA_VERSION


def test_schema_migration_adds_evidence_tables(tmp_path) -> None:
    legacy_path = tmp_path / "legacy.db"
    conn = connect(legacy_path)
    legacy_logger = ProcessLogger(conn)
    conn.executescript(
        """
        CREATE TABLE schema_version (version INTEGER NOT NULL);
        INSERT INTO schema_version (version) VALUES (1);
        CREATE TABLE dataset (
            dataset_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            schema_version INTEGER NOT NULL,
            notes TEXT NOT NULL DEFAULT ''
        );
        """
    )
    conn.commit()
    initialize_schema(conn, legacy_logger)
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    }
    assert "evidence_block" in tables
    assert "workspace_metadata" in tables
    assert get_schema_version(conn) == SCHEMA_VERSION
