"""Process log and ModelRun export helpers (T22)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from message_evidence_workstation.domain.models import ModelRunSummary, ProcessLogEntry
from message_evidence_workstation.logging_ui.process_log import ProcessLogger, fetch_process_logs


def export_process_log_json(
    conn: sqlite3.Connection,
    output_path: Path,
    *,
    dataset_id: int | None = None,
    limit: int = 5000,
) -> int:
    entries = fetch_process_logs(conn, limit=limit)
    if dataset_id is not None:
        entries = [entry for entry in entries if entry.dataset_id == dataset_id]
    payload = [
        {
            "process_log_id": entry.process_log_id,
            "dataset_id": entry.dataset_id,
            "timestamp": entry.timestamp,
            "severity": entry.severity,
            "component": entry.component,
            "operation": entry.operation,
            "message": entry.message,
            "details_json": entry.details_json,
            "exception_type": entry.exception_type,
            "stack_trace": entry.stack_trace,
        }
        for entry in entries
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return output_path.stat().st_size


def export_process_log_text(
    conn: sqlite3.Connection,
    output_path: Path,
    *,
    dataset_id: int | None = None,
    limit: int = 5000,
) -> int:
    entries = fetch_process_logs(conn, limit=limit)
    if dataset_id is not None:
        entries = [entry for entry in entries if entry.dataset_id == dataset_id]
    lines = []
    for entry in entries:
        lines.append(
            f"[{entry.timestamp}] {entry.severity} {entry.component}.{entry.operation}: {entry.message}"
        )
        if entry.exception_type:
            lines.append(f"  exception={entry.exception_type}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path.stat().st_size


def list_model_runs(
    conn: sqlite3.Connection,
    *,
    dataset_id: int | None = None,
    limit: int = 200,
) -> list[ModelRunSummary]:
    if dataset_id is None:
        rows = conn.execute(
            """
            SELECT mr.model_run_id, mr.dataset_id, mr.run_type, mr.model, mr.prompt_template_id,
                   mr.input_summary, mr.created_at, mr.latency_ms, mr.error_type, mr.error_message,
                   pt.version AS prompt_version
            FROM model_run mr
            LEFT JOIN prompt_template pt ON pt.prompt_template_id = mr.prompt_template_id
            ORDER BY mr.model_run_id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT mr.model_run_id, mr.dataset_id, mr.run_type, mr.model, mr.prompt_template_id,
                   mr.input_summary, mr.created_at, mr.latency_ms, mr.error_type, mr.error_message,
                   pt.version AS prompt_version
            FROM model_run mr
            LEFT JOIN prompt_template pt ON pt.prompt_template_id = mr.prompt_template_id
            WHERE mr.dataset_id = ?
            ORDER BY mr.model_run_id DESC
            LIMIT ?
            """,
            (dataset_id, limit),
        ).fetchall()
    return [
        ModelRunSummary(
            model_run_id=int(row["model_run_id"]),
            dataset_id=row["dataset_id"],
            run_type=str(row["run_type"]),
            model=str(row["model"]),
            prompt_template_id=row["prompt_template_id"],
            prompt_version=row["prompt_version"],
            input_summary=str(row["input_summary"] or ""),
            created_at=str(row["created_at"]),
            latency_ms=row["latency_ms"],
            error_type=row["error_type"],
            error_message=row["error_message"],
        )
        for row in reversed(rows)
    ]


def get_model_run_detail(conn: sqlite3.Connection, model_run_id: int) -> dict[str, object] | None:
    row = conn.execute(
        """
        SELECT mr.*, pt.version AS prompt_version, pt.run_type AS prompt_run_type
        FROM model_run mr
        LEFT JOIN prompt_template pt ON pt.prompt_template_id = mr.prompt_template_id
        WHERE mr.model_run_id = ?
        """,
        (model_run_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "model_run_id": row["model_run_id"],
        "dataset_id": row["dataset_id"],
        "run_type": row["run_type"],
        "model": row["model"],
        "prompt_template_id": row["prompt_template_id"],
        "prompt_version": row["prompt_version"],
        "input_summary": row["input_summary"],
        "created_at": row["created_at"],
        "latency_ms": row["latency_ms"],
        "error_type": row["error_type"],
        "error_message": row["error_message"],
        "stack_trace": row["stack_trace"],
        "raw_request_json": json.loads(row["raw_request_json"] or "{}"),
        "raw_response_json": json.loads(row["raw_response_json"] or "{}"),
    }


def export_audit_bundle(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    output_dir: Path,
    *,
    dataset_id: int | None = None,
) -> dict[str, int]:
    output_dir.mkdir(parents=True, exist_ok=True)
    log_json = output_dir / "process_log.json"
    log_text = output_dir / "process_log.txt"
    runs_json = output_dir / "model_runs.json"
    sizes = {
        "process_log_json": export_process_log_json(conn, log_json, dataset_id=dataset_id),
        "process_log_text": export_process_log_text(conn, log_text, dataset_id=dataset_id),
    }
    runs = list_model_runs(conn, dataset_id=dataset_id, limit=5000)
    runs_json.write_text(
        json.dumps([run.__dict__ for run in runs], indent=2),
        encoding="utf-8",
    )
    sizes["model_runs_json"] = runs_json.stat().st_size
    logger.info(
        component="export.audit_export",
        operation="audit_bundle_exported",
        message=f"Exported audit bundle to {output_dir}",
        details={"sizes": sizes, "dataset_id": dataset_id},
        dataset_id=dataset_id,
    )
    return sizes
