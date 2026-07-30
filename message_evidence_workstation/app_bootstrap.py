"""Lean Python client bootstrap: one EVW store and one remote gateway."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from message_evidence_workstation.client_api.gateway import RemoteGateway
from message_evidence_workstation.config.paths import default_workspace_path
from message_evidence_workstation.config.settings import load_settings
from message_evidence_workstation.db.workspace_store import WorkspaceStore
from message_evidence_workstation.logging_ui.log_bus import LogBus, get_log_bus
from message_evidence_workstation.logging_ui.diagnostic_logger import DiagnosticLogger


@dataclass(slots=True)
class AppContext:
    store: WorkspaceStore
    logger: DiagnosticLogger
    log_bus: LogBus
    dataset_id: int | None
    db_path: Path
    gateway: RemoteGateway


@dataclass(slots=True)
class StartupLoadOptions:
    dataset_path: Path
    skip_embedding: bool = False


def _latest_ready_dataset(store: WorkspaceStore) -> int | None:
    def read(conn):
        row = conn.execute("SELECT dataset_id FROM dataset WHERE import_validity='ready' ORDER BY dataset_id DESC LIMIT 1").fetchone()
        return int(row[0]) if row else None
    return store.read(read)


def bootstrap_app(*, db_path: Path | None = None, startup_load: StartupLoadOptions | None = None) -> AppContext:
    path = (db_path or default_workspace_path()).with_suffix(".evw")
    log_bus = get_log_bus()
    logger = DiagnosticLogger(log_bus=log_bus)
    store = WorkspaceStore(path, logger).open(create=True, display_name=path.stem)
    settings = load_settings()
    gateway = RemoteGateway(settings.server_url)
    if startup_load is not None:
        from message_evidence_workstation.services.import_dataset import import_normalized_dataset
        from message_evidence_workstation.services.corpus_builder import build_working_corpus

        dataset_id = store.write(import_normalized_dataset, logger, startup_load.dataset_path)
        store.write(build_working_corpus, logger, dataset_id=dataset_id, name="Full Corpus", selection_mode="all")
    else:
        dataset_id = _latest_ready_dataset(store)
    logger.info(component="app.bootstrap", operation="startup_complete", message="Python EVW client ready", details={"db_path": str(path), "dataset_id": dataset_id, "server_url": settings.server_url}, dataset_id=dataset_id)
    return AppContext(store=store, logger=logger, log_bus=log_bus, dataset_id=dataset_id, db_path=path, gateway=gateway)
