"""Application bootstrap: database, dataset, logging."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from message_evidence_workstation.config.paths import default_dataset_path, default_workspace_path
from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.repositories import get_latest_dataset
from message_evidence_workstation.db.workspace import import_into_workspace, open_or_create_workspace
from message_evidence_workstation.logging_ui.log_bus import LogBus, get_log_bus
from message_evidence_workstation.logging_ui.process_log import ProcessLogger


@dataclass(slots=True)
class AppContext:
    conn: sqlite3.Connection
    logger: ProcessLogger
    log_bus: LogBus
    dataset_id: int | None
    db_path: Path


def bootstrap_app(
    *,
    db_path: Path | None = None,
    dataset_path: Path | None = None,
    reload_dataset: bool = False,
) -> AppContext:
    path = db_path or default_workspace_path()
    log_bus = get_log_bus()
    bootstrap_logger = ProcessLogger(connect(path), log_bus=log_bus)
    conn = open_or_create_workspace(path, bootstrap_logger)
    logger = ProcessLogger(conn, log_bus=log_bus)

    dataset = get_latest_dataset(conn)
    resolved_dataset_path = dataset_path or default_dataset_path()
    dataset_id = dataset.dataset_id if dataset else None

    if resolved_dataset_path is not None:
        if dataset is None or reload_dataset:
            dataset_id = import_into_workspace(
                conn,
                logger,
                resolved_dataset_path,
                reload=reload_dataset,
            )
            logger.dataset_id = dataset_id
    elif dataset is None:
        logger.warning(
            component="app.bootstrap",
            operation="dataset_missing",
            message="No dataset loaded and no default dataset path found",
        )
    elif dataset_id is not None:
        from message_evidence_workstation.db.evidence_blocks import ensure_uncategorized_category

        ensure_uncategorized_category(conn, logger, dataset_id)

    logger.info(
        component="app.bootstrap",
        operation="startup_complete",
        message="Application bootstrap completed",
        details={"db_path": str(path), "dataset_id": dataset_id},
        dataset_id=dataset_id,
    )
    return AppContext(
        conn=conn,
        logger=logger,
        log_bus=log_bus,
        dataset_id=dataset_id,
        db_path=path,
    )
