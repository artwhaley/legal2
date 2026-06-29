"""Shared pytest fixtures."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(autouse=True)
def _reset_embedding_worker_state():
    yield
    from message_evidence_workstation.ui.embedding_worker import invalidate_embedding_model_cache

    invalidate_embedding_model_cache()


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app
