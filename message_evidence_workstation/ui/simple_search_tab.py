"""Simple Search tab."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from PySide6.QtCore import QMimeData, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QDrag
from PySide6.QtWidgets import (
    QCheckBox,
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
from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.llm.router import ModelRouter
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.nim.client import NimClientError, nim_error_user_message
from message_evidence_workstation.search import fts
from message_evidence_workstation.search.embedding_search import (
    EmbeddingIndexNotReadyError,
    search_chunk_embeddings,
    search_message_embeddings,
)
from message_evidence_workstation.search.fusion import fuse_hits
from message_evidence_workstation.search.grouping import group_hits
from message_evidence_workstation.search.keyword_expansion import expand_keywords
from message_evidence_workstation.search.result_models import GroupedSearchResult, SearchHit
from message_evidence_workstation.ui.background_tasks import run_background
from message_evidence_workstation.ui.evidence_block_transcript_widget import EvidenceBlockTranscriptWidget

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
        self._sort_index_by_message: dict[str, int] = {}
        self._thread_titles_by_id: dict[str, str] = {}
        self._active_chips: list[str] = []
        self._last_expansion_query = ""
        self._expansion_generation = 0
        self._vector_search_generation = 0
        self._embedding_model_name = ""

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Simple Search"))

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Type to search messages (FTS5)...")
        self.search_box.textChanged.connect(self._on_text_changed)
        self.search_box.returnPressed.connect(self._on_search_committed)
        self.search_box.editingFinished.connect(self._on_search_committed)
        layout.addWidget(self.search_box)

        self.keyword_toggle = QCheckBox("Keyword Expansion (yellow)")
        self.keyword_toggle.toggled.connect(self._on_keyword_toggle_changed)
        layout.addWidget(self.keyword_toggle)

        self.message_embedding_toggle = QCheckBox("Message Embedding Search (purple)")
        self.message_embedding_toggle.toggled.connect(self._on_vector_toggle_changed)
        layout.addWidget(self.message_embedding_toggle)

        self.chunk_embedding_toggle = QCheckBox("Chunk Embedding Search (pink)")
        self.chunk_embedding_toggle.toggled.connect(self._on_vector_toggle_changed)
        layout.addWidget(self.chunk_embedding_toggle)

        vector_selectivity_row = QHBoxLayout()
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
        layout.addLayout(vector_selectivity_row)

        chip_controls = QHBoxLayout()
        self.chip_container = QHBoxLayout()
        chip_wrapper = QWidget()
        chip_wrapper.setLayout(self.chip_container)
        chip_controls.addWidget(chip_wrapper, stretch=1)
        self.add_chip_button = QPushButton("+")
        self.add_chip_button.setFixedWidth(28)
        self.add_chip_button.clicked.connect(self._add_custom_chip)
        chip_controls.addWidget(self.add_chip_button)
        layout.addLayout(chip_controls)

        self.status_label = QLabel("Load a dataset to search.")
        layout.addWidget(self.status_label)

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

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(300)
        self._debounce.timeout.connect(lambda: self._run_search(expand_keywords=False))

    def set_dataset(self, dataset_id: int | None) -> None:
        self.dataset_id = dataset_id
        self._sort_index_by_message = {}
        self._thread_titles_by_id = {}
        self.results_list.clear()
        self._groups = []
        self.transcript_widget.set_dataset(dataset_id)
        self.add_evidence_block_button.setEnabled(dataset_id is not None)
        if dataset_id is None:
            self.status_label.setText("Load a dataset to search.")
            return
        rows = self.conn.execute(
            "SELECT message_id, sort_index FROM message WHERE dataset_id = ?",
            (dataset_id,),
        ).fetchall()
        self._sort_index_by_message = {row["message_id"]: row["sort_index"] for row in rows}
        self._thread_titles_by_id = {
            thread.source_thread_id: thread.display_title
            for thread in repositories.list_source_threads(self.conn, dataset_id)
        }
        self.status_label.setText("Ready.")

    def _on_text_changed(self, _text: str = "") -> None:
        query = self.search_box.text().strip()
        if query != self._last_expansion_query:
            self._expansion_generation += 1
            self._active_chips = []
            self._rebuild_chip_widgets()
        self._debounce.start()

    def _on_search_committed(self) -> None:
        self._debounce.stop()
        self._run_search(expand_keywords=True)

    def _on_keyword_toggle_changed(self, checked: bool) -> None:
        if not checked:
            self._active_chips = []
            self._last_expansion_query = ""
            self._rebuild_chip_widgets()
            self._debounce.stop()
            self._run_search(expand_keywords=False)
            return
        query = self.search_box.text().strip()
        if query:
            self._debounce.stop()
            self._run_search(expand_keywords=True)

    def _on_vector_toggle_changed(self, _checked: bool = False) -> None:
        if self.search_box.text().strip():
            self._debounce.stop()
            self._run_search(expand_keywords=False)

    def _embedding_selectivity_value(self) -> str:
        return {
            0: "broad",
            1: "balanced",
            2: "narrow",
        }.get(int(self.embedding_selectivity.value()), "balanced")

    def _on_embedding_selectivity_changed(self, _value: int) -> None:
        label = {
            "broad": "Broad",
            "balanced": "Balanced",
            "narrow": "Narrow",
        }[self._embedding_selectivity_value()]
        self.embedding_selectivity_label.setText(label)
        if (
            self.search_box.text().strip()
            and (self.message_embedding_toggle.isChecked() or self.chunk_embedding_toggle.isChecked())
        ):
            self._debounce.stop()
            self._run_search(expand_keywords=False)

    def _message_details(self, message_id: str) -> dict[str, str]:
        row = self.conn.execute(
            """
            SELECT sender_display, timestamp, body
            FROM message
            WHERE dataset_id = ? AND message_id = ?
            """,
            (self.dataset_id, message_id),
        ).fetchone()
        if row is None:
            return {"sender_display": "", "timestamp": "", "body": ""}
        return {
            "sender_display": row["sender_display"],
            "timestamp": row["timestamp"],
            "body": row["body"],
        }

    def _fts_to_search_hits(self, query: str) -> list[SearchHit]:
        assert self.dataset_id is not None
        results = fts.search_messages(self.conn, self.logger, self.dataset_id, query)
        hits: list[SearchHit] = []
        for fts_hit in results["exact"]:
            details = self._message_details(fts_hit.message_id)
            hits.append(
                SearchHit(
                    message_id=fts_hit.message_id,
                    source_thread_id=fts_hit.source_thread_id,
                    match_type="exact",
                    retrieval_method="fts_exact",
                    query_text=query,
                    matched_term=query,
                    score=fts_hit.rank,
                    sender_display=details["sender_display"],
                    timestamp=details["timestamp"],
                    body=details["body"],
                    snippet=details["body"][:160],
                )
            )
        for fts_hit in results["partial"]:
            if any(existing.message_id == fts_hit.message_id for existing in hits):
                continue
            details = self._message_details(fts_hit.message_id)
            hits.append(
                SearchHit(
                    message_id=fts_hit.message_id,
                    source_thread_id=fts_hit.source_thread_id,
                    match_type="partial",
                    retrieval_method="fts_partial",
                    query_text=query,
                    matched_term=query,
                    score=fts_hit.rank,
                    sender_display=details["sender_display"],
                    timestamp=details["timestamp"],
                    body=details["body"],
                    snippet=details["body"][:160],
                )
            )
        for fts_hit in results["fuzzy"]:
            if any(existing.message_id == fts_hit.message_id for existing in hits):
                continue
            details = self._message_details(fts_hit.message_id)
            hits.append(
                SearchHit(
                    message_id=fts_hit.message_id,
                    source_thread_id=fts_hit.source_thread_id,
                    match_type="fuzzy",
                    retrieval_method="spellfix_fuzzy",
                    query_text=query,
                    matched_term=query,
                    score=fts_hit.rank,
                    sender_display=details["sender_display"],
                    timestamp=details["timestamp"],
                    body=details["body"],
                    snippet=details["body"][:160],
                )
            )
        return fuse_hits(hits)

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
        self._run_search()

    def _add_custom_chip(self) -> None:
        term, ok = QInputDialog.getText(self, "Add keyword chip", "Term:")
        if not ok or not term.strip():
            return
        if term.strip() not in self._active_chips:
            self._active_chips.append(term.strip())
            self._rebuild_chip_widgets()
            self._run_search()

    def _keyword_hits(self, query: str) -> list[SearchHit]:
        assert self.dataset_id is not None
        hits: list[SearchHit] = []
        for chip in self._active_chips:
            for fts_hit in fts.search_exact(self.conn, self.logger, self.dataset_id, chip):
                details = self._message_details(fts_hit.message_id)
                hits.append(
                    SearchHit(
                        message_id=fts_hit.message_id,
                        source_thread_id=fts_hit.source_thread_id,
                        match_type="keyword",
                        retrieval_method="keyword_expansion",
                        query_text=query,
                        matched_term=chip,
                        score=fts_hit.rank,
                        sender_display=details["sender_display"],
                        timestamp=details["timestamp"],
                        body=details["body"],
                        snippet=details["body"][:160],
                    )
                )
        return hits

    def _request_keyword_expansion(self, query: str) -> None:
        if not self.keyword_toggle.isChecked() or query == self._last_expansion_query:
            return
        settings = load_settings()
        if not is_role_configured(settings, UserFacingModelRole.EXPANSION):
            self.status_label.setText(
                "Expansion model not configured — open Setup / Settings and assign an Expansion model."
            )
            return

        self._expansion_generation += 1
        generation = self._expansion_generation
        self.status_label.setText("Requesting keyword expansion...")
        dataset_id = self.dataset_id
        db_path = self.db_path

        def work() -> list[str]:
            worker_conn = connect(db_path)
            try:
                worker_logger = ProcessLogger(worker_conn, dataset_id=dataset_id)
                router = ModelRouter(load_settings())
                return expand_keywords(
                    worker_conn,
                    worker_logger,
                    router,
                    query,
                    dataset_id=dataset_id,
                )
            finally:
                worker_conn.close()

        def on_success(terms: object) -> None:
            if generation != self._expansion_generation:
                return
            expansion_query = self.search_box.text().strip()
            self._active_chips = list(terms)  # type: ignore[arg-type]
            self._last_expansion_query = expansion_query
            self._rebuild_chip_widgets()
            self._run_search(expand_keywords=False)
            if self.message_embedding_toggle.isChecked() or self.chunk_embedding_toggle.isChecked():
                current_query = self.search_box.text().strip()
                if current_query:
                    hits = self._fts_to_search_hits(current_query)
                    if self._active_chips and current_query == self._last_expansion_query:
                        hits = fuse_hits(hits, self._keyword_hits(current_query))
                    self._request_vector_search(current_query, hits)

        def on_error(exc: BaseException) -> None:
            if generation != self._expansion_generation:
                return
            if isinstance(exc, NimClientError):
                self.status_label.setText(f"Keyword expansion failed: {nim_error_user_message(exc)}")
                self.logger.error(
                    component="ui.simple_search_tab",
                    operation="keyword_expansion_failed",
                    message=str(exc),
                    exc=exc,
                    dataset_id=self.dataset_id,
                )
            else:
                self.status_label.setText(f"Keyword expansion failed: {exc}")
                self.logger.error(
                    component="ui.simple_search_tab",
                    operation="keyword_expansion_failed",
                    message="Unexpected keyword expansion failure",
                    exc=exc,
                    dataset_id=self.dataset_id,
                )

        run_background(self, work, on_success=on_success, on_error=on_error)

    def _request_vector_search(self, query: str, base_hits: list[SearchHit]) -> None:
        if not (
            self.message_embedding_toggle.isChecked() or self.chunk_embedding_toggle.isChecked()
        ):
            return
        if self.dataset_id is None:
            return
        model_name = load_settings().embedding_model
        self._embedding_model_name = model_name
        self._vector_search_generation += 1
        generation = self._vector_search_generation
        use_message = self.message_embedding_toggle.isChecked()
        use_chunk = self.chunk_embedding_toggle.isChecked()
        self.status_label.setText(self.status_label.text() + " | vector search in progress...")

        from message_evidence_workstation.embeddings.model_registry import get_model_spec
        from message_evidence_workstation.ui.embedding_worker import EmbeddingJobSpec, run_embedding_job

        spec = get_model_spec(model_name)
        if spec is None:
            self.status_label.setText(f"Unknown embedding model: {model_name}")
            return

        job = EmbeddingJobSpec(
            job_type="vector_search",
            db_path=self.db_path,
            dataset_id=self.dataset_id,
            adapter_key=spec.adapter_key,
            model_id=spec.model_id,
            vector_query=query,
            use_message_vectors=use_message,
            use_chunk_vectors=use_chunk,
            embedding_selectivity=self._embedding_selectivity_value(),
        )

        def on_success(vector_hits: object) -> None:
            if generation != self._vector_search_generation:
                return
            merged = fuse_hits(base_hits, list(vector_hits))  # type: ignore[arg-type]
            if self.keyword_toggle.isChecked() and self._active_chips and query == self._last_expansion_query:
                merged = fuse_hits(merged, self._keyword_hits(query))
            self._groups = group_hits(
                merged,
                sort_index_by_message=self._sort_index_by_message,
                logger=self.logger,
                dataset_id=self.dataset_id,
            )
            self._render_results(query, vector_pending=False)

        def on_error(exc: BaseException) -> None:
            if generation != self._vector_search_generation:
                return
            if isinstance(exc, EmbeddingIndexNotReadyError):
                self.status_label.setText(str(exc))
            else:
                self.status_label.setText(f"Vector search failed: {exc}")
            self.logger.error(
                component="ui.simple_search_tab",
                operation="vector_search_failed",
                message=str(exc),
                exc=exc,
                dataset_id=self.dataset_id,
            )

        run_embedding_job(self, job, on_success=on_success, on_error=on_error)

    def _run_search(self, *, expand_keywords: bool = False) -> None:
        self.results_list.clear()
        self._groups = []
        self.transcript_widget.set_dataset(self.dataset_id)
        if self.dataset_id is None:
            return
        query = self.search_box.text().strip()
        if not query:
            self.status_label.setText("Ready.")
            return
        try:
            hits = self._fts_to_search_hits(query)
            if self.keyword_toggle.isChecked():
                if self._active_chips and query == self._last_expansion_query:
                    hits = fuse_hits(hits, self._keyword_hits(query))
            self._groups = group_hits(
                hits,
                sort_index_by_message=self._sort_index_by_message,
                logger=self.logger,
                dataset_id=self.dataset_id,
            )
        except sqlite3.OperationalError:
            self.status_label.setText("Search failed - see process log for FTS syntax/details.")
            return
        vector_pending = (
            self.message_embedding_toggle.isChecked() or self.chunk_embedding_toggle.isChecked()
        )
        self._render_results(query, vector_pending=vector_pending)
        if expand_keywords and self.keyword_toggle.isChecked():
            self._request_keyword_expansion(query)
        if vector_pending:
            self._request_vector_search(query, hits)

    def _render_results(self, query: str, *, vector_pending: bool = False) -> None:
        self.results_list.clear()
        for index, group in enumerate(self._groups):
            methods = ", ".join(sorted(group.retrieval_methods))
            primary = group.hits[0]
            distance = ""
            if primary.distance is not None:
                distance = f" dist={primary.distance:.4f}"
            rank = f" rank={primary.rank}" if primary.rank is not None else ""
            text = (
                f"[{primary.match_type}] {primary.timestamp} | {primary.sender_display}: "
                f"{group.snippet}{distance}{rank}  "
                f"({len(group.hits)} matching message(s); methods: {methods})"
            )
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, index)
            item.setForeground(MATCH_COLORS.get(primary.match_type, QColor("#000000")))
            self.results_list.addItem(item)
        status = f"{len(self._groups)} grouped result(s) for '{query}'."
        if (
            self.keyword_toggle.isChecked()
            and query != self._last_expansion_query
            and self._expansion_generation > 0
        ):
            status += " (keyword expansion in progress...)"
        if vector_pending:
            status += " (vector search in progress...)"
        self.status_label.setText(status)
        if self._groups:
            self.results_list.setCurrentRow(0)

    def _on_result_selected(self, row: int) -> None:
        if row < 0 or row >= len(self._groups) or self.dataset_id is None:
            return
        group = self._groups[row]
        self._navigate_to_search_group(group, source_action="result_select")

    def _on_result_double_clicked(self, _item: QListWidgetItem) -> None:
        row = self.results_list.currentRow()
        if row < 0 or row >= len(self._groups) or self.dataset_id is None:
            return
        group = self._groups[row]
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
        if row < 0 or row >= len(self._groups):
            return
        group = self._groups[row]
        mime = QMimeData()
        mime.setData(MIME_SEARCH_RESULT, json.dumps(group.to_drag_payload()).encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)
