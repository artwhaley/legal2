"""Source thread message viewer widget."""

from __future__ import annotations

import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from message_evidence_workstation.db import repositories
from message_evidence_workstation.domain.constants import (
    HIGHLIGHT_CONTEXT,
    HIGHLIGHT_HIT,
    HIGHLIGHT_NONE,
    HIGHLIGHT_RELEVANT,
)
from message_evidence_workstation.domain.models import Message, OutputConversationContext
from message_evidence_workstation.logging_ui.process_log import ProcessLogger


class SourceThreadView(QWidget):
    def __init__(
        self,
        conn: sqlite3.Connection,
        logger: ProcessLogger,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.conn = conn
        self.logger = logger
        self.dataset_id: int | None = None
        self._messages: list[Message] = []
        self._selected_indices: list[int] = []
        self._row_by_message_id: dict[str, int] = {}

        layout = QVBoxLayout(self)
        self.header = QLabel("Select a source thread from the sidebar.")
        self.header.setWordWrap(True)
        layout.addWidget(self.header)

        self.message_list = QListWidget()
        self.message_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.message_list.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.message_list)

        action_row = QHBoxLayout()
        self.selection_label = QLabel("No messages selected.")
        action_row.addWidget(self.selection_label)
        action_row.addStretch()
        self.create_conversation_button = QPushButton("Create conversation from selection")
        self.create_conversation_button.setEnabled(False)
        self.create_conversation_button.clicked.connect(self._request_manual_conversation)
        action_row.addWidget(self.create_conversation_button)
        layout.addLayout(action_row)

        self._manual_conversation_handler = None

    def set_manual_conversation_handler(self, handler) -> None:
        self._manual_conversation_handler = handler

    def clear(self) -> None:
        self.dataset_id = None
        self._messages = []
        self._selected_indices = []
        self._row_by_message_id = {}
        self.header.setText("No dataset loaded.")
        self.message_list.clear()
        self.selection_label.setText("No messages selected.")
        self.create_conversation_button.setEnabled(False)

    def show_thread(self, dataset_id: int, source_thread_id: str, display_title: str) -> None:
        self.dataset_id = dataset_id
        self._messages = repositories.list_messages_for_thread(self.conn, dataset_id, source_thread_id)
        self._render_plain_thread(
            header_text=(
                f"Source thread: {display_title} ({source_thread_id}) - "
                f"{len(self._messages)} messages"
            )
        )
        self.logger.info(
            component="ui.source_thread_view",
            operation="thread_selected",
            message=f"Displayed source thread '{display_title}'",
            details={
                "dataset_id": dataset_id,
                "source_thread_id": source_thread_id,
                "message_count": len(self._messages),
            },
            dataset_id=dataset_id,
        )
        self.selection_label.setText("No messages selected.")
        self.create_conversation_button.setEnabled(False)

    def show_output_conversation(self, context: OutputConversationContext) -> None:
        """Render a full source thread with range/highlight styling."""
        conversation = context.conversation
        self.dataset_id = conversation.dataset_id
        self._messages = context.messages
        self.header.setText(
            f"{context.category_name} / {conversation.title}\n"
            f"Source thread: {context.thread_display_title} ({conversation.source_thread_id}) "
            f"- {len(self._messages)} messages"
        )
        self._render_styled_thread(
            display_states=context.display_states or {},
            boundary_labels=context.boundary_labels or {},
            focus_message_id=conversation.primary_hit_message_id,
        )
        self.logger.info(
            component="ui.source_thread_view",
            operation="output_conversation_opened",
            message=f"Opened output view for workstation conversation '{conversation.title}'",
            details={
                "workstation_conversation_id": conversation.workstation_conversation_id,
                "source_thread_id": conversation.source_thread_id,
                "message_count": len(self._messages),
                "hit_count": len(context.hit_message_ids),
                "has_range": context.conversation_range is not None,
            },
            dataset_id=conversation.dataset_id,
        )
        self.selection_label.setText(f"Status: {conversation.status}")
        self.create_conversation_button.setEnabled(False)

    def show_search_group(
        self,
        *,
        dataset_id: int,
        source_thread_id: str,
        display_title: str,
        primary_hit_message_id: str,
        hit_message_ids: set[str],
        retrieval_methods: set[str],
    ) -> None:
        self.dataset_id = dataset_id
        self._messages = repositories.list_messages_for_thread(self.conn, dataset_id, source_thread_id)
        methods = ", ".join(sorted(retrieval_methods))
        self.header.setText(
            f"Search context: {display_title} ({source_thread_id})\n"
            f"{len(hit_message_ids)} matching message(s) in this grouped result. "
            f"Methods: {methods}"
        )
        display_states = {
            message.message_id: (
                HIGHLIGHT_HIT if message.message_id in hit_message_ids else HIGHLIGHT_NONE
            )
            for message in self._messages
        }
        self._render_styled_thread(
            display_states=display_states,
            boundary_labels={},
            focus_message_id=primary_hit_message_id,
        )
        self.selection_label.setText(f"{len(hit_message_ids)} matching message(s) highlighted.")
        self.create_conversation_button.setEnabled(self._manual_conversation_handler is not None)

    def selected_message_id(self) -> str | None:
        if not self._selected_indices:
            return None
        return self._messages[self._selected_indices[0]].message_id

    def selected_messages(self) -> list[Message]:
        return [self._messages[index] for index in self._selected_indices]

    def focus_message(self, message_id: str) -> None:
        row = self._row_by_message_id.get(message_id)
        if row is None:
            return
        self.message_list.setCurrentRow(row)
        item = self.message_list.item(row)
        if item is not None:
            self.message_list.scrollToItem(
                item,
                QAbstractItemView.ScrollHint.PositionAtCenter,
            )

    def _on_selection_changed(self) -> None:
        self._selected_indices = sorted(index.row() for index in self.message_list.selectedIndexes())
        if not self._selected_indices:
            self.selection_label.setText("No messages selected.")
            self.create_conversation_button.setEnabled(False)
            return
        count = len(self._selected_indices)
        self.selection_label.setText(f"{count} message(s) selected.")
        self.create_conversation_button.setEnabled(self._manual_conversation_handler is not None)

    def _request_manual_conversation(self) -> None:
        if not self._manual_conversation_handler or not self._selected_indices:
            return
        selected_messages = [self._messages[index] for index in self._selected_indices]
        self._manual_conversation_handler(selected_messages)

    def _render_plain_thread(self, *, header_text: str) -> None:
        self.header.setText(header_text)
        self.message_list.clear()
        self._row_by_message_id = {}
        for index, message in enumerate(self._messages):
            attachment = ""
            if message.has_attachment and message.attachment_summary:
                attachment = f" [attachment: {message.attachment_summary}]"
            text = (
                f"{message.timestamp} | {message.sender_display}: {message.body}"
                f"{attachment}  [id={message.message_id}]"
            )
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, message.message_id)
            self.message_list.addItem(item)
            self._row_by_message_id[message.message_id] = index

    def _render_styled_thread(
        self,
        *,
        display_states: dict[str, str],
        boundary_labels: dict[str, str],
        focus_message_id: str | None,
    ) -> None:
        self.message_list.clear()
        self._row_by_message_id = {}
        styles = {
            HIGHLIGHT_HIT: (QColor("#1a7a1a"), True),
            HIGHLIGHT_RELEVANT: (QColor("#1a4a7a"), True),
            HIGHLIGHT_CONTEXT: (QColor("#555555"), False),
            HIGHLIGHT_NONE: (QColor("#111111"), False),
        }
        for index, message in enumerate(self._messages):
            attachment = ""
            if message.has_attachment and message.attachment_summary:
                attachment = f" [attachment: {message.attachment_summary}]"
            boundary = boundary_labels.get(message.message_id, "")
            prefix = f"[{boundary}] " if boundary else ""
            state = display_states.get(message.message_id, HIGHLIGHT_NONE)
            text = (
                f"{prefix}{message.timestamp} | {message.sender_display}: {message.body}"
                f"{attachment}  [id={message.message_id}; {state}]"
            )
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, message.message_id)
            color, bold = styles.get(state, styles[HIGHLIGHT_NONE])
            font = QFont(item.font())
            font.setBold(bold)
            item.setFont(font)
            item.setForeground(QBrush(color))
            self.message_list.addItem(item)
            self._row_by_message_id[message.message_id] = index
        if focus_message_id is not None:
            self.focus_message(focus_message_id)
