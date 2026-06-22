"""Audit export tests (T22)."""

from pathlib import Path

from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.export.audit_export import (
    export_audit_bundle,
    export_process_log_json,
    export_process_log_text,
    list_model_runs,
)
from message_evidence_workstation.importers.normalized_loader import load_normalized_dataset
from message_evidence_workstation.logging_ui.process_log import ProcessLogger

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_dataset"


def test_export_process_logs(tmp_path) -> None:
    conn = connect(tmp_path / "audit.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    dataset_id = load_normalized_dataset(conn, logger, FIXTURE_DIR)
    logger.info(
        component="tests.audit_export",
        operation="sample_log",
        message="Sample audit log entry",
        dataset_id=dataset_id,
    )
    json_path = tmp_path / "logs.json"
    text_path = tmp_path / "logs.txt"
    assert export_process_log_json(conn, json_path, dataset_id=dataset_id) > 0
    assert export_process_log_text(conn, text_path, dataset_id=dataset_id) > 0
    assert "Sample audit log entry" in text_path.read_text(encoding="utf-8")


def test_list_model_runs_empty(tmp_path) -> None:
    conn = connect(tmp_path / "runs.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    assert list_model_runs(conn) == []


def test_export_audit_bundle(tmp_path) -> None:
    conn = connect(tmp_path / "bundle.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    load_normalized_dataset(conn, logger, FIXTURE_DIR)
    out_dir = tmp_path / "audit_bundle"
    sizes = export_audit_bundle(conn, logger, out_dir)
    assert sizes["process_log_json"] > 0
    assert (out_dir / "process_log.json").is_file()
    assert (out_dir / "model_runs.json").is_file()
