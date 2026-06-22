"""Smoke tests for project bootstrap."""

from message_evidence_workstation import __version__
from message_evidence_workstation.ui.main_window import MainWindow


def test_version_is_set() -> None:
    assert __version__ == "0.1.0"


def test_main_window_import() -> None:
    assert MainWindow is not None
