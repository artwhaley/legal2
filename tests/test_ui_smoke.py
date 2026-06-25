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
from message_evidence_workstation.llm.types import UserFacingModelRole
from message_evidence_workstation.search.conversational_answer import (
    AnswerRangeDraft,
    ConversationalAnswerResult,
    CoverageSummary,
)
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


def test_settings_model_routing_controls_present(tmp_path, qapp, monkeypatch) -> None:
    monkeypatch.setenv("MEW_DB_PATH", str(tmp_path / "ui.db"))
    monkeypatch.setenv(
        "MEW_DATASET_PATH",
        str(Path(__file__).parent / "fixtures" / "sample_dataset"),
    )
    monkeypatch.setattr(SettingsTab, "start_embedding_model_preload", lambda self: None)
    context = bootstrap_app()
    window = MainWindow(context)
    tab = window.settings_tab
    assert tab.google_api_key is not None
    assert UserFacingModelRole.EXPANSION in tab.role_provider
    assert UserFacingModelRole.RESEARCH in tab.role_provider
    assert UserFacingModelRole.WRITING in tab.role_provider
    assert tab.save_routing_button is not None
    assert tab.save_routing_button.text() == "Save API settings"


def test_settings_model_routing_persists(tmp_path, monkeypatch) -> None:
    from message_evidence_workstation.config.settings import PROVIDER_GOOGLE, load_settings, save_settings
    from message_evidence_workstation.llm.types import UserFacingModelRole

    monkeypatch.setenv("MEW_WORKSPACE_DIR", str(tmp_path))
    settings = load_settings()
    routing = settings.model_routing
    assert routing is not None
    routing.writing.provider = PROVIDER_GOOGLE
    routing.writing.model = "gemini-2.0-flash"
    routing.writing.api_key = "google-test-key"
    save_settings(settings)
    reloaded = load_settings()
    assert reloaded.model_routing is not None
    assert reloaded.model_routing.writing.provider == PROVIDER_GOOGLE
    assert reloaded.model_routing.writing.model == "gemini-2.0-flash"


def test_settings_model_refresh_preserves_saved_writing_model(tmp_path, qapp, monkeypatch) -> None:
    from message_evidence_workstation.config.settings import PROVIDER_GOOGLE, load_settings, save_settings
    from message_evidence_workstation.llm.types import ModelInfo

    monkeypatch.setenv("MEW_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("MEW_DB_PATH", str(tmp_path / "ui.db"))
    monkeypatch.setenv(
        "MEW_DATASET_PATH",
        str(Path(__file__).parent / "fixtures" / "sample_dataset"),
    )
    monkeypatch.setattr(SettingsTab, "start_embedding_model_preload", lambda self: None)
    settings = load_settings()
    routing = settings.model_routing
    assert routing is not None
    routing.writing.provider = PROVIDER_GOOGLE
    routing.writing.model = "gemma-4-31b-it"
    routing.writing.api_key = "google-test-key"
    save_settings(settings)

    context = bootstrap_app()
    window = MainWindow(context)
    tab = window.settings_tab
    tab._models_by_provider[PROVIDER_GOOGLE] = [
        ModelInfo(id="gemini-2.0-flash"),
        ModelInfo(id="gemini-3.1-flash-lite"),
    ]

    tab._apply_cached_models_to_ui()
    assert tab.role_model[UserFacingModelRole.WRITING].currentText() == "gemma-4-31b-it"

    tab._save_api_settings()
    reloaded = load_settings()
    assert reloaded.model_routing is not None
    assert reloaded.model_routing.writing.model == "gemma-4-31b-it"


def test_settings_tab_initializes_without_budget_readout_race(tmp_path, qapp, monkeypatch) -> None:
    from message_evidence_workstation.config.settings import PROVIDER_GOOGLE, load_settings, save_settings

    monkeypatch.setenv("MEW_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("MEW_DB_PATH", str(tmp_path / "ui.db"))
    monkeypatch.setenv(
        "MEW_DATASET_PATH",
        str(Path(__file__).parent / "fixtures" / "sample_dataset"),
    )
    monkeypatch.setattr(SettingsTab, "start_embedding_model_preload", lambda self: None)
    settings = load_settings()
    assert settings.model_routing is not None
    settings.model_routing.expansion.provider = PROVIDER_GOOGLE
    settings.model_routing.expansion.model = "gemini-2.0-flash"
    settings.model_routing.research.provider = PROVIDER_GOOGLE
    settings.model_routing.research.model = "gemini-2.0-flash"
    settings.model_routing.writing.provider = PROVIDER_GOOGLE
    settings.model_routing.writing.model = "gemma-4-31b-it"
    save_settings(settings)

    context = bootstrap_app()
    window = MainWindow(context)

    assert window.settings_tab.context_budget_readout.text()


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
    assert window.tabs.count() == 5
    assert window.tabs.tabText(3) == "Setup / Settings"
    assert window.tabs.tabText(4) == "Transcript Widget"
    assert 2 <= window.settings_tab.chunk_desired_average.value() <= 20
    assert window.settings_tab.chunk_session_gap_hours.value() > 0.0
    assert window.settings_tab.chunk_max_chars.value() >= 100
    assert "message embeddings" in window.settings_tab.chunk_preview_label.text().lower()
    assert window.simple_search_tab.embedding_selectivity.value() == 1
    assert window.simple_search_tab.embedding_selectivity_label.text() == "Balanced"


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


def test_settings_loads_api_token_defaults(tmp_path, monkeypatch) -> None:
    from message_evidence_workstation.config.settings import NimSettings, load_settings

    monkeypatch.setenv("MEW_WORKSPACE_DIR", str(tmp_path))
    settings = load_settings()
    assert isinstance(settings.nim, NimSettings)
    assert settings.nim.context_safety_ratio == 0.70
    assert settings.nim.max_output_tokens == 4096
    assert settings.nim.prompt_overhead_tokens == 1500


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
    assert tree.currentItem() is school_item.child(0)


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


def test_conversational_answer_stream_persists_and_drives_transcript_and_block_creation(
    tmp_path, qapp, monkeypatch
) -> None:
    monkeypatch.setenv("MEW_DB_PATH", str(tmp_path / "ui.db"))
    monkeypatch.setenv(
        "MEW_DATASET_PATH",
        str(Path(__file__).parent / "fixtures" / "sample_dataset"),
    )
    monkeypatch.setattr(SettingsTab, "start_embedding_model_preload", lambda self: None)
    context = bootstrap_app()
    window = MainWindow(context)
    tab = window.conversational_tab
    answer = ConversationalAnswerResult(
        answer="Medical care appears in the allergy-form exchange.",
        cited_message_ids=[],
        answer_ranges=[
            AnswerRangeDraft(
                title="Allergy form and nurse call",
                summary="The exchange covers an allergy form and Nurse Kim.",
                hit_message_id="msg_002",
                start_message_id="msg_001",
                end_message_id="msg_003",
                source_thread_id="thread_001",
                date_description="On June 6, 2023",
                display_text="Martha texted about the school allergy form.",
            )
        ],
        candidate_evidence_blocks=[],
        uncertainties=[],
        coverage_summary=CoverageSummary(
            mode="whole_transcript",
            messages_considered=100,
            source_thread_ids=["thread_001"],
        ),
        mode="whole_transcript",
    )

    tab._last_query_text = "Tell me all the times we talked about medical care."
    tab._show_answer_result(answer)
    tab._last_query_text = "Show me the allergy-related exchange again."
    tab._show_answer_result(answer)
    qapp.processEvents()

    assert len(tab._conversation_results) == 2
    first_entry = tab._conversation_results[0]
    second_entry = tab._conversation_results[1]
    assert first_entry.button.text() == "The exchange covers an allergy form and Nurse Kim."
    assert first_entry.button.toolTip() == "Martha texted about the school allergy form."
    assert "#0b57d0" in first_entry.button.styleSheet()
    assert second_entry.turn_index == 1

    first_entry.button.navigate_requested.emit()
    qapp.processEvents()
    assert tab.transcript_widget._source_thread_id == "thread_001"

    before = evidence_blocks.list_evidence_blocks(context.conn, context.dataset_id)
    first_entry.button.create_requested.emit()
    qapp.processEvents()

    after = evidence_blocks.list_evidence_blocks(context.conn, context.dataset_id)
    assert len(after) == len(before) + 1
    created = after[-1]
    assert created.core_hit_message_id == "msg_002"
    assert created.relevant_start_slot == 0
    assert created.relevant_end_slot == 3
    assert created.context_start_slot == 0
    assert created.context_end_slot == 6


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


def test_source_thread_selection_opens_transcript_widget(tmp_path, qapp, monkeypatch) -> None:
    monkeypatch.setenv("MEW_DB_PATH", str(tmp_path / "ui.db"))
    monkeypatch.setenv(
        "MEW_DATASET_PATH",
        str(Path(__file__).parent / "fixtures" / "sample_dataset"),
    )
    monkeypatch.setattr(SettingsTab, "start_embedding_model_preload", lambda self: None)
    context = bootstrap_app()
    window = MainWindow(context)
    window.tabs.setCurrentWidget(window.simple_search_tab)
    window._on_source_thread_selected("thread_001", "Sample thread")
    qapp.processEvents()
    assert window.tabs.currentWidget() is window.transcript_widget_tab
    assert window.transcript_widget_tab.transcript_widget._source_thread_id == "thread_001"


def test_sidebar_evidence_block_click_does_not_navigate_tabs(tmp_path, qapp, monkeypatch) -> None:
    monkeypatch.setenv("MEW_DB_PATH", str(tmp_path / "ui.db"))
    monkeypatch.setenv(
        "MEW_DATASET_PATH",
        str(Path(__file__).parent / "fixtures" / "sample_dataset"),
    )
    monkeypatch.setattr(SettingsTab, "start_embedding_model_preload", lambda self: None)
    context = bootstrap_app()
    window = MainWindow(context)
    category = evidence_blocks.ensure_uncategorized_category(
        context.conn,
        context.logger,
        context.dataset_id,
    )
    messages = repositories.list_messages_for_thread(context.conn, context.dataset_id, "thread_001")
    block = evidence_blocks.create_evidence_block(
        context.conn,
        context.logger,
        dataset_id=context.dataset_id,
        category_id=category.category_id,
        source_thread_id="thread_001",
        title="Drag me",
        core_hit_message_id="msg_001",
        ordered_message_ids=[message.message_id for message in messages],
    )
    window.sidebar.reveal_evidence_block(block.evidence_block_id)
    window.tabs.setCurrentWidget(window.output_formatting_tab)
    qapp.processEvents()

    current = window.sidebar.category_tree.currentItem()
    assert current is not None
    assert current.text(0) == "Drag me"
    parent = current.parent()
    assert parent is not None
    window.sidebar.category_tree.setCurrentItem(parent)
    window.sidebar.category_tree.setCurrentItem(current)
    qapp.processEvents()
    assert window.tabs.currentWidget() is window.output_formatting_tab


def test_output_formatting_tab_initializes_tree(tmp_path, qapp, monkeypatch) -> None:
    monkeypatch.setenv("MEW_DB_PATH", str(tmp_path / "ui.db"))
    monkeypatch.setenv(
        "MEW_DATASET_PATH",
        str(Path(__file__).parent / "fixtures" / "sample_dataset"),
    )
    monkeypatch.setattr(SettingsTab, "start_embedding_model_preload", lambda self: None)
    context = bootstrap_app()
    window = MainWindow(context)
    tab = window.output_formatting_tab
    assert tab.artifact_tree.topLevelItemCount() >= 1
    assert tab.artifact_tree.topLevelItem(0).data(0, int(Qt.ItemDataRole.UserRole) + 1) == "group"


def test_output_formatting_drop_on_group_creates_artifact(tmp_path, qapp, monkeypatch) -> None:
    monkeypatch.setenv("MEW_DB_PATH", str(tmp_path / "ui.db"))
    monkeypatch.setenv(
        "MEW_DATASET_PATH",
        str(Path(__file__).parent / "fixtures" / "sample_dataset"),
    )
    monkeypatch.setattr(SettingsTab, "start_embedding_model_preload", lambda self: None)
    context = bootstrap_app()
    window = MainWindow(context)
    category = repositories.create_category(context.conn, context.logger, context.dataset_id, "school")
    messages = repositories.list_messages_for_thread(context.conn, context.dataset_id, "thread_001")
    block = evidence_blocks.create_evidence_block(
        context.conn,
        context.logger,
        dataset_id=context.dataset_id,
        category_id=category.category_id,
        source_thread_id="thread_001",
        title="Pickup note",
        core_hit_message_id="msg_001",
        ordered_message_ids=[message.message_id for message in messages],
    )
    tab = window.output_formatting_tab
    group_item = tab.artifact_tree.topLevelItem(0)
    group_id = int(group_item.data(0, int(Qt.ItemDataRole.UserRole)))
    tab.handle_evidence_block_drop(block.evidence_block_id, group_item)
    qapp.processEvents()
    artifacts = __import__(
        "message_evidence_workstation.db.printable_artifacts",
        fromlist=["list_printable_artifacts"],
    ).list_printable_artifacts(context.conn, group_id)
    assert len(artifacts) == 1
    tab._select_artifact_in_tree(artifacts[0].printable_artifact_id)
    qapp.processEvents()
    assert tab.title_field.text() == "Pickup note"
    assert tab.preview.page_label.text() != "—"


def test_output_formatting_append_same_block_twice(tmp_path, qapp, monkeypatch) -> None:
    monkeypatch.setenv("MEW_DB_PATH", str(tmp_path / "ui.db"))
    monkeypatch.setenv(
        "MEW_DATASET_PATH",
        str(Path(__file__).parent / "fixtures" / "sample_dataset"),
    )
    monkeypatch.setattr(SettingsTab, "start_embedding_model_preload", lambda self: None)
    context = bootstrap_app()
    window = MainWindow(context)
    category = evidence_blocks.ensure_uncategorized_category(
        context.conn, context.logger, context.dataset_id
    )
    messages = repositories.list_messages_for_thread(context.conn, context.dataset_id, "thread_001")
    block = evidence_blocks.create_evidence_block(
        context.conn,
        context.logger,
        dataset_id=context.dataset_id,
        category_id=category.category_id,
        source_thread_id="thread_001",
        title="Dup block",
        core_hit_message_id="msg_001",
        ordered_message_ids=[message.message_id for message in messages],
    )
    tab = window.output_formatting_tab
    group_item = tab.artifact_tree.topLevelItem(0)
    tab.handle_evidence_block_drop(block.evidence_block_id, group_item)
    qapp.processEvents()
    group_item = tab.artifact_tree.topLevelItem(0)
    artifact_item = group_item.child(0)
    tab.handle_evidence_block_drop(block.evidence_block_id, artifact_item)
    qapp.processEvents()
    artifact_item = tab.artifact_tree.topLevelItem(0).child(0)
    tab.artifact_tree.setCurrentItem(artifact_item)
    qapp.processEvents()
    assert tab.block_list.count() == 2


def test_output_formatting_preview_pagination_controls(tmp_path, qapp, monkeypatch) -> None:
    from message_evidence_workstation.output.printable_preview import LINES_PER_PAGE, PrintablePreviewPage, PreviewContentLine
    from message_evidence_workstation.output.printable_preview import PrintablePreviewModel

    monkeypatch.setenv("MEW_DB_PATH", str(tmp_path / "ui.db"))
    monkeypatch.setenv(
        "MEW_DATASET_PATH",
        str(Path(__file__).parent / "fixtures" / "sample_dataset"),
    )
    monkeypatch.setattr(SettingsTab, "start_embedding_model_preload", lambda self: None)
    context = bootstrap_app()
    window = MainWindow(context)
    tab = window.output_formatting_tab
    lines = [PreviewContentLine(kind="message_body", text=f"line {index}") for index in range(LINES_PER_PAGE + 5)]
    lines[LINES_PER_PAGE] = PreviewContentLine(kind="message_body", text="<b>literal & text</b>")
    model = PrintablePreviewModel(
        title="Long exhibit",
        exhibit_number="1",
        case_number="2",
        block_sections=[],
        provenance_entries=[],
        pages=[
            PrintablePreviewPage(page_number=1, lines=lines[:LINES_PER_PAGE]),
            PrintablePreviewPage(page_number=2, lines=lines[LINES_PER_PAGE:]),
        ],
        footer_exhibit="1",
        footer_case="2",
    )
    tab.preview.set_preview_model(model)
    qapp.processEvents()
    assert tab.preview.next_button.isEnabled()
    assert not tab.preview.prev_button.isEnabled()
    tab.preview.show_next_page()
    qapp.processEvents()
    assert tab.preview.prev_button.isEnabled()
    assert tab.preview.page_label.text() == "2 / 2"
    assert not tab.preview.title_label.isHidden()
    assert tab.preview.title_label.text() == "Long exhibit"
    assert "&lt;b&gt;literal &amp; text&lt;/b&gt;" in tab.preview.body_label.text()

