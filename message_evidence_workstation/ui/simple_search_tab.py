"""Simple Search tab."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtGui import QColor, QDrag
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSlider,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from message_evidence_workstation.config.settings import is_role_configured, load_settings
from message_evidence_workstation.llm.types import UserFacingModelRole
from message_evidence_workstation.db import repositories
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.nim.client import NimClientError, nim_error_user_message
from message_evidence_workstation.search import fts
from message_evidence_workstation.search.embedding_search import EmbeddingIndexNotReadyError
from message_evidence_workstation.search.grouping import group_hits
from message_evidence_workstation.search.result_models import GroupedSearchResult
from message_evidence_workstation.search.search_modes import SEARCH_MODE_LABELS, SearchMode
from message_evidence_workstation.ui.evidence_block_transcript_widget import EvidenceBlockTranscriptWidget
from message_evidence_workstation.ui.search_worker import (
    SearchCancellationToken,
    SearchJobResult,
    SearchJobSpec,
    run_search_job_background,
)

MIME_SEARCH_RESULT = "application/x-mew-search-result"
MATCH_COLORS = {
    "exact": QColor("#00aa00"),
    "partial": QColor("#88dd88"),
    "keyword": QColor("#cccc00"),
    "fuzzy": QColor("#ffaa33"),
    "message_embedding": QColor("#9933ff"),
    "chunk_embedding": QColor("#ff66cc"),
}


class DraggableResultsList(QListWidget):
    def __init__(self, owner: SimpleSearchTab) -> None:
        super().__init__()
        self._owner = owner
        self.setDragEnabled(True)

    def startDrag(self, supported_actions) -> None:  # noqa: ANN001
        row = self.currentRow()
        if row >= 0:
            self._owner.start_drag_for_row(row)
        else:
            super().startDrag(supported_actions)


class SimpleSearchTab(QWidget):
    evidence_block_created = Signal(int)

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
        self._groups: list[GroupedSearchResult] = []
        self._vector_groups: list[GroupedSearchResult] = []
        self._thread_titles_by_id: dict[str, str] = {}
        self._active_chips: list[str] = []
        self._last_expansion_query = ""
        self._search_generation = 0
        self._search_cancel_token: SearchCancellationToken | None = None
        self._search_thread = None
        self._embedding_model_name = ""
        self._fts_page_offset = 0
        self._fts_total_count = 0
        self._fts_has_more = False
        self._fts_page_hit_count = 0
        self._vector_groups: list[GroupedSearchResult] = []

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Simple Search"))

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Enter query and press Search or Enter...")
        self.search_box.textChanged.connect(self._on_text_changed)
        self.search_box.returnPressed.connect(self._on_search_committed)
        layout.addWidget(self.search_box)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Mode"))
        self.mode_combo = QComboBox()
        for mode in ("fts5", "expanded_keyword", "message_embedding", "chunk_embedding"):
            self.mode_combo.addItem(SEARCH_MODE_LABELS[mode], mode)  # type: ignore[index]
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        mode_row.addWidget(self.mode_combo, stretch=1)
        self.search_button = QPushButton("Search")
        self.search_button.clicked.connect(self._on_search_committed)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._on_cancel_search)
        mode_row.addWidget(self.search_button)
        mode_row.addWidget(self.cancel_button)
        layout.addLayout(mode_row)

        self.embedding_selectivity_row = QWidget()
        vector_selectivity_row = QHBoxLayout(self.embedding_selectivity_row)
        vector_selectivity_row.addWidget(QLabel("Embedding squelch"))
        self.embedding_selectivity = QSlider(Qt.Orientation.Horizontal)
        self.embedding_selectivity.setRange(0, 2)
        self.embedding_selectivity.setSingleStep(1)
        self.embedding_selectivity.setPageStep(1)
        self.embedding_selectivity.setValue(1)
        self.embedding_selectivity.setToolTip(
            "Broad returns more embedding matches; Narrow suppresses more noisy vector matches."
        )
        self.embedding_selectivity.valueChanged.connect(self._on_embedding_selectivity_changed)
        vector_selectivity_row.addWidget(self.embedding_selectivity, stretch=1)
        self.embedding_selectivity_label = QLabel("Balanced")
        vector_selectivity_row.addWidget(self.embedding_selectivity_label)
        layout.addWidget(self.embedding_selectivity_row)

        self.chip_controls = QWidget()
        chip_controls = QHBoxLayout(self.chip_controls)
        self.chip_container = QHBoxLayout()
        chip_wrapper = QWidget()
        chip_wrapper.setLayout(self.chip_container)
        chip_controls.addWidget(chip_wrapper, stretch=1)
        self.add_chip_button = QPushButton("+")
        self.add_chip_button.setFixedWidth(28)
        self.add_chip_button.clicked.connect(self._add_custom_chip)
        chip_controls.addWidget(self.add_chip_button)
        layout.addWidget(self.chip_controls)

        self.status_label = QLabel("Load a dataset to search.")
        layout.addWidget(self.status_label)

        self.pagination_row = QWidget()
        pagination_row = QHBoxLayout(self.pagination_row)
        self.fts_page_label = QLabel("")
        self.fts_prev_button = QPushButton("Previous")
        self.fts_next_button = QPushButton("Next")
        self.fts_prev_button.clicked.connect(self._on_fts_prev_page)
        self.fts_next_button.clicked.connect(self._on_fts_next_page)
        pagination_row.addWidget(self.fts_page_label, stretch=1)
        pagination_row.addWidget(self.fts_prev_button)
        pagination_row.addWidget(self.fts_next_button)
        layout.addWidget(self.pagination_row)

        self.results_splitter = QSplitter(Qt.Orientation.Vertical)
        self.results_list = DraggableResultsList(self)
        self.results_list.currentRowChanged.connect(self._on_result_selected)
        self.results_list.itemDoubleClicked.connect(self._on_result_double_clicked)
        self.results_splitter.addWidget(self.results_list)

        transcript_controls = QHBoxLayout()
        transcript_controls.addWidget(QLabel("Evidence transcript"))
        transcript_controls.addStretch()
        self.add_evidence_block_button = QPushButton("Add evidence block")
        self.add_evidence_block_button.clicked.connect(self._on_add_evidence_block_clicked)
        self.add_evidence_block_button.setEnabled(False)
        transcript_wrapper = QWidget()
        transcript_layout = QVBoxLayout(transcript_wrapper)
        transcript_layout.setContentsMargins(0, 0, 0, 0)
        transcript_layout.addLayout(transcript_controls)
        self.transcript_widget = EvidenceBlockTranscriptWidget(conn, logger, transcript_wrapper)
        self.transcript_widget.evidence_block_created.connect(self.evidence_block_created.emit)
        transcript_layout.addWidget(self.transcript_widget, stretch=1)
        self.results_splitter.addWidget(transcript_wrapper)
        self.results_splitter.setStretchFactor(0, 1)
        self.results_splitter.setStretchFactor(1, 2)
        self.results_splitter.setSizes([240, 480])
        layout.addWidget(self.results_splitter, stretch=1)
        self._on_mode_changed()

    def _selected_mode(self) -> SearchMode:
        return self.mode_combo.currentData()

    def _on_mode_changed(self, _index: int | None = None) -> None:
        mode = self._selected_mode()
        self.embedding_selectivity_row.setVisible(mode in ("message_embedding", "chunk_embedding"))
        self.chip_controls.setVisible(mode == "expanded_keyword")
        self.pagination_row.setVisible(mode in ("fts5", "expanded_keyword"))

    def set_dataset(self, dataset_id: int | None) -> None:
        self.dataset_id = dataset_id
        self._thread_titles_by_id = {}
        self.results_list.clear()
        self._groups = []
        self._vector_groups = []
        self._fts_page_offset = 0
        self._fts_total_count = 0
        self._fts_has_more = False
        self._fts_page_hit_count = 0
        self.transcript_widget.set_dataset(dataset_id)
        self.add_evidence_block_button.setEnabled(dataset_id is not None)
        if dataset_id is None:
            self.status_label.setText("Load a dataset to search.")
            self._update_pagination_controls()
            return
        self._thread_titles_by_id = {
            thread.source_thread_id: thread.display_title
            for thread in repositories.list_source_threads(self.conn, dataset_id)
        }
        self.status_label.setText("Ready.")

    def update_embedding_gating(self, state) -> None:
        from PySide6.QtCore import Qt
        from message_evidence_workstation.domain.embedding_state import EmbeddingState

        if not isinstance(state, EmbeddingState):
            return
        model = self.mode_combo.model()
        for row in range(self.mode_combo.count()):
            mode = self.mode_combo.itemData(row)
            item = model.item(row)
            if item is None or mode not in ("message_embedding", "chunk_embedding"):
                continue
            ready = state.message_ready if mode == "message_embedding" else state.chunk_ready
            progress = state.message_progress if mode == "message_embedding" else state.chunk_progress
            total = state.message_total if mode == "message_embedding" else state.chunk_total
            flags = item.flags()
            if ready:
                item.setFlags(flags | Qt.ItemFlag.ItemIsEnabled)
                item.setToolTip("")
            else:
                item.setFlags(flags & ~Qt.ItemFlag.ItemIsEnabled)
                if total > 0:
                    item.setToolTip(
                        f"{SEARCH_MODE_LABELS[mode]} still building ({progress}/{total}) — "
                        "available when complete"
                    )
                else:
                    item.setToolTip(
                        f"{SEARCH_MODE_LABELS[mode]} unavailable — build embeddings first"
                    )
        if self._selected_mode() in ("message_embedding", "chunk_embedding"):
            current_mode = self._selected_mode()
            ready = state.message_ready if current_mode == "message_embedding" else state.chunk_ready
            if not ready:
                self.mode_combo.setCurrentIndex(0)

    def _on_text_changed(self, _text: str = "") -> None:
        query = self.search_box.text().strip()
        if query != self._last_expansion_query:
            self._active_chips = []
            self._rebuild_chip_widgets()

    def _on_search_committed(self) -> None:
        self._run_search(page_offset=0, expand_keywords=True)

    def _on_cancel_search(self) -> None:
        if self._search_cancel_token is not None:
            self._search_cancel_token.cancel()
        self.cancel_button.setEnabled(False)
        self.status_label.setText("Search cancelled.")

    def _on_embedding_selectivity_changed(self, _value: int) -> None:
        label = {
            "broad": "Broad",
            "balanced": "Balanced",
            "narrow": "Narrow",
        }[self._embedding_selectivity_value()]
        self.embedding_selectivity_label.setText(label)

    def _embedding_selectivity_value(self) -> str:
        return {
            0: "broad",
            1: "balanced",
            2: "narrow",
        }.get(int(self.embedding_selectivity.value()), "balanced")

    def _fts_page_size(self) -> int:
        return max(1, int(load_settings().search.fts_page_size))

    def _format_fts_page_range(self) -> str:
        if self._fts_total_count <= 0:
            return "Showing 0 of 0 matches"
        start = self._fts_page_offset + 1
        end = min(self._fts_page_offset + self._fts_page_hit_count, self._fts_total_count)
        return f"Showing {start:,}–{end:,} of {self._fts_total_count:,} matches"

    def _update_pagination_controls(self) -> None:
        has_query = bool(self.search_box.text().strip()) and self.dataset_id is not None
        if not has_query or self._fts_total_count <= 0:
            self.fts_page_label.setText("")
            self.fts_prev_button.setEnabled(False)
            self.fts_next_button.setEnabled(False)
            return
        self.fts_page_label.setText(self._format_fts_page_range())
        self.fts_prev_button.setEnabled(self._fts_page_offset > 0)
        self.fts_next_button.setEnabled(self._fts_has_more)

    def _on_fts_prev_page(self) -> None:
        page_size = self._fts_page_size()
        next_offset = max(0, self._fts_page_offset - page_size)
        if next_offset == self._fts_page_offset:
            return
        self._run_search(page_offset=next_offset)

    def _on_fts_next_page(self) -> None:
        if not self._fts_has_more:
            return
        self._run_search(page_offset=self._fts_page_offset + self._fts_page_size())

    def _apply_search_result(self, result: SearchJobResult) -> None:
        if result.generation != self._search_generation:
            return
        self.cancel_button.setEnabled(False)
        if result.cancelled:
            self.status_label.setText("Search cancelled.")
            return
        if result.keyword_terms:
            self._active_chips = list(result.keyword_terms)
            self._last_expansion_query = result.query
            self._rebuild_chip_widgets()
        self._groups = list(result.groups)
        self._vector_groups = []
        if result.total_count is not None:
            self._fts_total_count = int(result.total_count)
            self._fts_page_offset = result.offset
            self._fts_has_more = bool(result.has_more)
            self._fts_page_hit_count = sum(len(group.hits) for group in result.groups)
        self._render_results(result.query, status_message=result.status_message)

    def _run_embedding_search(self, query: str, generation: int) -> None:
        mode = self._selected_mode()
        model_name = load_settings().embedding_model
        self._embedding_model_name = model_name
        from message_evidence_workstation.embeddings.model_registry import get_model_spec
        from message_evidence_workstation.ui.embedding_worker import EmbeddingJobSpec, run_embedding_job

        spec = get_model_spec(model_name)
        if spec is None:
            self.cancel_button.setEnabled(False)
            self.status_label.setText(f"Unknown embedding model: {model_name}")
            return

        job = EmbeddingJobSpec(
            job_type="vector_search",
            db_path=self.db_path,
            dataset_id=self.dataset_id,
            adapter_key=spec.adapter_key,
            model_id=spec.model_id,
            vector_query=query,
            use_message_vectors=mode == "message_embedding",
            use_chunk_vectors=mode == "chunk_embedding",
            embedding_selectivity=self._embedding_selectivity_value(),
        )

        def on_success(vector_hits: object) -> None:
            if generation != self._search_generation:
                return
            self.cancel_button.setEnabled(False)
            self._groups = group_hits(
                list(vector_hits),  # type: ignore[arg-type]
                logger=self.logger,
                dataset_id=self.dataset_id,
            )
            self._vector_groups = []
            self._fts_total_count = 0
            self._fts_has_more = False
            self._render_results(
                query,
                status_message=f"Showing top {len(self._groups)} grouped result(s) by similarity.",
            )

        def on_error(exc: BaseException) -> None:
            if generation != self._search_generation:
                return
            self.cancel_button.setEnabled(False)
            if isinstance(exc, EmbeddingIndexNotReadyError):
                self.status_label.setText(str(exc))
            else:
                self.status_label.setText(f"Vector search failed: {exc}")

        run_embedding_job(self, job, on_success=on_success, on_error=on_error)

    def _run_search(self, *, expand_keywords: bool = False, page_offset: int | None = None) -> None:
        self.results_list.clear()
        self._groups = []
        self._vector_groups = []
        self.transcript_widget.set_dataset(self.dataset_id)
        if self.dataset_id is None:
            self._update_pagination_controls()
            return
        query = self.search_box.text().strip()
        if not query:
            self._fts_page_offset = 0
            self._fts_total_count = 0
            self._fts_has_more = False
            self._fts_page_hit_count = 0
            self.status_label.setText("Ready.")
            self._update_pagination_controls()
            return
        if page_offset is None:
            page_offset = 0
        mode = self._selected_mode()
        if mode == "expanded_keyword" and expand_keywords:
            settings = load_settings()
            if not is_role_configured(settings, UserFacingModelRole.EXPANSION) and not self._active_chips:
                self.status_label.setText(
                    "Expansion model not configured — open Setup / Settings and assign an Expansion model."
                )
                return
        self._search_generation += 1
        generation = self._search_generation
        if self._search_cancel_token is not None:
            self._search_cancel_token.cancel()
        self._search_cancel_token = SearchCancellationToken()
        cancel_token = self._search_cancel_token
        self.cancel_button.setEnabled(True)
        self.status_label.setText(f"Searching ({SEARCH_MODE_LABELS[mode]})...")

        if mode in ("message_embedding", "chunk_embedding"):
            self._run_embedding_search(query, generation)
            return

        job = SearchJobSpec(
            db_path=self.db_path,
            dataset_id=self.dataset_id,
            mode=mode,
            query=query,
            page_size=self._fts_page_size(),
            offset=page_offset,
            keyword_terms=list(self._active_chips),
            expand_keywords=expand_keywords and mode == "expanded_keyword",
            generation=generation,
        )

        def on_success(result: SearchJobResult) -> None:
            self._apply_search_result(result)

        def on_error(exc: BaseException) -> None:
            if generation != self._search_generation:
                return
            self.cancel_button.setEnabled(False)
            if isinstance(exc, NimClientError):
                self.status_label.setText(f"Search failed: {nim_error_user_message(exc)}")
            else:
                self.status_label.setText(f"Search failed: {exc}")
            self.logger.error(
                component="ui.simple_search_tab",
                operation="search_failed",
                message=str(exc),
                exc=exc,
                dataset_id=self.dataset_id,
            )

        self._search_thread = run_search_job_background(
            self,
            job,
            cancel_token,
            on_success=on_success,
            on_error=on_error,
        )

    def _rebuild_chip_widgets(self) -> None:
        while self.chip_container.count():
            item = self.chip_container.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for term in self._active_chips:
            row = QHBoxLayout()
            label = QLabel(term)
            remove = QPushButton("x")
            remove.setFixedWidth(22)
            remove.clicked.connect(lambda _checked=False, t=term: self._remove_chip(t))
            wrapper = QWidget()
            row.addWidget(label)
            row.addWidget(remove)
            wrapper.setLayout(row)
            self.chip_container.addWidget(wrapper)

    def _remove_chip(self, term: str) -> None:
        self._active_chips = [chip for chip in self._active_chips if chip != term]
        self._rebuild_chip_widgets()

    def _add_custom_chip(self) -> None:
        term, ok = QInputDialog.getText(self, "Add keyword chip", "Term:")
        if not ok or not term.strip():
            return
        if term.strip() not in self._active_chips:
            self._active_chips.append(term.strip())
            self._rebuild_chip_widgets()

    def _render_results(self, query: str, *, status_message: str = "") -> None:
        self.results_list.clear()
        mode = self._selected_mode()
        for index, group in enumerate(self._groups):
            methods = ", ".join(sorted(group.retrieval_methods))
            primary = group.hits[0]
            distance = f" dist={primary.distance:.4f}" if primary.distance is not None else ""
            rank = f" rank={primary.rank}" if primary.rank is not None else ""
            text = (
                f"[{primary.match_type}] {primary.timestamp} | {primary.sender_display}: "
                f"{group.snippet}{distance}{rank}  "
                f"({len(group.hits)} matching message(s); methods: {methods})"
            )
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, ("result", index))
            item.setForeground(MATCH_COLORS.get(primary.match_type, QColor("#000000")))
            self.results_list.addItem(item)
        if mode in ("message_embedding", "chunk_embedding") and self._groups:
            header = QListWidgetItem("Showing top results by similarity (not a complete result set).")
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            self.results_list.insertItem(0, header)
        if status_message:
            self.status_label.setText(status_message)
        elif self._groups:
            self.status_label.setText(f"{len(self._groups)} grouped result(s) for '{query}'.")
        self._update_pagination_controls()
        if self._groups:
            self.results_list.setCurrentRow(min(1 if mode in ("message_embedding", "chunk_embedding") else 0, self.results_list.count() - 1))

    def _group_for_row(self, row: int) -> GroupedSearchResult | None:
        item = self.results_list.item(row)
        if item is None:
            return None
        payload = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(payload, tuple) or len(payload) != 2:
            return None
        lane, index = payload
        if lane == "result" and 0 <= index < len(self._groups):
            return self._groups[index]
        if lane == "fts" and 0 <= index < len(self._groups):
            return self._groups[index]
        return None

    def _on_result_selected(self, row: int) -> None:
        group = self._group_for_row(row)
        if group is None or self.dataset_id is None:
            return
        self._navigate_to_search_group(group, source_action="result_select")

    def _on_result_double_clicked(self, _item: QListWidgetItem) -> None:
        row = self.results_list.currentRow()
        group = self._group_for_row(row)
        if group is None or self.dataset_id is None:
            return
        self._navigate_to_search_group(group, source_action="result_double_click")
        block = self.transcript_widget.create_evidence_block_for_message(
            group.primary_hit_message_id,
            source_action="result_double_click",
        )
        if block is None:
            return

    def _on_add_evidence_block_clicked(self) -> None:
        self.transcript_widget.create_evidence_block_from_viewport_center(
            source_action="viewport_button",
        )

    def _navigate_to_search_group(
        self,
        group: GroupedSearchResult,
        *,
        source_action: str,
    ) -> None:
        self.transcript_widget.load_source_thread(
            group.source_thread_id,
            source_action=source_action,
        )
        self.transcript_widget.focus_message(
            group.primary_hit_message_id,
            source_action=source_action,
        )
        self.logger.info(
            component="ui.simple_search_tab",
            operation="result_navigation",
            message="Navigated simple search transcript to grouped result",
            details={
                "dataset_id": self.dataset_id,
                "source_thread_id": group.source_thread_id,
                "message_id": group.primary_hit_message_id,
                "source_action": source_action,
            },
            dataset_id=self.dataset_id,
        )

    def start_drag_for_row(self, row: int) -> None:
        group = self._group_for_row(row)
        if group is None:
            return
        mime = QMimeData()
        mime.setData(MIME_SEARCH_RESULT, json.dumps(group.to_drag_payload()).encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)
