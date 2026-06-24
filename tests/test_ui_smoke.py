"""UI bootstrap smoke tests."""

import json
import os
from pathlib import Path

import pytest
from PySide6.QtCore import QMimeData, QPoint, Qt
from PySide6.QtWidgets import QApplication

from message_evidence_workstation.app_bootstrap import bootstrap_app
from message_evidence_workstation.db import evidence_blocks
from message_evidence_workstation.db import repositories
from message_evidence_workstation.domain.constants import UNCATEGORIZED_CATEGORY_NAME
from message_evidence_workstation.ui.main_window import MainWindow
from message_evidence_workstation.ui.settings_tab import SettingsTab
from message_evidence_workstation.ui.sidebar import Sidebar
from message_evidence_workstation.ui.simple_search_tab import MIME_SEARCH_RESULT, SimpleSearchTab
from message_evidence_workstation.ui.transcript_widget_tab import TranscriptWidgetTab
from message_evidence_workstation.search.result_models import GroupedSearchResult, SearchHit


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _search_group(title: str = "Allergy form") -> GroupedSearchResult:
    return GroupedSearchResult(
        group_id="group-1",
        source_thread_id="thread_001",
        primary_hit_message_id="msg_001",
        hits=[
            SearchHit(
                message_id="msg_001",
                source_thread_id="thread_001",
                match_type="exact",
                retrieval_method="fts_exact",
                query_text="allergy",
            )
        ],
        title=title,
        snippet=title,
    )


def _find_top_level_item(sidebar: Sidebar, label: str):
    tree = sidebar.category_tree
    for index in range(tree.topLevelItemCount()):
        item = tree.topLevelItem(index)
        if item.text(0) == label:
            return item
    return None


def test_main_window_with_dataset(tmp_path, qapp, monkeypatch) -> None:
    monkeypatch.setenv("MEW_DB_PATH", str(tmp_path / "ui.db"))
    monkeypatch.setenv(
        "MEW_DATASET_PATH",
        str(Path(__file__).parent / "fixtures" / "sample_dataset"),
    )
    monkeypatch.setattr(SettingsTab, "start_embedding_model_preload", lambda self: None)
    context = bootstrap_app()
    window = MainWindow(context)
    assert window.sidebar.thread_combo.count() == 1
    assert window.tabs.count() == 6
    assert window.tabs.tabText(4) == "Setup / Settings"
    assert window.tabs.tabText(5) == "Transcript Widget"
    assert window.settings_tab.chunk_similarity_threshold.value() >= 0.0
    assert window.settings_tab.chunk_session_gap_hours.value() > 0.0
    assert window.settings_tab.chunk_max_chars.value() >= 100
    assert "message embeddings" in window.settings_tab.chunk_preview_label.text().lower()


def test_settings_context_budget_readout_present(tmp_path, qapp, monkeypatch) -> None:
    monkeypatch.setenv("MEW_DB_PATH", str(tmp_path / "ui.db"))
    monkeypatch.setenv(
        "MEW_DATASET_PATH",
        str(Path(__file__).parent / "fixtures" / "sample_dataset"),
    )
    monkeypatch.setattr(SettingsTab, "start_embedding_model_preload", lambda self: None)
    context = bootstrap_app()
    window = MainWindow(context)
    readout = window.settings_tab.context_budget_readout.text()
    assert "Selected answer model" in readout
    assert "Context window tokens" in readout
    assert "Usable input budget" in readout
    assert "Auto mode decision" in readout


def test_settings_loads_answer_token_defaults(tmp_path) -> None:
    from message_evidence_workstation.config.settings import AnswerSettings, load_settings

    settings = load_settings()
    assert isinstance(settings.answer, AnswerSettings)
    assert settings.answer.context_safety_ratio == 0.70
    assert settings.answer.reserved_output_tokens == 4096
    assert settings.answer.window_target_tokens == 12000


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


def test_sidebar_search_drop_uses_target_category(tmp_path, qapp, monkeypatch) -> None:
    monkeypatch.setenv("MEW_DB_PATH", str(tmp_path / "ui.db"))
    monkeypatch.setenv(
        "MEW_DATASET_PATH",
        str(Path(__file__).parent / "fixtures" / "sample_dataset"),
    )
    context = bootstrap_app()
    category = repositories.create_category(context.conn, context.logger, context.dataset_id, "school")
    repositories.set_category_collapsed(context.conn, context.logger, category.category_id, True)
    sidebar = Sidebar(context.conn, context.logger)
    sidebar.set_dataset(context.dataset_id)

    group = _search_group()
    sidebar.handle_search_drop(group, category_id=category.category_id)
    qapp.processEvents()

    school_item = _find_top_level_item(sidebar, "school")
    assert school_item is not None
    assert school_item.isExpanded()
    assert school_item.childCount() == 1
    assert school_item.child(0).text(0) == "Allergy form"
    blocks = evidence_blocks.list_evidence_blocks(
        context.conn,
        context.dataset_id,
        category_id=category.category_id,
    )
    assert [block.title for block in blocks] == ["Allergy form"]


def test_sidebar_search_drop_without_category_reveals_uncategorized(tmp_path, qapp, monkeypatch) -> None:
    monkeypatch.setenv("MEW_DB_PATH", str(tmp_path / "ui.db"))
    monkeypatch.setenv(
        "MEW_DATASET_PATH",
        str(Path(__file__).parent / "fixtures" / "sample_dataset"),
    )
    context = bootstrap_app()
    category = evidence_blocks.ensure_uncategorized_category(context.conn, context.logger, context.dataset_id)
    repositories.set_category_collapsed(context.conn, context.logger, category.category_id, True)
    sidebar = Sidebar(context.conn, context.logger)
    sidebar.set_dataset(context.dataset_id)

    sidebar.handle_search_drop(_search_group("Uncategorized allergy drop"))
    qapp.processEvents()

    uncategorized_item = _find_top_level_item(sidebar, UNCATEGORIZED_CATEGORY_NAME)
    assert uncategorized_item is not None
    assert uncategorized_item.isExpanded()
    assert uncategorized_item.childCount() == 1
    assert uncategorized_item.child(0).text(0) == "Uncategorized allergy drop"


def test_sidebar_blank_area_drop_defaults_to_uncategorized(tmp_path, qapp, monkeypatch) -> None:
    monkeypatch.setenv("MEW_DB_PATH", str(tmp_path / "ui.db"))
    monkeypatch.setenv(
        "MEW_DATASET_PATH",
        str(Path(__file__).parent / "fixtures" / "sample_dataset"),
    )
    context = bootstrap_app()
    sidebar = Sidebar(context.conn, context.logger)
    sidebar.set_dataset(context.dataset_id)
    mime = QMimeData()
    mime.setData(
        MIME_SEARCH_RESULT,
        json.dumps(_search_group("Blank area drop").to_drag_payload()).encode("utf-8"),
    )

    class _FakePosition:
        def toPoint(self) -> QPoint:
            return QPoint(-1, -1)

    class _FakeDropEvent:
        accepted = False
        ignored = False

        def mimeData(self) -> QMimeData:
            return mime

        def position(self) -> _FakePosition:
            return _FakePosition()

        def acceptProposedAction(self) -> None:
            self.accepted = True

        def ignore(self) -> None:
            self.ignored = True

    event = _FakeDropEvent()
    sidebar.category_tree.dropEvent(event)
    qapp.processEvents()

    uncategorized_item = _find_top_level_item(sidebar, UNCATEGORIZED_CATEGORY_NAME)
    assert event.accepted
    assert not event.ignored
    assert uncategorized_item is not None
    assert uncategorized_item.isExpanded()
    assert uncategorized_item.childCount() == 1
    assert uncategorized_item.child(0).text(0) == "Blank area drop"


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
    assert tab.transcript_widget.transcript_surface is not None
    assert tab.transcript_widget.model.message_count() == 100
    assert tab.transcript_widget._source_thread_id == "thread_001"


def test_simple_search_double_click_creates_uncategorized_block(tmp_path, qapp, monkeypatch) -> None:
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

    before = evidence_blocks.list_evidence_blocks(context.conn, context.dataset_id)
    tab.results_list.itemDoubleClicked.emit(tab.results_list.item(0))
    qapp.processEvents()

    after = evidence_blocks.list_evidence_blocks(context.conn, context.dataset_id)
    assert len(after) == len(before) + 1
    created = after[-1]
    assert created.core_hit_message_id == "msg_001"
    uncategorized = evidence_blocks.ensure_uncategorized_category(
        context.conn, context.logger, context.dataset_id
    )
    assert created.category_id == uncategorized.category_id


def test_simple_search_add_evidence_block_uses_viewport_center(tmp_path, qapp, monkeypatch) -> None:
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

    tab.transcript_widget.transcript_surface.viewport_center_message_index = lambda: 5  # type: ignore[method-assign]
    before = evidence_blocks.list_evidence_blocks(
        context.conn,
        context.dataset_id,
        source_thread_id="thread_001",
    )
    tab.add_evidence_block_button.click()
    qapp.processEvents()

    after = evidence_blocks.list_evidence_blocks(
        context.conn,
        context.dataset_id,
        source_thread_id="thread_001",
    )
    assert len(after) == len(before) + 1
    assert after[-1].core_hit_message_id == "msg_006"


def test_search_drop_reveals_block_in_simple_search_transcript(tmp_path, qapp, monkeypatch) -> None:
    monkeypatch.setenv("MEW_DB_PATH", str(tmp_path / "ui.db"))
    monkeypatch.setenv(
        "MEW_DATASET_PATH",
        str(Path(__file__).parent / "fixtures" / "sample_dataset"),
    )
    monkeypatch.setattr(SettingsTab, "start_embedding_model_preload", lambda self: None)
    context = bootstrap_app()
    window = MainWindow(context)
    category = repositories.create_category(context.conn, context.logger, context.dataset_id, "school")

    block = window.sidebar.handle_search_drop(_search_group("Drop into school"), category_id=category.category_id)
    qapp.processEvents()

    assert block is not None
    assert window.tabs.currentWidget() is window.simple_search_tab
    assert window.simple_search_tab.transcript_widget._source_thread_id == "thread_001"
    overlay_ids = [
        overlay.evidence_block_id
        for overlay in window.simple_search_tab.transcript_widget.model.block_overlays()
    ]
    assert block.evidence_block_id in overlay_ids


def test_search_drop_blank_area_reveals_in_simple_search(tmp_path, qapp, monkeypatch) -> None:
    monkeypatch.setenv("MEW_DB_PATH", str(tmp_path / "ui.db"))
    monkeypatch.setenv(
        "MEW_DATASET_PATH",
        str(Path(__file__).parent / "fixtures" / "sample_dataset"),
    )
    monkeypatch.setattr(SettingsTab, "start_embedding_model_preload", lambda self: None)
    context = bootstrap_app()
    window = MainWindow(context)
    mime = QMimeData()
    mime.setData(
        MIME_SEARCH_RESULT,
        json.dumps(_search_group("Blank drop reveal").to_drag_payload()).encode("utf-8"),
    )

    class _FakePosition:
        def toPoint(self) -> QPoint:
            return QPoint(-1, -1)

    class _FakeDropEvent:
        accepted = False
        ignored = False

        def mimeData(self) -> QMimeData:
            return mime

        def position(self) -> _FakePosition:
            return _FakePosition()

        def acceptProposedAction(self) -> None:
            self.accepted = True

        def ignore(self) -> None:
            self.ignored = True

    event = _FakeDropEvent()
    window.sidebar.category_tree.dropEvent(event)
    qapp.processEvents()

    assert event.accepted
    assert window.tabs.currentWidget() is window.simple_search_tab
    overlays = window.simple_search_tab.transcript_widget.model.block_overlays()
    assert any(overlay.core_hit_message_id == "msg_001" for overlay in overlays)


def test_simple_search_block_creation_stays_on_simple_search_tab(tmp_path, qapp, monkeypatch) -> None:
    monkeypatch.setenv("MEW_DB_PATH", str(tmp_path / "ui.db"))
    monkeypatch.setenv(
        "MEW_DATASET_PATH",
        str(Path(__file__).parent / "fixtures" / "sample_dataset"),
    )
    monkeypatch.setattr(SettingsTab, "start_embedding_model_preload", lambda self: None)
    context = bootstrap_app()
    window = MainWindow(context)
    window.tabs.setCurrentWidget(window.simple_search_tab)
    tab = window.simple_search_tab
    tab.search_box.setText("allergy")
    tab._run_search()
    qapp.processEvents()

    tab.transcript_widget.transcript_surface.viewport_center_message_index = lambda: 5  # type: ignore[method-assign]
    tab.add_evidence_block_button.click()
    qapp.processEvents()

    assert window.tabs.currentWidget() is window.simple_search_tab


def test_transcript_widget_tab_loads_thread_without_default_block(tmp_path, qapp, monkeypatch) -> None:
    monkeypatch.setenv("MEW_DB_PATH", str(tmp_path / "ui.db"))
    monkeypatch.setenv(
        "MEW_DATASET_PATH",
        str(Path(__file__).parent / "fixtures" / "sample_dataset"),
    )
    context = bootstrap_app()
    tab = TranscriptWidgetTab(context.conn, context.logger)
    tab.set_dataset(context.dataset_id)

    assert tab.transcript_surface is not None
    assert tab.new_block_button.isEnabled()
    assert tab.thread_combo.count() == 1
    assert tab._model.block_overlays() == []

    tab._model.move_boundary("relevant_end", 2)
    tab._model.toggle_highlight_row(1)
    qapp.processEvents()

    assert tab._model.active_slots()[2] == 2
    assert "msg_001" in tab._model.highlighted_message_ids()


def test_transcript_widget_new_block_uses_viewport_center(tmp_path, qapp, monkeypatch) -> None:
    monkeypatch.setenv("MEW_DB_PATH", str(tmp_path / "ui.db"))
    monkeypatch.setenv(
        "MEW_DATASET_PATH",
        str(Path(__file__).parent / "fixtures" / "sample_dataset"),
    )
    context = bootstrap_app()
    tab = TranscriptWidgetTab(context.conn, context.logger)
    tab.set_dataset(context.dataset_id)

    before = evidence_blocks.list_evidence_blocks(
        context.conn,
        context.dataset_id,
        source_thread_id="thread_001",
    )
    tab.transcript_surface.viewport_center_message_index = lambda: 5  # type: ignore[method-assign]
    tab._create_evidence_block_from_view()
    qapp.processEvents()

    after = evidence_blocks.list_evidence_blocks(
        context.conn,
        context.dataset_id,
        source_thread_id="thread_001",
    )
    assert len(after) == len(before) + 1
    created = after[-1]
    assert created.core_hit_message_id == "msg_006"
    assert created.context_start_slot == 2
    assert created.relevant_start_slot == 5
    assert created.relevant_end_slot == 6
    assert created.context_end_slot == 9


def test_new_evidence_block_preserves_existing_block_slots(tmp_path, qapp, monkeypatch) -> None:
    monkeypatch.setenv("MEW_DB_PATH", str(tmp_path / "ui.db"))
    monkeypatch.setenv(
        "MEW_DATASET_PATH",
        str(Path(__file__).parent / "fixtures" / "sample_dataset"),
    )
    context = bootstrap_app()
    tab = TranscriptWidgetTab(context.conn, context.logger)
    tab.set_dataset(context.dataset_id)

    tab._create_evidence_block_from_view()
    qapp.processEvents()
    first_block = evidence_blocks.list_evidence_blocks(
        context.conn,
        context.dataset_id,
        source_thread_id="thread_001",
    )[-1]
    tab._model.move_boundary_for_block(first_block.evidence_block_id, "context_end", 8)
    tab._model.move_boundary_for_block(first_block.evidence_block_id, "relevant_end", 7)
    tab._model.notify_overlay_edited(first_block.evidence_block_id)
    qapp.processEvents()

    tab.transcript_surface.viewport_center_message_index = lambda: 2  # type: ignore[method-assign]
    tab._create_evidence_block_from_view()
    qapp.processEvents()

    preserved = evidence_blocks.get_evidence_block(context.conn, first_block.evidence_block_id)
    assert preserved is not None
    assert preserved.context_end_slot == 8
    assert preserved.relevant_end_slot == 7
    assert len(
        evidence_blocks.list_evidence_blocks(
            context.conn,
            context.dataset_id,
            source_thread_id="thread_001",
        )
    ) == 2


def test_transcript_new_block_updates_sidebar(tmp_path, qapp, monkeypatch) -> None:
    monkeypatch.setenv("MEW_DB_PATH", str(tmp_path / "ui.db"))
    monkeypatch.setenv(
        "MEW_DATASET_PATH",
        str(Path(__file__).parent / "fixtures" / "sample_dataset"),
    )
    monkeypatch.setattr(SettingsTab, "start_embedding_model_preload", lambda self: None)
    context = bootstrap_app()
    window = MainWindow(context)

    def _count_evidence_block_items() -> int:
        total = 0
        tree = window.sidebar.category_tree
        for index in range(tree.topLevelItemCount()):
            total += tree.topLevelItem(index).childCount()
        return total

    before = _count_evidence_block_items()
    window.transcript_widget_tab.transcript_surface.viewport_center_message_index = lambda: 5  # type: ignore[method-assign]
    window.transcript_widget_tab._create_evidence_block_from_view()
    qapp.processEvents()

    assert _count_evidence_block_items() == before + 1
    uncategorized = _find_top_level_item(window.sidebar, UNCATEGORIZED_CATEGORY_NAME)
    assert uncategorized is not None
    assert uncategorized.isExpanded()
