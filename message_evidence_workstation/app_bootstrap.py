"""Application bootstrap: database, dataset, logging."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from message_evidence_workstation.config.paths import default_workspace_path
from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.repositories import get_latest_dataset
from message_evidence_workstation.db.workspace import open_or_create_workspace
from message_evidence_workstation.domain.constants import IMPORT_VALIDITY_READY
from message_evidence_workstation.importers.normalized_loader import get_dataset_import_validity
from message_evidence_workstation.domain.embedding_state import EmbeddingState
from message_evidence_workstation.logging_ui.log_bus import LogBus, get_log_bus
from message_evidence_workstation.logging_ui.process_log import ProcessLogger


@dataclass(slots=True)
class AppContext:
    conn: sqlite3.Connection
    logger: ProcessLogger
    log_bus: LogBus
    dataset_id: int | None
    db_path: Path
    embedding_available: bool = False
    embedding_state: EmbeddingState | None = None


@dataclass(slots=True)
class StartupLoadOptions:
    dataset_path: Path
    reload: bool = False
    skip_embedding: bool = False


def _ready_dataset_id(conn: sqlite3.Connection) -> int | None:
    dataset = get_latest_dataset(conn)
    if dataset is None:
        return None
    if get_dataset_import_validity(conn, dataset.dataset_id) != IMPORT_VALIDITY_READY:
        return None
    return dataset.dataset_id


def bootstrap_app(
    *,
    db_path: Path | None = None,
    startup_load: StartupLoadOptions | None = None,
) -> AppContext:
    path = db_path or default_workspace_path()
    log_bus = get_log_bus()
    bootstrap_logger = ProcessLogger(connect(path), log_bus=log_bus)
    conn = open_or_create_workspace(path, bootstrap_logger)
    logger = ProcessLogger(conn, log_bus=log_bus)

    dataset_id = None
    embedding_available = False
    stored_dataset_id = _ready_dataset_id(conn)

    if startup_load is not None:
        logger.info(
            component="app.bootstrap",
            operation="startup_load_deferred",
            message="Dataset load deferred to UI background pipeline",
            details={
                "dataset_path": str(startup_load.dataset_path),
                "reload": startup_load.reload,
                "skip_embedding": startup_load.skip_embedding,
            },
        )

    if dataset_id is None:
        logger.warning(
            component="app.bootstrap",
            operation="dataset_missing",
            message="No dataset loaded in UI; use Home to load a dataset",
            details={"stored_dataset_id": stored_dataset_id},
        )

    logger.info(
        component="app.bootstrap",
        operation="startup_complete",
        message="Application bootstrap completed",
        details={
            "db_path": str(path),
            "dataset_id": dataset_id,
            "stored_dataset_id": stored_dataset_id,
            "embedding_available": embedding_available,
        },
        dataset_id=dataset_id,
    )
    return AppContext(
        conn=conn,
        logger=logger,
        log_bus=log_bus,
        dataset_id=dataset_id,
        db_path=path,
        embedding_available=embedding_available,
        embedding_state=EmbeddingState(),
    )
