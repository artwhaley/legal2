"""Main application window."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from message_evidence_workstation.app_bootstrap import AppContext
from message_evidence_workstation.db import repositories
from message_evidence_workstation.ui.conversational_tab import ConversationalTab
from message_evidence_workstation.ui.output_formatting_tab import OutputFormattingTab
from message_evidence_workstation.ui.settings_tab import SettingsTab
from message_evidence_workstation.ui.sidebar import Sidebar
from message_evidence_workstation.ui.simple_search_tab import SimpleSearchTab
from message_evidence_workstation.ui.transcript_widget_tab import TranscriptWidgetTab


class MainWindow(QMainWindow):
    def __init__(self, context: AppContext) -> None:
        super().__init__()
        self.context = context
        self.setWindowTitle("Message Evidence Workstation")
        self.resize(1280, 800)

        central = QWidget()
        root_layout = QHBoxLayout(central)

        self.sidebar = Sidebar(context.conn, context.logger)
        self.sidebar.setFixedWidth(300)
        root_layout.addWidget(self.sidebar)

        right = QWidget()
        right_layout = QVBoxLayout(right)

        self.tabs = QTabWidget()
        self.simple_search_tab = SimpleSearchTab(
            context.conn, context.logger, db_path=context.db_path
        )
        self.conversational_tab = ConversationalTab(
            context.conn, context.logger, db_path=context.db_path
        )
        self.output_formatting_tab = OutputFormattingTab(
            context.conn, context.logger, db_path=context.db_path
        )
        self.transcript_widget_tab = TranscriptWidgetTab(context.conn, context.logger)

        self.tabs.addTab(self.simple_search_tab, "Simple Search")
        self.tabs.addTab(self.conversational_tab, "Conversational Interface")
        self.tabs.addTab(self.output_formatting_tab, "Output Formatting")
        self.settings_tab = SettingsTab(
            context.conn,
            context.logger,
            context.log_bus,
            dataset_id=context.dataset_id,
            db_path=context.db_path,
        )
        self.tabs.addTab(self.settings_tab, "Setup / Settings")
        self.tabs.addTab(self.transcript_widget_tab, "Transcript Widget")
        right_layout.addWidget(self.tabs)
        root_layout.addWidget(right, stretch=1)

        self.setCentralWidget(central)

        self.sidebar.source_thread_selected.connect(self._on_source_thread_selected)
        self.transcript_widget_tab.evidence_block_created.connect(self._on_transcript_evidence_block_created)
        self.simple_search_tab.evidence_block_created.connect(self._on_simple_search_evidence_block_created)
        self.sidebar.search_drop_evidence_block_created.connect(self._on_search_drop_evidence_block_created)
        self.sidebar.set_dataset(context.dataset_id)
        self.simple_search_tab.set_dataset(context.dataset_id)
        self.conversational_tab.set_dataset(context.dataset_id)
        self.conversational_tab.set_category_refresh_handler(self._refresh_workspaces)
        self.conversational_tab.message_citation_selected.connect(
            self._on_conversational_citation_selected
        )
        self.output_formatting_tab.set_dataset(context.dataset_id)
        self.output_formatting_tab.set_refresh_handler(self._refresh_workspaces)
        self.transcript_widget_tab.set_dataset(context.dataset_id)
        if context.dataset_id is not None:
            self.tabs.setCurrentWidget(self.transcript_widget_tab)

        context.logger.info(
            component="ui.main_window",
            operation="window_ready",
            message="Main window initialized",
            details={"dataset_id": context.dataset_id},
            dataset_id=context.dataset_id,
        )

    def _refresh_workspaces(self) -> None:
        self.sidebar.refresh_evidence_blocks()
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

    def _placeholder_tab(self, title: str) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(QLabel(f"{title} — placeholder (future ticket)"))
        layout.addStretch()
        return widget

    def _on_source_thread_selected(self, source_thread_id: str, display_title: str) -> None:
        if self.context.dataset_id is None:
            return
        self.tabs.setCurrentWidget(self.transcript_widget_tab)
        self.transcript_widget_tab.select_source_thread(source_thread_id)

    def _on_conversational_citation_selected(self, message_id: str, source_thread_id: str) -> None:
        if self.context.dataset_id is None:
            return
        threads = repositories.list_source_threads(self.context.conn, self.context.dataset_id)
        display_title = source_thread_id
        for thread in threads:
            if thread.source_thread_id == source_thread_id:
                display_title = thread.display_title
                break
        self.tabs.setCurrentWidget(self.transcript_widget_tab)
        self.transcript_widget_tab.select_source_thread(source_thread_id)
        self.transcript_widget_tab.transcript_widget.focus_message(message_id)
