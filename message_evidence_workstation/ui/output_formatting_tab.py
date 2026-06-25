"""Output formatting tab — printable artifact tree, editor, and paged preview."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from message_evidence_workstation.db import printable_artifacts
from message_evidence_workstation.domain.models import PrintableArtifactContext
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.output.block_labels import block_label_for_index
from message_evidence_workstation.output.printable_preview import build_printable_preview
from message_evidence_workstation.ui.printable_preview_widget import PrintablePreviewWidget
from message_evidence_workstation.ui.sidebar import MIME_EVIDENCE_BLOCK

ROLE_ITEM_ID = int(Qt.ItemDataRole.UserRole)
ROLE_ITEM_KIND = ROLE_ITEM_ID + 1


class PrintableArtifactTree(QTreeWidget):
    def __init__(self, tab: OutputFormattingTab) -> None:
        super().__init__()
        self._tab = tab
        self.setHeaderHidden(True)
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.viewport().setAcceptDrops(True)

    def dragEnterEvent(self, event) -> None:  # noqa: ANN001
        if event.mimeData().hasFormat(MIME_EVIDENCE_BLOCK):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # noqa: ANN001
        if event.mimeData().hasFormat(MIME_EVIDENCE_BLOCK):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        if event.mimeData().hasFormat(MIME_EVIDENCE_BLOCK):
            payload = json.loads(bytes(event.mimeData().data(MIME_EVIDENCE_BLOCK)).decode("utf-8"))
            evidence_block_id = int(payload["evidence_block_id"])
            item = self.itemAt(event.position().toPoint())
            self._tab.handle_evidence_block_drop(evidence_block_id, item)
            event.acceptProposedAction()
            return
        dragged = self.currentItem()
        if dragged is None or dragged.data(0, ROLE_ITEM_KIND) != "artifact":
            super().dropEvent(event)
            return
        target = self.itemAt(event.position().toPoint())
        group_item = target
        while group_item is not None and group_item.data(0, ROLE_ITEM_KIND) != "group":
            group_item = group_item.parent()
        if group_item is None:
            super().dropEvent(event)
            return
        artifact_id = int(dragged.data(0, ROLE_ITEM_ID))
        group_id = int(group_item.data(0, ROLE_ITEM_ID))
        self._tab.move_artifact_to_group(artifact_id, group_id)
        event.acceptProposedAction()


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
        self._refresh_handler: Callable[[], None] | None = None
        self._active_artifact_id: int | None = None
        self._active_context: PrintableArtifactContext | None = None
        self._block_join_ids: list[int] = []

        root = QVBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)

        tree_header = QHBoxLayout()
        tree_header.addWidget(QLabel("Printable artifacts"))
        self.add_group_button = QPushButton("+")
        self.add_group_button.setFixedWidth(28)
        self.add_group_button.clicked.connect(self._add_group)
        tree_header.addWidget(self.add_group_button)
        left_layout.addLayout(tree_header)

        self.artifact_tree = PrintableArtifactTree(self)
        self.artifact_tree.itemCollapsed.connect(self._on_group_collapsed)
        self.artifact_tree.itemExpanded.connect(self._on_group_expanded)
        self.artifact_tree.itemDoubleClicked.connect(self._rename_group)
        self.artifact_tree.currentItemChanged.connect(self._on_tree_selection_changed)
        left_layout.addWidget(self.artifact_tree, stretch=2)

        editor = QWidget()
        editor_layout = QVBoxLayout(editor)
        editor_layout.addWidget(QLabel("Artifact metadata"))
        self.title_field = QLineEdit()
        self.title_field.setPlaceholderText("Title")
        editor_layout.addWidget(self.title_field)
        self.exhibit_field = QLineEdit()
        self.exhibit_field.setPlaceholderText("Exhibit Number")
        editor_layout.addWidget(self.exhibit_field)
        self.case_field = QLineEdit()
        self.case_field.setPlaceholderText("Case Number")
        editor_layout.addWidget(self.case_field)
        self.save_metadata_button = QPushButton("Save metadata")
        self.save_metadata_button.clicked.connect(self._save_metadata)
        self.save_metadata_button.setEnabled(False)
        editor_layout.addWidget(self.save_metadata_button)

        editor_layout.addWidget(QLabel("Included blocks"))
        self.block_list = QListWidget()
        editor_layout.addWidget(self.block_list, stretch=1)
        block_buttons = QHBoxLayout()
        self.move_up_button = QPushButton("Move Up")
        self.move_up_button.clicked.connect(self._move_block_up)
        block_buttons.addWidget(self.move_up_button)
        self.move_down_button = QPushButton("Move Down")
        self.move_down_button.clicked.connect(self._move_block_down)
        block_buttons.addWidget(self.move_down_button)
        self.remove_block_button = QPushButton("Remove")
        self.remove_block_button.clicked.connect(self._remove_block)
        block_buttons.addWidget(self.remove_block_button)
        editor_layout.addLayout(block_buttons)
        self._set_editor_enabled(False)
        left_layout.addWidget(editor, stretch=2)

        self.preview = PrintablePreviewWidget()
        splitter.addWidget(left)
        splitter.addWidget(self.preview)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        root.addWidget(splitter, stretch=1)

        self.empty_label = QLabel("Load a dataset to manage printable artifacts.")
        root.addWidget(self.empty_label)

    def set_refresh_handler(self, handler: Callable[[], None]) -> None:
        self._refresh_handler = handler

    def set_dataset(self, dataset_id: int | None) -> None:
        self.dataset_id = dataset_id
        self._active_artifact_id = None
        self._active_context = None
        self.artifact_tree.clear()
        self._clear_editor()
        self.preview.set_preview_model(None)
        if dataset_id is None:
            self.empty_label.show()
            return
        self.empty_label.hide()
        printable_artifacts.ensure_default_printable_artifact_group(self.conn, self.logger, dataset_id)
        self.refresh()

    def refresh(self) -> None:
        if self.dataset_id is None:
            return
        selected_artifact_id = self._active_artifact_id
        self.artifact_tree.blockSignals(True)
        self.artifact_tree.clear()
        groups = printable_artifacts.list_printable_artifact_groups(self.conn, self.dataset_id)
        for group in groups:
            group_item = QTreeWidgetItem([group.name])
            group_item.setData(0, ROLE_ITEM_ID, group.printable_artifact_group_id)
            group_item.setData(0, ROLE_ITEM_KIND, "group")
            group_item.setFlags(
                group_item.flags()
                | Qt.ItemFlag.ItemIsDropEnabled
                | Qt.ItemFlag.ItemIsEditable
            )
            for artifact in printable_artifacts.list_printable_artifacts(
                self.conn,
                group.printable_artifact_group_id,
            ):
                child = QTreeWidgetItem([artifact.title or f"Artifact {artifact.printable_artifact_id}"])
                child.setData(0, ROLE_ITEM_ID, artifact.printable_artifact_id)
                child.setData(0, ROLE_ITEM_KIND, "artifact")
                child.setFlags(
                    (child.flags() | Qt.ItemFlag.ItemIsDragEnabled | Qt.ItemFlag.ItemIsDropEnabled)
                    & ~Qt.ItemFlag.ItemIsEditable
                )
                group_item.addChild(child)
            self.artifact_tree.addTopLevelItem(group_item)
            group_item.setExpanded(not group.is_collapsed)
        self.artifact_tree.blockSignals(False)
        if selected_artifact_id is not None:
            self._select_artifact_in_tree(selected_artifact_id)
        elif self.artifact_tree.topLevelItemCount() > 0:
            first_group = self.artifact_tree.topLevelItem(0)
            if first_group.childCount() > 0:
                self.artifact_tree.setCurrentItem(first_group.child(0))

    def handle_evidence_block_drop(
        self,
        evidence_block_id: int,
        item: QTreeWidgetItem | None,
    ) -> None:
        if self.dataset_id is None:
            return
        kind = item.data(0, ROLE_ITEM_KIND) if item is not None else None
        if kind == "artifact":
            artifact_id = int(item.data(0, ROLE_ITEM_ID))
            printable_artifacts.append_evidence_block_to_printable_artifact(
                self.conn,
                self.logger,
                artifact_id,
                evidence_block_id,
            )
            self._active_artifact_id = artifact_id
        elif kind == "group":
            group_id = int(item.data(0, ROLE_ITEM_ID))
            artifact = printable_artifacts.create_printable_artifact_from_evidence_block(
                self.conn,
                self.logger,
                self.dataset_id,
                group_id,
                evidence_block_id,
            )
            self._active_artifact_id = artifact.printable_artifact_id
        else:
            default_group = printable_artifacts.ensure_default_printable_artifact_group(
                self.conn,
                self.logger,
                self.dataset_id,
            )
            artifact = printable_artifacts.create_printable_artifact_from_evidence_block(
                self.conn,
                self.logger,
                self.dataset_id,
                default_group.printable_artifact_group_id,
                evidence_block_id,
            )
            self._active_artifact_id = artifact.printable_artifact_id
        self.refresh()
        self._load_active_artifact()

    def move_artifact_to_group(self, artifact_id: int, group_id: int) -> None:
        printable_artifacts.move_printable_artifact_to_group(
            self.conn,
            self.logger,
            artifact_id,
            group_id,
        )
        self._active_artifact_id = artifact_id
        self.refresh()

    def _add_group(self) -> None:
        if self.dataset_id is None:
            return
        from PySide6.QtWidgets import QInputDialog

        name, ok = QInputDialog.getText(self, "New group", "Group name:")
        if not ok or not name.strip():
            return
        printable_artifacts.create_printable_artifact_group(
            self.conn,
            self.logger,
            self.dataset_id,
            name.strip(),
        )
        self.refresh()

    def _rename_group(self, item: QTreeWidgetItem, _column: int) -> None:
        if item.data(0, ROLE_ITEM_KIND) != "group":
            return
        from PySide6.QtWidgets import QInputDialog

        group_id = int(item.data(0, ROLE_ITEM_ID))
        new_name, ok = QInputDialog.getText(self, "Rename group", "Group name:", text=item.text(0))
        if not ok or not new_name.strip():
            return
        printable_artifacts.rename_printable_artifact_group(
            self.conn,
            self.logger,
            group_id,
            new_name.strip(),
        )
        self.refresh()

    def _on_group_collapsed(self, item: QTreeWidgetItem) -> None:
        if item.data(0, ROLE_ITEM_KIND) != "group":
            return
        printable_artifacts.set_printable_artifact_group_collapsed(
            self.conn,
            self.logger,
            int(item.data(0, ROLE_ITEM_ID)),
            True,
        )

    def _on_group_expanded(self, item: QTreeWidgetItem) -> None:
        if item.data(0, ROLE_ITEM_KIND) != "group":
            return
        printable_artifacts.set_printable_artifact_group_collapsed(
            self.conn,
            self.logger,
            int(item.data(0, ROLE_ITEM_ID)),
            False,
        )

    def _on_tree_selection_changed(
        self,
        current: QTreeWidgetItem | None,
        _previous: QTreeWidgetItem | None,
    ) -> None:
        if current is None or current.data(0, ROLE_ITEM_KIND) != "artifact":
            self._active_artifact_id = None
            self._active_context = None
            self._clear_editor()
            self.preview.set_preview_model(None)
            return
        self._active_artifact_id = int(current.data(0, ROLE_ITEM_ID))
        self._load_active_artifact()

    def _select_artifact_in_tree(self, artifact_id: int) -> None:
        for group_index in range(self.artifact_tree.topLevelItemCount()):
            group_item = self.artifact_tree.topLevelItem(group_index)
            for child_index in range(group_item.childCount()):
                child = group_item.child(child_index)
                if int(child.data(0, ROLE_ITEM_ID)) == artifact_id:
                    self.artifact_tree.setCurrentItem(child)
                    return

    def _load_active_artifact(self) -> None:
        if self._active_artifact_id is None:
            return
        context = printable_artifacts.load_printable_artifact_context(
            self.conn,
            self._active_artifact_id,
        )
        if context is None:
            self._clear_editor()
            self.preview.set_preview_model(None)
            return
        self._active_context = context
        self.title_field.setText(context.artifact.title)
        self.exhibit_field.setText(context.artifact.exhibit_number)
        self.case_field.setText(context.artifact.case_number)
        self._populate_block_list(context)
        self._set_editor_enabled(True)
        self._refresh_preview(context)

    def _populate_block_list(self, context: PrintableArtifactContext) -> None:
        self.block_list.clear()
        self._block_join_ids = []
        for index, block in enumerate(context.blocks):
            join_id = block.join.printable_artifact_evidence_block_id
            self._block_join_ids.append(join_id)
            label = block_label_for_index(index)
            item = QListWidgetItem(f"Block {label} - {block.evidence_block.title}")
            item.setData(Qt.ItemDataRole.UserRole, join_id)
            self.block_list.addItem(item)

    def _clear_editor(self) -> None:
        self.title_field.clear()
        self.exhibit_field.clear()
        self.case_field.clear()
        self.block_list.clear()
        self._block_join_ids = []
        self._set_editor_enabled(False)

    def _set_editor_enabled(self, enabled: bool) -> None:
        self.title_field.setEnabled(enabled)
        self.exhibit_field.setEnabled(enabled)
        self.case_field.setEnabled(enabled)
        self.save_metadata_button.setEnabled(enabled)
        self.move_up_button.setEnabled(enabled)
        self.move_down_button.setEnabled(enabled)
        self.remove_block_button.setEnabled(enabled)

    def _save_metadata(self) -> None:
        if self._active_artifact_id is None:
            return
        printable_artifacts.update_printable_artifact_metadata(
            self.conn,
            self.logger,
            self._active_artifact_id,
            self.title_field.text(),
            self.exhibit_field.text(),
            self.case_field.text(),
        )
        self.refresh()
        self._load_active_artifact()

    def _move_block_up(self) -> None:
        row = self.block_list.currentRow()
        if row <= 0 or self._active_artifact_id is None:
            return
        ordered = list(self._block_join_ids)
        ordered[row - 1], ordered[row] = ordered[row], ordered[row - 1]
        self._apply_block_order(ordered)

    def _move_block_down(self) -> None:
        row = self.block_list.currentRow()
        if row < 0 or row >= len(self._block_join_ids) - 1 or self._active_artifact_id is None:
            return
        ordered = list(self._block_join_ids)
        ordered[row + 1], ordered[row] = ordered[row], ordered[row + 1]
        self._apply_block_order(ordered)

    def _remove_block(self) -> None:
        row = self.block_list.currentRow()
        if row < 0 or self._active_artifact_id is None:
            return
        join_id = self._block_join_ids[row]
        printable_artifacts.remove_printable_artifact_block(self.conn, self.logger, join_id)
        self._load_active_artifact()
        self.refresh()

    def _apply_block_order(self, ordered_join_ids: list[int]) -> None:
        if self._active_artifact_id is None:
            return
        printable_artifacts.reorder_printable_artifact_blocks(
            self.conn,
            self.logger,
            self._active_artifact_id,
            ordered_join_ids,
        )
        self._load_active_artifact()

    def _refresh_preview(self, context: PrintableArtifactContext | None = None) -> None:
        if context is None and self._active_artifact_id is not None:
            context = printable_artifacts.load_printable_artifact_context(
                self.conn,
                self._active_artifact_id,
            )
        if context is None:
            self.preview.set_preview_model(None)
            return
        self.preview.set_preview_model(build_printable_preview(context))
