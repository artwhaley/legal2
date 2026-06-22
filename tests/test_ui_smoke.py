"""UI bootstrap smoke tests."""

import os
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from message_evidence_workstation.app_bootstrap import bootstrap_app
from message_evidence_workstation.db import evidence_blocks
from message_evidence_workstation.db import repositories
from message_evidence_workstation.ui.main_window import MainWindow
from message_evidence_workstation.ui.settings_tab import SettingsTab
from message_evidence_workstation.ui.sidebar import Sidebar
from message_evidence_workstation.ui.simple_search_tab import SimpleSearchTab
from message_evidence_workstation.ui.transcript_widget_tab import TranscriptWidgetTab


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_main_window_with_dataset(tmp_path, qapp, monkeypatch) -> None:
    monkeypatch.setenv("MEW_DB_PATH", str(tmp_path / "ui.db"))
    monkeypatch.setenv(
        "MEW_DATASET_PATH",
        str(Path(__file__).parent / "fixtures" / "sample_dataset"),
    )
    monkeypatch.setattr(SettingsTab, "start_embedding_model_preload", lambda self: None)
    context = bootstrap_app()
    window = MainWindow(context)
    assert window.sidebar.thread_list.count() == 2
    assert window.tabs.count() == 6
    assert window.tabs.tabText(4) == "Setup / Settings"
    assert window.tabs.tabText(5) == "Transcript Widget"


def test_sidebar_category_tree_shows_names_and_child_evidence_blocks(tmp_path, qapp, monkeypatch) -> None:
    monkeypatch.setenv("MEW_DB_PATH", str(tmp_path / "ui.db"))
    monkeypatch.setenv(
        "MEW_DATASET_PATH",
        str(Path(__file__).parent / "fixtures" / "sample_dataset"),
    )
    context = bootstrap_app()
    category = repositories.create_category(context.conn, context.logger, context.dataset_id, "school")
    messages = repositories.list_messages_for_thread(context.conn, context.dataset_id, "thread_001")
    block = evidence_blocks.create_evidence_block(
        context.conn,
        context.logger,
        dataset_id=context.dataset_id,
        category_id=category.category_id,
        source_thread_id="thread_001",
        title="School pickup",
        core_hit_message_id="msg_001",
        ordered_message_ids=[message.message_id for message in messages],
    )
    repositories.set_category_collapsed(context.conn, context.logger, category.category_id, True)

    sidebar = Sidebar(context.conn, context.logger)
    sidebar.set_dataset(context.dataset_id)
    selected_ids: list[int] = []
    sidebar.evidence_block_selected.connect(selected_ids.append)
    tree = sidebar.category_tree
    school_item = None
    for index in range(tree.topLevelItemCount()):
        item = tree.topLevelItem(index)
        if item.text(0) == "school":
            school_item = item
            break
    assert school_item is not None
    assert school_item.childCount() == 1
    assert school_item.child(0).text(0) == "School pickup"
    assert not school_item.isExpanded()

    tree.expandItem(school_item)
    qapp.processEvents()
    assert school_item.isExpanded()

    tree.setCurrentItem(school_item.child(0))
    qapp.processEvents()
    assert selected_ids == [block.evidence_block_id]


def test_simple_search_shows_transcript_for_selected_group(tmp_path, qapp, monkeypatch) -> None:
    monkeypatch.setenv("MEW_DB_PATH", str(tmp_path / "ui.db"))
    monkeypatch.setenv(
        "MEW_DATASET_PATH",
        str(Path(__file__).parent / "fixtures" / "sample_dataset"),
    )
    context = bootstrap_app()
    tab = SimpleSearchTab(context.conn, context.logger, db_path=context.db_path)
    tab.set_dataset(context.dataset_id)
    tab.search_box.setText("allergy")
    tab._run_search()
    qapp.processEvents()

    assert tab.results_splitter.count() == 2
    assert tab.results_list.count() >= 1
    assert "matching message(s)" in tab.results_list.item(0).text()
    assert tab.thread_view.header.text().startswith("Search context:")
    assert tab.thread_view.message_list.count() == 3
    assert "allergy" in tab.thread_view.message_list.item(0).text().lower()


def test_transcript_widget_tab_updates_summary_when_state_changes(tmp_path, qapp, monkeypatch) -> None:
    monkeypatch.setenv("MEW_DB_PATH", str(tmp_path / "ui.db"))
    monkeypatch.setenv(
        "MEW_DATASET_PATH",
        str(Path(__file__).parent / "fixtures" / "sample_dataset"),
    )
    context = bootstrap_app()
    tab = TranscriptWidgetTab(context.conn, context.logger)
    tab.set_dataset(context.dataset_id)

    assert tab.thread_combo.count() == 2
    assert "Context:" in tab.summary_label.text()

    tab._model.move_boundary("relevant_end", 2)
    tab._model.toggle_highlight_row(1)
    qapp.processEvents()

    assert "Relevant:" in tab.summary_label.text()
    assert "Highlighted: 1" in tab.summary_label.text()
