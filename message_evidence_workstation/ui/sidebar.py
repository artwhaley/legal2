"""Persistent left sidebar."""

from __future__ import annotations

import json
import sqlite3

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtGui import QAction, QDrag, QDropEvent, QWheelEvent
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from message_evidence_workstation.db import evidence_blocks, repositories
from message_evidence_workstation.domain.constants import UNCATEGORIZED_CATEGORY_NAME
from message_evidence_workstation.domain.models import EvidenceBlock, Message
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
        if event.mimeData().hasFormat(MIME_SEARCH_RESULT):
            category_id = self._category_id_at_drop(event)
            payload = json.loads(bytes(event.mimeData().data(MIME_SEARCH_RESULT)).decode("utf-8"))
            group = GroupedSearchResult.from_drag_payload(payload)
            self._sidebar.handle_search_drop(group, category_id=category_id)
        else:
            category_id = self._category_id_at_drop(event)
            if category_id is None:
                event.ignore()
                return
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

    def contextMenuEvent(self, event) -> None:  # noqa: ANN001
        item = self.itemAt(event.pos())
        if item is None or item.data(0, ROLE_ITEM_KIND) != "evidence_block":
            super().contextMenuEvent(event)
            return
        self.setCurrentItem(item)
        evidence_block_id = int(item.data(0, ROLE_ITEM_ID))
        menu = QMenu(self)
        hidden_in_virtual_transcript = self._sidebar.is_evidence_block_hidden_in_virtual_transcript(
            evidence_block_id
        )
        visibility_action = QAction(
            "Show in virtual transcript" if hidden_in_virtual_transcript else "Hide in virtual transcript",
            self,
        )
        visibility_action.triggered.connect(
            lambda checked=False, block_id=evidence_block_id, hidden=not hidden_in_virtual_transcript: self._sidebar.request_virtual_transcript_visibility_change(
                block_id,
                hidden=hidden,
            )
        )
        menu.addAction(visibility_action)
        edit_action = QAction("Edit evidence block name", self)
        edit_action.triggered.connect(
            lambda checked=False, block_id=evidence_block_id: self._sidebar.prompt_edit_evidence_block_title(block_id)
        )
        menu.addAction(edit_action)
        delete_action = QAction("Delete evidence block", self)
        delete_action.triggered.connect(
            lambda checked=False, block_id=evidence_block_id: self._sidebar.prompt_delete_evidence_block(block_id)
        )
        menu.addAction(delete_action)
        menu.exec(event.globalPos())


class Sidebar(QWidget):
    source_thread_selected = Signal(str, str)
    evidence_block_activated = Signal(int)
    search_drop_evidence_block_created = Signal(object)
    evidence_block_virtual_transcript_visibility_requested = Signal(int, bool)

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
        self._virtual_transcript_hidden_state_provider = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Source thread"))
        self.thread_combo = QComboBox()
        self.thread_combo.currentIndexChanged.connect(self._on_thread_changed)
        layout.addWidget(self.thread_combo)

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
        self.category_tree.itemDoubleClicked.connect(self._on_category_tree_double_clicked)
        layout.addWidget(self.category_tree, stretch=9)

        self.empty_label = QLabel("No dataset loaded.")
        self.empty_label.setWordWrap(True)
        layout.addWidget(self.empty_label, stretch=1)

    def set_dataset(self, dataset_id: int | None) -> None:
        self.dataset_id = dataset_id
        self.thread_combo.blockSignals(True)
        self.thread_combo.clear()
        self.thread_combo.blockSignals(False)
        self.category_tree.clear()
        if dataset_id is None:
            self.empty_label.setText("No dataset loaded. Place a normalized dataset and restart.")
            self.empty_label.show()
            return
        self.empty_label.hide()
        evidence_blocks.ensure_uncategorized_category(self.conn, self.logger, dataset_id)
        self._threads = repositories.list_source_threads(self.conn, dataset_id)
        self.thread_combo.blockSignals(True)
        for thread in self._threads:
            self.thread_combo.addItem(
                f"{thread.display_title} ({thread.message_count})",
                thread.source_thread_id,
            )
        self.thread_combo.blockSignals(False)
        if self.thread_combo.count() > 0:
            self.thread_combo.setCurrentIndex(0)
            self._on_thread_changed(0)
        self.refresh_evidence_blocks()
        self.logger.info(
            component="ui.sidebar",
            operation="dataset_bound",
            message="Sidebar populated from dataset",
            details={"dataset_id": dataset_id, "thread_count": len(self._threads)},
            dataset_id=dataset_id,
        )

    def refresh_evidence_blocks(self) -> None:
        self._refresh_categories()

    def set_virtual_transcript_hidden_state_provider(self, provider) -> None:
        self._virtual_transcript_hidden_state_provider = provider

    def is_evidence_block_hidden_in_virtual_transcript(self, evidence_block_id: int) -> bool:
        provider = self._virtual_transcript_hidden_state_provider
        if provider is None:
            return False
        return bool(provider(evidence_block_id))

    def request_virtual_transcript_visibility_change(
        self,
        evidence_block_id: int,
        *,
        hidden: bool,
    ) -> None:
        self.evidence_block_virtual_transcript_visibility_requested.emit(
            evidence_block_id,
            hidden,
        )

    def reveal_evidence_block(self, evidence_block_id: int) -> None:
        block = evidence_blocks.get_evidence_block(self.conn, evidence_block_id)
        if block is None:
            self.refresh_evidence_blocks()
            return
        self._refresh_categories_and_reveal(
            block.category_id,
            evidence_block_id=evidence_block_id,
        )

    def _evidence_block_sort_keys(
        self,
        blocks: list[EvidenceBlock],
    ) -> dict[int, tuple[bool, str, str, int, str, int]]:
        if self.dataset_id is None or not blocks:
            return {}
        block_ids = [block.evidence_block_id for block in blocks]
        placeholders = ",".join("?" * len(block_ids))
        rows = self.conn.execute(
            f"""
            SELECT eb.evidence_block_id,
                   eb.source_thread_id,
                   COALESCE(context_message.timestamp, core_message.timestamp, '') AS sort_timestamp,
                   COALESCE(context_message.sort_index, core_message.sort_index, 0) AS sort_index,
                   COALESCE(context_message.message_id, core_message.message_id, '') AS sort_message_id
            FROM evidence_block AS eb
            LEFT JOIN message AS context_message
                ON context_message.dataset_id = eb.dataset_id
               AND context_message.source_thread_id = eb.source_thread_id
               AND context_message.thread_ordinal = eb.context_start_slot
            LEFT JOIN message AS core_message
                ON core_message.dataset_id = eb.dataset_id
               AND core_message.message_id = eb.core_hit_message_id
            WHERE eb.evidence_block_id IN ({placeholders})
            """,
            block_ids,
        ).fetchall()
        sort_keys: dict[int, tuple[bool, str, str, int, str, int]] = {}
        for row in rows:
            evidence_block_id = int(row["evidence_block_id"])
            sort_timestamp = str(row["sort_timestamp"] or "")
            sort_keys[evidence_block_id] = (
                sort_timestamp == "",
                sort_timestamp,
                str(row["source_thread_id"] or ""),
                int(row["sort_index"] or 0),
                str(row["sort_message_id"] or ""),
                evidence_block_id,
            )
        return sort_keys

    def _refresh_categories(self) -> None:
        self.category_tree.blockSignals(True)
        self.category_tree.clear()
        if self.dataset_id is None:
            self.category_tree.blockSignals(False)
            return
        uncategorized = evidence_blocks.ensure_uncategorized_category(
            self.conn,
            self.logger,
            self.dataset_id,
        )
        categories = repositories.list_categories(self.conn, self.dataset_id)
        category_by_id = {category.category_id: category for category in categories}
        if uncategorized.category_id not in category_by_id:
            categories.append(uncategorized)
            category_by_id[uncategorized.category_id] = uncategorized

        all_blocks = evidence_blocks.list_evidence_blocks(self.conn, self.dataset_id)
        sort_keys = self._evidence_block_sort_keys(all_blocks)
        blocks_by_category: dict[int, list] = {category.category_id: [] for category in categories}
        for block in all_blocks:
            category_id = block.category_id
            if category_id not in blocks_by_category:
                category_id = uncategorized.category_id
            blocks_by_category.setdefault(category_id, []).append(block)
        for category_id, blocks in blocks_by_category.items():
            blocks_by_category[category_id] = sorted(
                blocks,
                key=lambda block: sort_keys.get(
                    block.evidence_block_id,
                    (True, "", block.source_thread_id, 0, block.core_hit_message_id, block.evidence_block_id),
                ),
            )

        def _category_sort_key(category) -> tuple[int, str]:
            if category.name == UNCATEGORIZED_CATEGORY_NAME:
                return (0, category.name.lower())
            return (1, category.name.lower())

        for category in sorted(categories, key=_category_sort_key):
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
            for block in blocks_by_category.get(category.category_id, []):
                title = block.title
                if self.is_evidence_block_hidden_in_virtual_transcript(block.evidence_block_id):
                    title = f"{title} [hidden]"
                child = QTreeWidgetItem([title])
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

    def _refresh_categories_and_reveal(
        self,
        category_id: int,
        *,
        evidence_block_id: int | None = None,
    ) -> None:
        repositories.set_category_collapsed(self.conn, self.logger, category_id, False)
        self._refresh_categories()
        if evidence_block_id is None:
            return
        for top_index in range(self.category_tree.topLevelItemCount()):
            category_item = self.category_tree.topLevelItem(top_index)
            if int(category_item.data(0, ROLE_ITEM_ID)) != category_id:
                continue
            category_item.setExpanded(True)
            for child_index in range(category_item.childCount()):
                child = category_item.child(child_index)
                if int(child.data(0, ROLE_ITEM_ID)) == evidence_block_id:
                    self.category_tree.blockSignals(True)
                    try:
                        self.category_tree.setCurrentItem(child)
                    finally:
                        self.category_tree.blockSignals(False)
                    return

    def _on_thread_changed(self, index: int) -> None:
        if index < 0 or self.dataset_id is None:
            return
        source_thread_id = self.thread_combo.currentData(Qt.ItemDataRole.UserRole)
        if not isinstance(source_thread_id, str):
            return
        display_title = self.thread_combo.currentText().split(" (", 1)[0]
        self.source_thread_selected.emit(source_thread_id, display_title)

    def _add_category(self) -> None:
        if self.dataset_id is None:
            return
        name, ok = QInputDialog.getText(self, "New Category", "Category name:")
        if not ok or not name.strip():
            return
        repositories.create_category(self.conn, self.logger, self.dataset_id, name.strip())
        self._refresh_categories()

    def _on_category_tree_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        kind = item.data(0, ROLE_ITEM_KIND)
        if kind == "evidence_block":
            self.evidence_block_activated.emit(int(item.data(0, ROLE_ITEM_ID)))
            return
        if kind == "category":
            self._rename_category(item, column)

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
        block = evidence_blocks.create_evidence_block_from_search(
            self.conn,
            self.logger,
            dataset_id=self.dataset_id,
            source_thread_id=source_thread_id,
            primary_hit_message_id=primary.message_id,
            title=title,
            ordered_message_ids=ordered_ids,
        )
        self._refresh_categories_and_reveal(
            block.category_id,
            evidence_block_id=block.evidence_block_id,
        )

    def prompt_category_for_manual_conversation(
        self,
        messages: list[Message],
        source_thread_id: str,
    ) -> None:
        self.create_manual_evidence_block(messages, source_thread_id)

    def move_evidence_block_to_category(self, evidence_block_id: int, category_id: int) -> None:
        block = evidence_blocks.move_evidence_block_to_category(
            self.conn,
            self.logger,
            evidence_block_id=evidence_block_id,
            category_id=category_id,
        )
        self._refresh_categories_and_reveal(
            block.category_id,
            evidence_block_id=block.evidence_block_id,
        )

    def prompt_delete_evidence_block(self, evidence_block_id: int) -> None:
        block = evidence_blocks.get_evidence_block(self.conn, evidence_block_id)
        if block is None:
            self.refresh_evidence_blocks()
            return
        reply = QMessageBox.question(
            self,
            "Delete evidence block?",
            f"Delete evidence block '{block.title}'?\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        evidence_blocks.delete_evidence_block(
            self.conn,
            self.logger,
            evidence_block_id=evidence_block_id,
        )
        self.refresh_evidence_blocks()

    def prompt_edit_evidence_block_title(self, evidence_block_id: int) -> None:
        block = evidence_blocks.get_evidence_block(self.conn, evidence_block_id)
        if block is None:
            self.refresh_evidence_blocks()
            return
        new_title, ok = QInputDialog.getText(
            self,
            "Edit Evidence Block Name",
            "Evidence block name:",
            text=block.title,
        )
        if not ok or not new_title.strip():
            return
        updated = evidence_blocks.update_evidence_block_metadata(
            self.conn,
            self.logger,
            evidence_block_id=evidence_block_id,
            title=new_title.strip(),
        )
        self._refresh_categories_and_reveal(
            updated.category_id,
            evidence_block_id=updated.evidence_block_id,
        )

    def handle_search_drop(
        self,
        group: GroupedSearchResult,
        *,
        category_id: int | None = None,
    ) -> EvidenceBlock | None:
        if self.dataset_id is None or not group.hits:
            return None
        if group.relevant_start_message_id and group.relevant_end_message_id:
            block = evidence_blocks.create_evidence_block_from_conversational_candidate(
                self.conn,
                self.logger,
                dataset_id=self.dataset_id,
                source_thread_id=group.source_thread_id,
                title=group.title or group.snippet or group.primary_hit_message_id,
                summary=group.summary or group.snippet,
                core_message_id=group.primary_hit_message_id,
                leading_context_start_message_id=(
                    group.leading_context_start_message_id or group.relevant_start_message_id
                ),
                relevant_start_message_id=group.relevant_start_message_id,
                relevant_end_message_id=group.relevant_end_message_id,
                trailing_context_end_message_id=(
                    group.trailing_context_end_message_id or group.relevant_end_message_id
                ),
                highlighted_message_ids=[group.primary_hit_message_id],
                category_id=category_id,
            )
        else:
            block = evidence_blocks.create_evidence_block_from_search(
                self.conn,
                self.logger,
                dataset_id=self.dataset_id,
                source_thread_id=group.source_thread_id,
                primary_hit_message_id=group.primary_hit_message_id,
                title=group.title or group.snippet or group.primary_hit_message_id,
                category_id=category_id,
            )
        self.logger.info(
            component="ui.sidebar",
            operation="search_drop_create_evidence_block",
            message="Created evidence block from search drop",
            details={
                "evidence_block_id": block.evidence_block_id,
                "category_id": block.category_id,
                "dataset_id": self.dataset_id,
                "source_thread_id": group.source_thread_id,
                "core_hit_message_id": group.primary_hit_message_id,
                "hit_count": len(group.hits),
                "source_action": "search_drop",
            },
            dataset_id=self.dataset_id,
        )
        self._refresh_categories_and_reveal(
            block.category_id,
            evidence_block_id=block.evidence_block_id,
        )
        self.search_drop_evidence_block_created.emit(block)
        return block
