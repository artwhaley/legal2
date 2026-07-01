"""Main application window."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from message_evidence_workstation.app_bootstrap import AppContext, StartupLoadOptions
from message_evidence_workstation.config.settings import load_settings
from message_evidence_workstation.db import repositories
from message_evidence_workstation.domain.embedding_state import EmbeddingState
from message_evidence_workstation.ui.conversational_tab import ConversationalTab
from message_evidence_workstation.ui.embedding_progress_controller import EmbeddingProgressController
from message_evidence_workstation.ui.home_tab import HomeTab
from message_evidence_workstation.ui.output_formatting_tab import OutputFormattingTab
from message_evidence_workstation.ui.settings_tab import SettingsTab
from message_evidence_workstation.ui.sidebar import Sidebar
from message_evidence_workstation.ui.simple_search_tab import SimpleSearchTab
from message_evidence_workstation.ui.transcript_widget_tab import TranscriptWidgetTab
from message_evidence_workstation.ui.new_transcript_widget_tab import NewTranscriptWidgetTab
from message_evidence_workstation.ui.virtual_transcript_widget_tab import VirtualTranscriptWidgetTab


class MainWindow(QMainWindow):
    def __init__(
        self,
        context: AppContext,
        *,
        startup_load: StartupLoadOptions | None = None,
    ) -> None:
        super().__init__()
        self.context = context
        self._startup_load = startup_load
        self._home_tab_index: int | None = None
        self._dataset_tabs_built = False
        self.setWindowTitle("Message Evidence Workstation")
        self.resize(1280, 800)

        self._embedding_controller = EmbeddingProgressController(context.log_bus, self)
        self._embedding_controller.state_changed.connect(self._on_embedding_state_changed)
        self.context.embedding_state = self._embedding_controller.state

        self._status_bar = QStatusBar(self)
        self.setStatusBar(self._status_bar)

        central = QWidget()
        root_layout = QHBoxLayout(central)

        self.sidebar = Sidebar(context.conn, context.logger)
        self.sidebar.setFixedWidth(300)
        root_layout.addWidget(self.sidebar)

        right = QWidget()
        right_layout = QVBoxLayout(right)

        self.tabs = QTabWidget()
        self.home_tab = HomeTab(
            context.conn,
            context.logger,
            db_path=context.db_path,
            initial_dataset_path=startup_load.dataset_path if startup_load else None,
            reload_dataset=startup_load.reload if startup_load else False,
            skip_embedding_on_load=(
                startup_load.skip_embedding if startup_load is not None else False
            ),
            auto_run_on_show=startup_load is not None,
        )
        self._home_tab_index = self.tabs.addTab(self.home_tab, "Home")
        self.settings_tab = SettingsTab(
            context.conn,
            context.logger,
            context.log_bus,
            dataset_id=None,
            db_path=context.db_path,
        )
        self.settings_index = self.tabs.addTab(self.settings_tab, "Setup / Settings")

        self.simple_search_tab: SimpleSearchTab | None = None
        self.conversational_tab: ConversationalTab | None = None
        self.output_formatting_tab: OutputFormattingTab | None = None
        self.transcript_widget_tab: TranscriptWidgetTab | None = None
        self.new_transcript_widget_tab: NewTranscriptWidgetTab | None = None
        self.virtual_transcript_widget_tab: VirtualTranscriptWidgetTab | None = None
        self.simple_search_index = -1
        self.conversational_index = -1
        self.output_formatting_index = -1
        self.transcript_index = -1
        self.new_transcript_index = -1
        self.virtual_transcript_index = -1

        self._add_locked_dataset_tabs()

        self.home_tab.dataset_imported.connect(self._on_dataset_imported)
        self.home_tab.load_completed.connect(self._on_dataset_load_completed)
        self.home_tab.load_failed.connect(self._on_dataset_load_failed)
        self.home_tab.embeddings_ready.connect(self._on_embeddings_ready)

        right_layout.addWidget(self.tabs)
        root_layout.addWidget(right, stretch=1)

        self.setCentralWidget(central)

        self.sidebar.source_thread_selected.connect(self._on_source_thread_selected)
        self.sidebar.evidence_block_activated.connect(self._on_sidebar_evidence_block_activated)

        self.tabs.currentChanged.connect(self._on_tab_changed)

        self._set_dataset_tabs_enabled(False)
        self.tabs.setCurrentWidget(self.home_tab)

        self.settings_tab.start_embedding_model_preload()

        context.logger.info(
            component="ui.main_window",
            operation="window_ready",
            message="Main window initialized",
            details={"dataset_id": context.dataset_id},
            dataset_id=context.dataset_id,
        )

    def _add_locked_dataset_tabs(self) -> None:
        if self._dataset_tabs_built:
            return
        self.simple_search_tab = SimpleSearchTab(
            self.context.conn, self.context.logger, db_path=self.context.db_path
        )
        self.conversational_tab = ConversationalTab(
            self.context.conn, self.context.logger, db_path=self.context.db_path
        )
        self.output_formatting_tab = OutputFormattingTab(
            self.context.conn, self.context.logger, db_path=self.context.db_path
        )
        self.transcript_widget_tab = TranscriptWidgetTab(self.context.conn, self.context.logger)
        self.new_transcript_widget_tab = NewTranscriptWidgetTab(
            self.context.conn, self.context.logger
        )
        self.virtual_transcript_widget_tab = VirtualTranscriptWidgetTab(
            self.context.conn, self.context.logger
        )

        self.simple_search_index = self.tabs.addTab(self.simple_search_tab, "Simple Search")
        self.conversational_index = self.tabs.addTab(
            self.conversational_tab, "Conversational Interface"
        )
        self.output_formatting_index = self.tabs.addTab(
            self.output_formatting_tab, "Output Formatting"
        )
        self.transcript_index = self.tabs.addTab(
            self.transcript_widget_tab, "Transcript Widget"
        )
        self.new_transcript_index = self.tabs.addTab(
            self.new_transcript_widget_tab,
            "New Transcript Widget",
        )
        self.virtual_transcript_index = self.tabs.addTab(
            self.virtual_transcript_widget_tab,
            "Virtual Transcript Widget",
        )

        self.simple_search_tab.evidence_block_created.connect(
            self._on_simple_search_evidence_block_created
        )
        self.transcript_widget_tab.evidence_block_created.connect(
            self._on_transcript_evidence_block_created
        )
        self.new_transcript_widget_tab.evidence_block_created.connect(
            self._on_transcript_evidence_block_created
        )
        self.virtual_transcript_widget_tab.evidence_block_created.connect(
            self._on_transcript_evidence_block_created
        )
        self.virtual_transcript_widget_tab.evidence_block_deleted.connect(
            self._refresh_workspaces
        )
        self.conversational_tab.set_category_refresh_handler(self._refresh_workspaces)
        self.conversational_tab.message_citation_selected.connect(
            self._on_conversational_citation_selected
        )
        self.output_formatting_tab.set_refresh_handler(self._refresh_workspaces)
        self.sidebar.search_drop_evidence_block_created.connect(
            self._on_search_drop_evidence_block_created
        )
        self._dataset_tabs_built = True
        self._set_dataset_tabs_enabled(False)

    def _on_embedding_state_changed(self, state: EmbeddingState) -> None:
        self.context.embedding_state = state
        text = self._embedding_controller.status_text()
        self._status_bar.showMessage(text)
        if self.simple_search_tab is not None:
            self.simple_search_tab.update_embedding_gating(state)
        if self.conversational_tab is not None:
            self.conversational_tab.update_embedding_gating(state)

    def _on_tab_changed(self, index: int) -> None:
        if index < 0:
            return
        widget = self.tabs.widget(index)
        if widget is self.new_transcript_widget_tab and self.new_transcript_widget_tab is not None:
            self.new_transcript_widget_tab.ensure_document_loaded()
        if widget is self.transcript_widget_tab and self.transcript_widget_tab is not None:
            self.transcript_widget_tab.ensure_thread_loaded()
        if widget is self.virtual_transcript_widget_tab and self.virtual_transcript_widget_tab is not None:
            self.virtual_transcript_widget_tab.ensure_thread_loaded()

    def _set_dataset_tabs_enabled(self, enabled: bool) -> None:
        for index in (
            self.simple_search_index,
            self.conversational_index,
            self.output_formatting_index,
            self.transcript_index,
            self.new_transcript_index,
            self.virtual_transcript_index,
        ):
            if index >= 0:
                self.tabs.setTabEnabled(index, enabled)

    def _activate_dataset(self, dataset_id: int, *, embedding_available: bool = False) -> None:
        self.context.dataset_id = dataset_id
        self.context.embedding_available = embedding_available
        self.context.logger.dataset_id = dataset_id
        self._add_locked_dataset_tabs()

        def bind_lightweight() -> None:
            if self.simple_search_tab is not None:
                self.simple_search_tab.set_dataset(dataset_id)
            if self.conversational_tab is not None:
                self.conversational_tab.set_dataset(dataset_id)
            if self.output_formatting_tab is not None:
                self.output_formatting_tab.set_dataset(dataset_id)
            if self.settings_tab is not None:
                self.settings_tab.set_dataset(dataset_id)
            self._set_dataset_tabs_enabled(True)
            model_id = load_settings().embedding_model
            self._embedding_controller.refresh_from_db(
                self.context.conn,
                dataset_id=dataset_id,
                model_name=model_id,
            )

        def bind_sidebar() -> None:
            self.sidebar.set_dataset(dataset_id)

        def bind_transcripts() -> None:
            if self.transcript_widget_tab is not None:
                self.transcript_widget_tab.set_dataset(dataset_id)
            if self.new_transcript_widget_tab is not None:
                self.new_transcript_widget_tab.set_dataset(dataset_id)
            if self.virtual_transcript_widget_tab is not None:
                self.virtual_transcript_widget_tab.set_dataset(dataset_id)

        bind_lightweight()
        QTimer.singleShot(0, self, bind_sidebar)
        QTimer.singleShot(0, self, bind_transcripts)

        self.context.logger.info(
            component="ui.main_window",
            operation="dataset_activated",
            message="Dataset activated in main window",
            details={
                "dataset_id": dataset_id,
                "embedding_available": embedding_available,
            },
            dataset_id=dataset_id,
        )

    def _on_dataset_imported(self, result: object) -> None:
        from message_evidence_workstation.dataset_load_pipeline import DatasetLoadResult

        if not isinstance(result, DatasetLoadResult) or result.dataset_id is None:
            return
        self._activate_dataset(result.dataset_id, embedding_available=False)
        self._embedding_controller.mark_build_started()

    def _on_embeddings_ready(self, result: object) -> None:
        from message_evidence_workstation.dataset_load_pipeline import DatasetLoadResult

        if not isinstance(result, DatasetLoadResult) or result.dataset_id is None:
            return
        self.context.embedding_available = bool(result.embedding_available)
        model_id = load_settings().embedding_model
        self._embedding_controller.refresh_from_db(
            self.context.conn,
            dataset_id=result.dataset_id,
            model_name=model_id,
        )

    def _on_dataset_load_completed(self, result: object) -> None:
        from message_evidence_workstation.dataset_load_pipeline import DatasetLoadResult

        if not isinstance(result, DatasetLoadResult):
            return
        if result.dataset_id is None:
            return
        try:
            if self.context.dataset_id != result.dataset_id:
                self._activate_dataset(
                    result.dataset_id,
                    embedding_available=result.embedding_available,
                )
            else:
                self.context.embedding_available = result.embedding_available
                model_id = load_settings().embedding_model
                self._embedding_controller.refresh_from_db(
                    self.context.conn,
                    dataset_id=result.dataset_id,
                    model_name=model_id,
                )
        except Exception as exc:
            self.context.logger.error(
                component="ui.main_window",
                operation="dataset_activation_failed",
                message=str(exc),
                exc=exc,
                dataset_id=result.dataset_id,
            )
            self._set_dataset_tabs_enabled(False)
            self.tabs.setCurrentWidget(self.home_tab)
            self.home_tab._append_status(f"Dataset activation failed: {exc}")

    def _on_dataset_load_failed(self, result: object) -> None:
        self._set_dataset_tabs_enabled(False)
        self.tabs.setCurrentWidget(self.home_tab)

    def _refresh_workspaces(self) -> None:
        self.sidebar.refresh_evidence_blocks()
        if self.output_formatting_tab is not None:
            self.output_formatting_tab.refresh()

    def _on_transcript_evidence_block_created(self, evidence_block_id: int) -> None:
        self.sidebar.reveal_evidence_block(evidence_block_id)

    def _on_simple_search_evidence_block_created(self, evidence_block_id: int) -> None:
        self.sidebar.reveal_evidence_block(evidence_block_id)

    def _on_search_drop_evidence_block_created(self, block: object) -> None:
        from message_evidence_workstation.domain.models import EvidenceBlock
        from message_evidence_workstation.domain.constants import CREATED_BY_CONVERSATIONAL_ANSWER

        if not isinstance(block, EvidenceBlock):
            return
        if self.conversational_tab is None or self.simple_search_tab is None:
            return
        if block.created_by == CREATED_BY_CONVERSATIONAL_ANSWER:
            self.tabs.setCurrentWidget(self.conversational_tab)
            self.conversational_tab.transcript_widget.reveal_created_evidence_block(
                block,
                source_action="answer_hit_drop",
            )
            return
        self.tabs.setCurrentWidget(self.simple_search_tab)
        self.simple_search_tab.transcript_widget.reveal_created_evidence_block(
            block,
            source_action="search_drop",
        )

    def _on_sidebar_evidence_block_activated(self, evidence_block_id: int) -> None:
        current = self.tabs.currentWidget()
        if current is self.virtual_transcript_widget_tab and self.virtual_transcript_widget_tab is not None:
            self.virtual_transcript_widget_tab.reveal_evidence_block(evidence_block_id)
            return
        if current is self.transcript_widget_tab and self.transcript_widget_tab is not None:
            self.transcript_widget_tab.select_evidence_block(evidence_block_id)
            return
        if current is self.new_transcript_widget_tab and self.new_transcript_widget_tab is not None:
            self.new_transcript_widget_tab.transcript_widget.select_evidence_block(evidence_block_id)
            return
        if current is self.simple_search_tab and self.simple_search_tab is not None:
            self.simple_search_tab.transcript_widget.select_evidence_block(evidence_block_id)
            return
        if current is self.conversational_tab and self.conversational_tab is not None:
            self.conversational_tab.transcript_widget.select_evidence_block(evidence_block_id)

    def _on_source_thread_selected(self, source_thread_id: str, display_title: str) -> None:
        if self.context.dataset_id is None:
            return
        if self.transcript_widget_tab is not None:
            self.tabs.setCurrentWidget(self.transcript_widget_tab)
            self.transcript_widget_tab.select_source_thread(source_thread_id)
        if self.new_transcript_widget_tab is not None:
            self.new_transcript_widget_tab.select_source_thread(source_thread_id)
        if self.virtual_transcript_widget_tab is not None:
            self.virtual_transcript_widget_tab.select_source_thread(source_thread_id)

    def _on_conversational_citation_selected(self, message_id: str, source_thread_id: str) -> None:
        if self.context.dataset_id is None or self.transcript_widget_tab is None:
            return
        self.tabs.setCurrentWidget(self.transcript_widget_tab)
        self.transcript_widget_tab.select_source_thread(source_thread_id)
        self.transcript_widget_tab.transcript_widget.focus_message(message_id)
