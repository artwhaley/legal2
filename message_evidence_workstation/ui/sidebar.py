"""Persistent left sidebar."""

from __future__ import annotations

import json
import sqlite3

from PySide6.QtCore import Qt, Signal
from PySide6.QtCore import QMimeData
from PySide6.QtGui import QDrag, QDropEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from message_evidence_workstation.db import evidence_blocks, repositories
from message_evidence_workstation.domain.models import Message
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.search.result_models import GroupedSearchResult
from message_evidence_workstation.ui.simple_search_tab import MIME_SEARCH_RESULT

ROLE_ITEM_ID = int(Qt.ItemDataRole.UserRole)
ROLE_ITEM_KIND = ROLE_ITEM_ID + 1
MIME_EVIDENCE_BLOCK = "application/x-mew-evidence-block"


class CategoryDropTree(QTreeWidget):
    def __init__(self, sidebar: Sidebar) -> None:
        super().__init__()
        self._sidebar = sidebar
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.viewport().setAcceptDrops(True)

    def dragEnterEvent(self, event) -> None:  # noqa: ANN001
        if event.mimeData().hasFormat(MIME_SEARCH_RESULT) or event.mimeData().hasFormat(MIME_EVIDENCE_BLOCK):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # noqa: ANN001
        if event.mimeData().hasFormat(MIME_SEARCH_RESULT) or event.mimeData().hasFormat(MIME_EVIDENCE_BLOCK):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def startDrag(self, supported_actions) -> None:  # noqa: ANN001
        item = self.currentItem()
        if item is None or item.data(0, ROLE_ITEM_KIND) != "evidence_block":
            super().startDrag(supported_actions)
            return
        mime = QMimeData()
        mime.setData(
            MIME_EVIDENCE_BLOCK,
            json.dumps({"evidence_block_id": int(item.data(0, ROLE_ITEM_ID))}).encode("utf-8"),
        )
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction)

    def dropEvent(self, event: QDropEvent) -> None:
        if not (
            event.mimeData().hasFormat(MIME_SEARCH_RESULT)
            or event.mimeData().hasFormat(MIME_EVIDENCE_BLOCK)
        ):
            super().dropEvent(event)
            return
        category_id = self._category_id_at_drop(event)
        if category_id is None:
            event.ignore()
            return
        if event.mimeData().hasFormat(MIME_SEARCH_RESULT):
            payload = json.loads(bytes(event.mimeData().data(MIME_SEARCH_RESULT)).decode("utf-8"))
            group = GroupedSearchResult.from_drag_payload(payload)
            self._sidebar.handle_search_drop(group, category_id=category_id)
        else:
            payload = json.loads(bytes(event.mimeData().data(MIME_EVIDENCE_BLOCK)).decode("utf-8"))
            self._sidebar.move_evidence_block_to_category(
                int(payload["evidence_block_id"]),
                category_id,
            )
        event.acceptProposedAction()

    def _category_id_at_drop(self, event: QDropEvent) -> int | None:
        item = self.itemAt(event.position().toPoint())
        if item is None:
            return None
        while item.parent() is not None:
            item = item.parent()
        if item.data(0, ROLE_ITEM_KIND) != "category":
            return None
        return int(item.data(0, ROLE_ITEM_ID))


class Sidebar(QWidget):
    source_thread_selected = Signal(str, str)
    workstation_conversation_selected = Signal(int)
    evidence_block_selected = Signal(int)

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
        self._threads: list = []

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Source Threads"))

        self.thread_list = QListWidget()
        self.thread_list.currentItemChanged.connect(self._on_thread_changed)
        layout.addWidget(self.thread_list)

        category_header = QHBoxLayout()
        category_header.addWidget(QLabel("Evidence Blocks"))
        self.add_category_button = QPushButton("+")
        self.add_category_button.setFixedWidth(28)
        self.add_category_button.clicked.connect(self._add_category)
        category_header.addWidget(self.add_category_button)
        layout.addLayout(category_header)

        self.category_tree = CategoryDropTree(self)
        self.category_tree.setHeaderHidden(True)
        self.category_tree.itemCollapsed.connect(self._on_category_item_collapsed)
        self.category_tree.itemExpanded.connect(self._on_category_item_expanded)
        self.category_tree.currentItemChanged.connect(self._on_category_tree_current_item_changed)
        self.category_tree.itemDoubleClicked.connect(self._rename_category)
        layout.addWidget(self.category_tree)

        self.empty_label = QLabel("No dataset loaded.")
        self.empty_label.setWordWrap(True)
        layout.addWidget(self.empty_label)

    def set_dataset(self, dataset_id: int | None) -> None:
        self.dataset_id = dataset_id
        self.thread_list.clear()
        self.category_tree.clear()
        if dataset_id is None:
            self.empty_label.setText("No dataset loaded. Place a normalized dataset and restart.")
            self.empty_label.show()
            return
        self.empty_label.hide()
        self._threads = repositories.list_source_threads(self.conn, dataset_id)
        for thread in self._threads:
            item = QListWidgetItem(f"{thread.display_title} ({thread.message_count})")
            item.setData(0, thread.source_thread_id)
            self.thread_list.addItem(item)
        self._refresh_categories()
        self.logger.info(
            component="ui.sidebar",
            operation="dataset_bound",
            message="Sidebar populated from dataset",
            details={"dataset_id": dataset_id, "thread_count": len(self._threads)},
            dataset_id=dataset_id,
        )

    def _refresh_categories(self) -> None:
        self.category_tree.blockSignals(True)
        self.category_tree.clear()
        if self.dataset_id is None:
            self.category_tree.blockSignals(False)
            return
        categories = repositories.list_categories(self.conn, self.dataset_id)
        for category in categories:
            category_item = QTreeWidgetItem([category.name])
            category_item.setData(0, ROLE_ITEM_ID, category.category_id)
            category_item.setData(0, ROLE_ITEM_KIND, "category")
            category_item.setFlags(
                (
                    category_item.flags()
                    | Qt.ItemFlag.ItemIsEditable
                    | Qt.ItemFlag.ItemIsDropEnabled
                )
                & ~Qt.ItemFlag.ItemIsUserCheckable
            )
            blocks = evidence_blocks.list_evidence_blocks(
                self.conn,
                self.dataset_id,
                category_id=category.category_id,
            )
            for block in blocks:
                child = QTreeWidgetItem([block.title])
                child.setData(0, ROLE_ITEM_ID, block.evidence_block_id)
                child.setData(0, ROLE_ITEM_KIND, "evidence_block")
                child.setFlags(
                    (child.flags() | Qt.ItemFlag.ItemIsDragEnabled)
                    & ~Qt.ItemFlag.ItemIsDropEnabled
                    & ~Qt.ItemFlag.ItemIsUserCheckable
                )
                category_item.addChild(child)
            self.category_tree.addTopLevelItem(category_item)
            category_item.setExpanded(not category.is_collapsed)
        self.category_tree.blockSignals(False)

    def _on_thread_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if current is None or self.dataset_id is None:
            return
        source_thread_id = current.data(0)
        display_title = current.text().split(" (", 1)[0]
        self.source_thread_selected.emit(source_thread_id, display_title)

    def _add_category(self) -> None:
        if self.dataset_id is None:
            return
        name, ok = QInputDialog.getText(self, "New Category", "Category name:")
        if not ok or not name.strip():
            return
        repositories.create_category(self.conn, self.logger, self.dataset_id, name.strip())
        self._refresh_categories()

    def _rename_category(self, item: QTreeWidgetItem, _column: int) -> None:
        if item.data(0, ROLE_ITEM_KIND) != "category":
            return
        category_id = int(item.data(0, ROLE_ITEM_ID))
        new_name, ok = QInputDialog.getText(self, "Rename Category", "Category name:", text=item.text(0))
        if not ok or not new_name.strip():
            return
        repositories.rename_category(self.conn, self.logger, category_id, new_name.strip())
        self._refresh_categories()

    def _on_category_item_collapsed(self, item: QTreeWidgetItem) -> None:
        if item.data(0, ROLE_ITEM_KIND) != "category":
            return
        category_id = int(item.data(0, ROLE_ITEM_ID))
        repositories.set_category_collapsed(self.conn, self.logger, category_id, True)

    def _on_category_item_expanded(self, item: QTreeWidgetItem) -> None:
        if item.data(0, ROLE_ITEM_KIND) != "category":
            return
        category_id = int(item.data(0, ROLE_ITEM_ID))
        repositories.set_category_collapsed(self.conn, self.logger, category_id, False)

    def _on_category_tree_current_item_changed(
        self,
        current: QTreeWidgetItem | None,
        _previous: QTreeWidgetItem | None,
    ) -> None:
        if current is None:
            return
        kind = current.data(0, ROLE_ITEM_KIND)
        item_id = int(current.data(0, ROLE_ITEM_ID))
        if kind == "evidence_block":
            self.evidence_block_selected.emit(item_id)

    def create_manual_evidence_block(
        self,
        messages: list[Message],
        source_thread_id: str,
    ) -> None:
        if self.dataset_id is None or not messages:
            return
        primary = messages[0]
        title = primary.body[:80] if primary.body else f"Evidence {primary.message_id}"
        ordered_ids = [message.message_id for message in messages]
        evidence_blocks.create_evidence_block_from_search(
            self.conn,
            self.logger,
            dataset_id=self.dataset_id,
            source_thread_id=source_thread_id,
            primary_hit_message_id=primary.message_id,
            title=title,
            ordered_message_ids=ordered_ids,
        )
        self._refresh_categories()

    def prompt_category_for_manual_conversation(
        self,
        messages: list[Message],
        source_thread_id: str,
    ) -> None:
        self.create_manual_evidence_block(messages, source_thread_id)

    def move_evidence_block_to_category(self, evidence_block_id: int, category_id: int) -> None:
        evidence_blocks.move_evidence_block_to_category(
            self.conn,
            self.logger,
            evidence_block_id=evidence_block_id,
            category_id=category_id,
        )
        self._refresh_categories()

    def handle_search_drop(
        self,
        group: GroupedSearchResult,
        *,
        category_id: int | None = None,
    ) -> None:
        if self.dataset_id is None or not group.hits:
            return
        messages = repositories.list_messages_for_thread(
            self.conn,
            self.dataset_id,
            group.source_thread_id,
        )
        ordered_ids = [message.message_id for message in messages]
        block = evidence_blocks.create_evidence_block_from_search(
            self.conn,
            self.logger,
            dataset_id=self.dataset_id,
            source_thread_id=group.source_thread_id,
            primary_hit_message_id=group.primary_hit_message_id,
            title=group.title,
            ordered_message_ids=ordered_ids,
            category_id=category_id,
        )
        self.logger.info(
            component="ui.sidebar",
            operation="search_drop_create_evidence_block",
            message="Created evidence block from search drop",
            details={
                "evidence_block_id": block.evidence_block_id,
                "category_id": block.category_id,
                "hit_count": len(group.hits),
            },
            dataset_id=self.dataset_id,
        )
        self._refresh_categories()
