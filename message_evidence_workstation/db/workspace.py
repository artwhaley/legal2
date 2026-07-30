"""Public EVW lifecycle facade over :class:`WorkspaceStore`."""

from __future__ import annotations

from pathlib import Path

from message_evidence_workstation.config.paths import default_workspace_path
from message_evidence_workstation.db.workspace_store import WorkspaceStore
from message_evidence_workstation.domain.constants import WORKSPACE_FORMAT_ID, WORKSPACE_FORMAT_VERSION
from message_evidence_workstation.logging_ui.diagnostic_logger import DiagnosticLogger

EVW_EXTENSION = ".evw"


class WorkspaceError(RuntimeError):
    pass


class WorkspaceLifecycleError(WorkspaceError):
    pass


def ensure_evw_path(path: Path) -> Path:
    return path if path.suffix.lower() == EVW_EXTENSION else path.with_suffix(EVW_EXTENSION)


def create_workspace(path: Path, logger: DiagnosticLogger, *, display_name: str | None = None) -> WorkspaceStore:
    path = ensure_evw_path(path)
    if path.exists():
        raise WorkspaceError(f"Workspace already exists: {path}")
    return WorkspaceStore(path, logger).open(create=True, display_name=display_name or path.stem)


def open_workspace(path: Path, logger: DiagnosticLogger) -> WorkspaceStore:
    path = ensure_evw_path(path)
    return WorkspaceStore(path, logger).open(create=False)


def open_or_create_workspace(path: Path, logger: DiagnosticLogger) -> WorkspaceStore:
    return open_workspace(path, logger) if ensure_evw_path(path).exists() else create_workspace(path, logger)


def open_or_create_default_workspace(logger: DiagnosticLogger) -> tuple[WorkspaceStore, Path]:
    path = default_workspace_path()
    return open_or_create_workspace(path, logger), path


def close_workspace(store: WorkspaceStore, logger: DiagnosticLogger | None = None) -> None:
    store.close()


def import_into_workspace(store: WorkspaceStore, logger: DiagnosticLogger, dataset_dir: Path) -> int:
    from message_evidence_workstation.services.corpus_builder import build_working_corpus
    from message_evidence_workstation.services.import_dataset import import_normalized_dataset

    dataset_id = store.write(import_normalized_dataset, logger, dataset_dir)
    store.write(build_working_corpus, logger, dataset_id=dataset_id, name="Full Corpus", selection_mode="all")
    return dataset_id
