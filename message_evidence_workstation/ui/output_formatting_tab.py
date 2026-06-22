"""Output formatting tab — ranges, highlights, HTML preview (T19–T21)."""

from __future__ import annotations

import sqlite3
import tempfile
import webbrowser
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from message_evidence_workstation.config.settings import nim_settings_for_client
from message_evidence_workstation.db import repositories
from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.domain.constants import (
    HIGHLIGHT_CONTEXT,
    HIGHLIGHT_HIT,
    HIGHLIGHT_NONE,
    HIGHLIGHT_RELEVANT,
)
from message_evidence_workstation.domain.models import OutputConversationContext, WorkstationConversation
from message_evidence_workstation.export.html_preview import render_conversation_html, write_conversation_html
from message_evidence_workstation.logging_ui.process_log import ProcessLogger, fetch_process_logs
from message_evidence_workstation.nim.client import NimClient, NimClientError, nim_error_user_message
from message_evidence_workstation.search.range_suggestion import run_range_suggestion
from message_evidence_workstation.ui.background_tasks import run_background
from message_evidence_workstation.ui.source_thread_view import SourceThreadView


class OutputFormattingTab(QWidget):
    def __init__(
        self,
        conn: sqlite3.Connection,
        logger: ProcessLogger,
        *,
        db_path: Path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.conn = conn
        self.logger = logger
        self.db_path = db_path
        self.dataset_id: int | None = None
        self._conversations_by_id: dict[int, WorkstationConversation] = {}
        self._active_conversation_id: int | None = None
        self._active_context: OutputConversationContext | None = None
        self._refresh_handler: Callable[[], None] | None = None
        self._range_generation = 0

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Output Formatting"))

        splitter = QSplitter()
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("Categories"))
        self.category_list = QListWidget()
        self.category_list.currentRowChanged.connect(self._on_category_changed)
        left_layout.addWidget(self.category_list)
        left_layout.addWidget(QLabel("Workstation conversations"))
        self.conversation_list = QListWidget()
        self.conversation_list.currentRowChanged.connect(self._on_conversation_changed)
        left_layout.addWidget(self.conversation_list)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        meta_row = QHBoxLayout()
        self.status_label = QLabel("Status: —")
        meta_row.addWidget(self.status_label)
        meta_row.addStretch()
        self.save_notes_button = QPushButton("Save notes")
        self.save_notes_button.clicked.connect(self._save_notes)
        self.save_notes_button.setEnabled(False)
        meta_row.addWidget(self.save_notes_button)
        right_layout.addLayout(meta_row)

        boundary_row = QHBoxLayout()
        self.boundary_label = QLabel("Boundaries: —")
        self.boundary_label.setWordWrap(True)
        boundary_row.addWidget(self.boundary_label, stretch=1)
        for label, slot in (
            ("Lead-in start", self._set_lead_in_start),
            ("Relevant start", self._set_relevant_start),
            ("Relevant end", self._set_relevant_end),
            ("Lead-out end", self._set_lead_out_end),
        ):
            button = QPushButton(label)
            button.clicked.connect(slot)
            boundary_row.addWidget(button)
        right_layout.addLayout(boundary_row)

        highlight_row = QHBoxLayout()
        highlight_row.addWidget(QLabel("Highlight override:"))
        self.highlight_combo = QComboBox()
        for state in (HIGHLIGHT_NONE, HIGHLIGHT_HIT, HIGHLIGHT_RELEVANT, HIGHLIGHT_CONTEXT):
            self.highlight_combo.addItem(state, state)
        highlight_row.addWidget(self.highlight_combo)
        self.apply_highlight_button = QPushButton("Apply to selected message")
        self.apply_highlight_button.clicked.connect(self._apply_highlight_override)
        highlight_row.addWidget(self.apply_highlight_button)
        highlight_row.addStretch()
        self.request_range_button = QPushButton("Re-run range suggestion")
        self.request_range_button.clicked.connect(self._request_range_suggestion)
        highlight_row.addWidget(self.request_range_button)
        right_layout.addLayout(highlight_row)

        export_row = QHBoxLayout()
        self.include_audit_checkbox = QCheckBox("Include audit appendix")
        export_row.addWidget(self.include_audit_checkbox)
        self.preview_html_button = QPushButton("Preview HTML")
        self.preview_html_button.clicked.connect(self._preview_html)
        export_row.addWidget(self.preview_html_button)
        self.save_html_button = QPushButton("Save HTML…")
        self.save_html_button.clicked.connect(self._save_html)
        export_row.addWidget(self.save_html_button)
        export_row.addStretch()
        right_layout.addLayout(export_row)

        right_layout.addWidget(QLabel("Notes"))
        self.notes_editor = QPlainTextEdit()
        self.notes_editor.setPlaceholderText("Reviewer notes for this workstation conversation…")
        right_layout.addWidget(self.notes_editor)
        self.thread_view = SourceThreadView(conn, logger)
        right_layout.addWidget(self.thread_view, stretch=1)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        layout.addWidget(splitter, stretch=1)

        self.empty_label = QLabel("Load a dataset and add workstation conversations to categories.")
        layout.addWidget(self.empty_label)

    def set_refresh_handler(self, handler: Callable[[], None]) -> None:
        self._refresh_handler = handler

    def set_dataset(self, dataset_id: int | None) -> None:
        self.dataset_id = dataset_id
        self._active_conversation_id = None
        self._active_context = None
        self.category_list.clear()
        self.conversation_list.clear()
        self.notes_editor.clear()
        self.save_notes_button.setEnabled(False)
        self.thread_view.clear()
        self.boundary_label.setText("Boundaries: —")
        if dataset_id is None:
            self.empty_label.show()
            self.status_label.setText("Status: —")
            return
        self.empty_label.hide()
        self.refresh()

    def refresh(self) -> None:
        if self.dataset_id is None:
            return
        selected_category_id: int | None = None
        category_row = self.category_list.currentRow()
        if category_row >= 0:
            item = self.category_list.item(category_row)
            if item is not None:
                selected_category_id = int(item.data(Qt.ItemDataRole.UserRole))
        self.category_list.blockSignals(True)
        self.category_list.clear()
        categories = repositories.list_categories(self.conn, self.dataset_id)
        restore_row = 0
        for index, category in enumerate(categories):
            item = QListWidgetItem(category.name)
            item.setData(Qt.ItemDataRole.UserRole, category.category_id)
            self.category_list.addItem(item)
            if selected_category_id == category.category_id:
                restore_row = index
        self.category_list.blockSignals(False)
        if categories:
            self.category_list.setCurrentRow(restore_row)
        else:
            self.conversation_list.clear()
            self.thread_view.clear()

    def select_workstation_conversation(self, conversation_id: int) -> None:
        if self.dataset_id is None:
            return
        context = repositories.load_output_conversation_context(self.conn, conversation_id)
        if context is None:
            return
        self.refresh()
        for row in range(self.category_list.count()):
            item = self.category_list.item(row)
            if item is None:
                continue
            if int(item.data(Qt.ItemDataRole.UserRole)) == context.conversation.category_id:
                self.category_list.setCurrentRow(row)
                break
        for row in range(self.conversation_list.count()):
            item = self.conversation_list.item(row)
            if item is None:
                continue
            if int(item.data(Qt.ItemDataRole.UserRole)) == conversation_id:
                self.conversation_list.setCurrentRow(row)
                break

    def _on_category_changed(self, row: int) -> None:
        self.conversation_list.clear()
        self._conversations_by_id.clear()
        self._active_conversation_id = None
        self._active_context = None
        self.notes_editor.clear()
        self.save_notes_button.setEnabled(False)
        self.thread_view.clear()
        if row < 0 or self.dataset_id is None:
            return
        item = self.category_list.item(row)
        if item is None:
            return
        category_id = int(item.data(Qt.ItemDataRole.UserRole))
        conversations = repositories.list_workstation_conversations(
            self.conn,
            self.dataset_id,
            category_id,
        )
        for conversation in conversations:
            list_item = QListWidgetItem(f"{conversation.title} ({conversation.status})")
            list_item.setData(Qt.ItemDataRole.UserRole, conversation.workstation_conversation_id)
            self.conversation_list.addItem(list_item)
            self._conversations_by_id[conversation.workstation_conversation_id] = conversation
        if conversations:
            self.conversation_list.setCurrentRow(0)

    def _on_conversation_changed(self, row: int) -> None:
        if row < 0:
            self._active_conversation_id = None
            self.save_notes_button.setEnabled(False)
            return
        item = self.conversation_list.item(row)
        if item is None:
            return
        conversation_id = int(item.data(Qt.ItemDataRole.UserRole))
        self._open_conversation(conversation_id)

    def _needs_range_suggestion(self, context: OutputConversationContext) -> bool:
        conversation_range = context.conversation_range
        if conversation_range is None:
            return True
        if conversation_range.locked:
            return False
        return not conversation_range.user_modified

    def _open_conversation(self, conversation_id: int) -> None:
        context = repositories.load_output_conversation_context(self.conn, conversation_id)
        if context is None:
            return
        self._active_conversation_id = conversation_id
        self._active_context = context
        self.status_label.setText(f"Status: {context.conversation.status}")
        self.notes_editor.setPlainText(context.conversation.user_notes)
        self.save_notes_button.setEnabled(True)
        self._render_context(context)
        if self._needs_range_suggestion(context):
            self._request_range_suggestion()
        self.logger.info(
            component="ui.output_formatting_tab",
            operation="conversation_selected",
            message=f"Selected workstation conversation '{context.conversation.title}'",
            details={
                "workstation_conversation_id": conversation_id,
                "category_name": context.category_name,
                "hit_count": len(context.hits),
            },
            dataset_id=context.conversation.dataset_id,
        )

    def _render_context(self, context: OutputConversationContext) -> None:
        self.thread_view.show_output_conversation(context)
        conversation_range = context.conversation_range
        if conversation_range is None:
            self.boundary_label.setText("Boundaries: not set")
            return
        self.boundary_label.setText(
            "Boundaries: "
            f"lead-in={conversation_range.lead_in_start_message_id}, "
            f"relevant={conversation_range.relevant_start_message_id}"
            f"…{conversation_range.relevant_end_message_id}, "
            f"lead-out={conversation_range.lead_out_end_message_id}"
            + (" (user modified)" if conversation_range.user_modified else "")
        )

    def _reload_active_context(self) -> None:
        if self._active_conversation_id is None:
            return
        context = repositories.load_output_conversation_context(self.conn, self._active_conversation_id)
        if context is None:
            return
        self._active_context = context
        self._render_context(context)

    def _request_range_suggestion(self) -> None:
        if self._active_conversation_id is None or self._active_context is None:
            return
        nim = nim_settings_for_client()
        if not nim.model:
            self.status_label.setText("NIM model not configured for range suggestion.")
            return
        self.status_label.setText("Requesting range suggestion…")
        self._range_generation += 1
        generation = self._range_generation
        conversation_id = self._active_conversation_id
        db_path = self.db_path

        def work() -> None:
            worker_conn = connect(db_path)
            try:
                worker_logger = ProcessLogger(worker_conn, dataset_id=self.dataset_id)
                context = repositories.load_output_conversation_context(worker_conn, conversation_id)
                if context is None:
                    return
                client = NimClient(nim)
                result = run_range_suggestion(
                    worker_conn,
                    worker_logger,
                    client,
                    context=context,
                    dataset_id=context.conversation.dataset_id,
                )
                repositories.upsert_conversation_range(
                    worker_conn,
                    worker_logger,
                    workstation_conversation_id=conversation_id,
                    lead_in_start_message_id=result.lead_in_start_message_id,
                    relevant_start_message_id=result.relevant_start_message_id,
                    relevant_end_message_id=result.relevant_end_message_id,
                    lead_out_end_message_id=result.lead_out_end_message_id,
                    llm_suggested_json=result.raw_payload,
                    user_modified=False,
                )
            finally:
                worker_conn.close()

        def on_success(_: object) -> None:
            if generation != self._range_generation:
                return
            self._reload_active_context()
            self.status_label.setText("Range suggestion stored.")

        def on_error(exc: BaseException) -> None:
            if generation != self._range_generation:
                return
            message = (
                f"Range suggestion failed: {nim_error_user_message(exc)}"
                if isinstance(exc, NimClientError)
                else f"Range suggestion failed: {exc}"
            )
            self.status_label.setText(message)
            self.logger.error(
                component="ui.output_formatting_tab",
                operation="range_suggestion_failed",
                message=message,
                exc=exc,
                dataset_id=self.dataset_id,
            )

        run_background(self, work, on_success=on_success, on_error=on_error)

    def _set_boundary(self, field: str) -> None:
        if self._active_conversation_id is None or self._active_context is None:
            return
        message_id = self.thread_view.selected_message_id()
        if not message_id:
            QMessageBox.information(self, "Select message", "Select a message in the thread first.")
            return
        conversation_range = self._active_context.conversation_range
        lead_in = conversation_range.lead_in_start_message_id if conversation_range else message_id
        rel_start = conversation_range.relevant_start_message_id if conversation_range else message_id
        rel_end = conversation_range.relevant_end_message_id if conversation_range else message_id
        lead_out = conversation_range.lead_out_end_message_id if conversation_range else message_id
        if field == "lead_in":
            lead_in = message_id
        elif field == "relevant_start":
            rel_start = message_id
        elif field == "relevant_end":
            rel_end = message_id
        elif field == "lead_out":
            lead_out = message_id
        repositories.upsert_conversation_range(
            self.conn,
            self.logger,
            workstation_conversation_id=self._active_conversation_id,
            lead_in_start_message_id=lead_in or message_id,
            relevant_start_message_id=rel_start or message_id,
            relevant_end_message_id=rel_end or message_id,
            lead_out_end_message_id=lead_out or message_id,
            llm_suggested_json=conversation_range.llm_suggested_json if conversation_range else {},
            user_modified=True,
            locked=conversation_range.locked if conversation_range else False,
        )
        self._reload_active_context()
        self.status_label.setText("Boundary updated (user modified).")

    def _set_lead_in_start(self) -> None:
        self._set_boundary("lead_in")

    def _set_relevant_start(self) -> None:
        self._set_boundary("relevant_start")

    def _set_relevant_end(self) -> None:
        self._set_boundary("relevant_end")

    def _set_lead_out_end(self) -> None:
        self._set_boundary("lead_out")

    def _apply_highlight_override(self) -> None:
        if self._active_conversation_id is None:
            return
        message_id = self.thread_view.selected_message_id()
        if not message_id:
            QMessageBox.information(self, "Select message", "Select a message to override highlight state.")
            return
        state = str(self.highlight_combo.currentData())
        repositories.set_highlight_override(
            self.conn,
            self.logger,
            workstation_conversation_id=self._active_conversation_id,
            message_id=message_id,
            highlight_state=state,
        )
        self._reload_active_context()
        self.status_label.setText(f"Highlight override saved: {message_id} -> {state}")

    def _current_context_for_export(self) -> OutputConversationContext | None:
        if self._active_conversation_id is None:
            return None
        return repositories.load_output_conversation_context(self.conn, self._active_conversation_id)

    def _preview_html(self) -> None:
        context = self._current_context_for_export()
        if context is None:
            return
        audit_entries = None
        if self.include_audit_checkbox.isChecked():
            audit_entries = fetch_process_logs(self.conn, limit=100)
        html_text = render_conversation_html(
            context,
            include_audit=self.include_audit_checkbox.isChecked(),
            audit_entries=audit_entries,
        )
        temp_path = Path(tempfile.gettempdir()) / f"mew_preview_{context.conversation.workstation_conversation_id}.html"
        temp_path.write_text(html_text, encoding="utf-8")
        webbrowser.open(temp_path.as_uri())
        self.logger.info(
            component="ui.output_formatting_tab",
            operation="html_preview_opened",
            message="Opened HTML preview in browser",
            details={"path": str(temp_path)},
            dataset_id=context.conversation.dataset_id,
        )

    def _save_html(self) -> None:
        context = self._current_context_for_export()
        if context is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save HTML preview",
            f"{context.conversation.title}.html",
            "HTML files (*.html)",
        )
        if not path:
            return
        audit_entries = fetch_process_logs(self.conn, limit=100) if self.include_audit_checkbox.isChecked() else None
        write_conversation_html(
            context,
            Path(path),
            self.logger,
            include_audit=self.include_audit_checkbox.isChecked(),
            audit_entries=audit_entries,
        )
        self.status_label.setText(f"Saved HTML to {path}")

    def _save_notes(self) -> None:
        if self._active_conversation_id is None:
            return
        repositories.update_workstation_conversation_notes(
            self.conn,
            self.logger,
            workstation_conversation_id=self._active_conversation_id,
            user_notes=self.notes_editor.toPlainText(),
        )
        if self._refresh_handler is not None:
            self._refresh_handler()
