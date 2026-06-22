"""Workspace and data path helpers."""

from __future__ import annotations

import os
from pathlib import Path


def workspace_dir() -> Path:
    override = os.environ.get("MEW_WORKSPACE_DIR")
    if override:
        return Path(override)
    return Path.home() / ".message_evidence_workstation"


def default_workspace_path() -> Path:
    override = os.environ.get("MEW_WORKSPACE_PATH")
    if override:
        return Path(override)
    db_override = os.environ.get("MEW_DB_PATH")
    if db_override:
        path = Path(db_override)
        if path.suffix.lower() == ".evw":
            return path
        return path.with_suffix(".evw")
    return workspace_dir() / "workspace.evw"


def default_db_path() -> Path:
    return default_workspace_path()


def default_dataset_path() -> Path | None:
    override = os.environ.get("MEW_DATASET_PATH")
    if override:
        return Path(override)
    bundled = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "sample_dataset"
    if bundled.is_dir():
        return bundled
    return None
