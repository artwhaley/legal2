"""Small, explicit Python client for the v15 split architecture."""

from __future__ import annotations

import json
import time

from PySide6.QtCore import QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QComboBox,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from message_evidence_workstation.app_bootstrap import AppContext
from message_evidence_workstation.client_api.gateway import (
    RemoteGatewayCancelled,
    RequestCancellation,
)
from message_evidence_workstation.db.corpus_repository import WorkingCorpusRepository
from message_evidence_workstation.domain.search_scope import NarrowedSearchScope, WorkingCorpusScope
from message_evidence_workstation.services.client_workflows import (
    ClientWorkflowService,
    ConversationalWorkflow,
    ConversationalExecutionResult,
    ConversationalSearchProgress,
    EmbeddingBuildCoordinator,
    EmbeddingBuildProgress,
    EmbeddingBuildResult,
    EmbeddingSearchWorkflow,
    KeywordSearchWorkflow,
    clear_local_embeddings,
    format_conversational_result,
)


class EmbeddingBuildWorker(QThread):
    progress = Signal(object)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, context: AppContext, scope: WorkingCorpusScope) -> None:
        super().__init__()
        self.context = context
        self.scope = scope

    def run(self) -> None:
        try:
            result = EmbeddingBuildCoordinator(
                self.context.store,
                self.context.logger,
                self.context.gateway,
            ).build(self.scope, self.progress.emit)
            self.succeeded.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class ConversationalSearchWorker(QThread):
    progress = Signal(object)
    succeeded = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(
        self,
        context: AppContext,
        scope: WorkingCorpusScope,
        query: str,
    ) -> None:
        super().__init__()
        self.context = context
        self.scope = scope
        self.query = query
        self.cancellation = RequestCancellation()

    def cancel_request(self) -> None:
        self.cancellation.cancel()

    def run(self) -> None:
        try:
            coordinator = ConversationalWorkflow(
                self.context.store, self.context.logger, self.context.gateway
            )
            result = coordinator.execute(
                NarrowedSearchScope(self.scope),
                self.query,
                self.progress.emit,
                cancellation=self.cancellation,
            )
            self.succeeded.emit(result)
        except RemoteGatewayCancelled:
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self, context: AppContext, *, startup_load: object | None = None) -> None:
        super().__init__()
        self.context = context
        self.embedding_worker: EmbeddingBuildWorker | None = None
        self.embedding_started_at = 0.0
        self.embedding_progress_state: EmbeddingBuildProgress | None = None
        self.embedding_timer = QTimer(self)
        self.embedding_timer.setInterval(1000)
        self.embedding_timer.timeout.connect(self._refresh_embedding_progress_text)
        self.conversation_worker: ConversationalSearchWorker | None = None
        self.conversation_progress_state: ConversationalSearchProgress | None = None
        self.conversation_started_at = 0.0
        self.conversation_timer = QTimer(self)
        self.conversation_timer.setInterval(1000)
        self.conversation_timer.timeout.connect(self._refresh_conversation_progress_text)
        self.setWindowTitle("Message Evidence Workstation — EVW v15")
        self.resize(1100, 720)
        root = QWidget()
        layout = QVBoxLayout(root)
        self.scope_label = QLabel("Select a ready corpus revision")
        layout.addWidget(self.scope_label)
        selector_row = QHBoxLayout()
        selector_row.addWidget(QLabel("Corpus revision:"))
        self.scope_combo = QComboBox()
        self.scope_combo.currentIndexChanged.connect(self._on_scope_changed)
        selector_row.addWidget(self.scope_combo, 1)
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self._refresh_revisions)
        selector_row.addWidget(refresh_button)
        self.clear_embeddings_button = QPushButton("Clear local embeddings")
        self.clear_embeddings_button.clicked.connect(self._clear_embeddings)
        selector_row.addWidget(self.clear_embeddings_button)
        layout.addLayout(selector_row)
        query_row = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("Search or ask about the selected corpus revision")
        query_row.addWidget(self.query)
        self.search_buttons: list[QPushButton] = []
        for label, handler in (("FTS5", self._fts), ("Keyword", self._keyword), ("Embedding", self._embedding), ("Conversational", self._conversation)):
            button = QPushButton(label)
            button.clicked.connect(handler)
            query_row.addWidget(button)
            self.search_buttons.append(button)
            if label == "Embedding":
                self.embedding_search_button = button
            elif label == "Conversational":
                self.conversation_button = button
        layout.addLayout(query_row)
        self.conversation_progress_label = QLabel("Conversational search has not started")
        self.conversation_progress_label.setVisible(False)
        layout.addWidget(self.conversation_progress_label)
        self.conversation_progress_bar = QProgressBar()
        self.conversation_progress_bar.setVisible(False)
        layout.addWidget(self.conversation_progress_bar)
        self.cancel_conversation_button = QPushButton("Cancel conversational search")
        self.cancel_conversation_button.clicked.connect(self._cancel_conversation)
        self.cancel_conversation_button.setVisible(False)
        layout.addWidget(self.cancel_conversation_button)
        self.rebuild_button = QPushButton("Build / refresh local embeddings")
        self.rebuild_button.clicked.connect(self._build_embeddings)
        layout.addWidget(self.rebuild_button)
        self.embedding_progress_label = QLabel("Embedding build has not started")
        self.embedding_progress_label.setVisible(False)
        layout.addWidget(self.embedding_progress_label)
        self.embedding_progress_bar = QProgressBar()
        self.embedding_progress_bar.setVisible(False)
        layout.addWidget(self.embedding_progress_bar)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        layout.addWidget(self.output)
        self.setCentralWidget(root)
        self._refresh_revisions()

    def _scope(self):
        if self.context.dataset_id is None:
            raise RuntimeError("No imported dataset is available")
        revision_id = self.scope_combo.currentData()
        if revision_id is None:
            raise RuntimeError("Select a ready working-corpus revision before searching")
        return self.context.store.read(lambda conn: WorkingCorpusRepository(conn, self.context.logger).require_ready_scope(working_corpus_revision_id=int(revision_id), dataset_id=int(self.context.dataset_id)))

    def _service_read(self, callback):
        scope = self._scope()
        return self.context.store.read(lambda conn: callback(ClientWorkflowService(conn, self.context.logger, self.context.gateway), scope))

    def _run(self, operation, *, persist: bool = False) -> None:
        try:
            value = operation()
            self.output.setPlainText(json.dumps(value, ensure_ascii=False, indent=2, default=str))
        except Exception as exc:
            self.output.setPlainText(f"FAILED\n{exc}")
            QMessageBox.critical(self, "Operation failed", str(exc))

    def _refresh_revisions(self) -> None:
        selected = self.scope_combo.currentData()
        self.scope_combo.blockSignals(True)
        self.scope_combo.clear()
        self.scope_combo.addItem("Select a ready corpus revision…", None)
        try:
            if self.context.dataset_id is None:
                self.scope_label.setText("No imported dataset is available")
                return
            corpora = self.context.store.read(lambda conn: WorkingCorpusRepository(conn, self.context.logger).list_working_corpora(int(self.context.dataset_id)))
            for corpus in corpora:
                revisions = self.context.store.read(lambda conn, corpus_id=corpus.working_corpus_id: WorkingCorpusRepository(conn, self.context.logger).list_revisions(corpus_id))
                for revision in revisions:
                    label = f"{corpus.name} · revision {revision.revision_number} · {revision.status} · {revision.message_count:,} messages · {revision.estimated_tokens:,} tokens"
                    self.scope_combo.addItem(label, revision.working_corpus_revision_id if revision.status == "ready" else None)
            self.scope_label.setText("Select a ready corpus revision")
        except Exception as exc:
            self.scope_label.setText(f"Workspace unavailable: {exc}")
        finally:
            if selected is not None:
                for index in range(self.scope_combo.count()):
                    if self.scope_combo.itemData(index) == selected:
                        self.scope_combo.setCurrentIndex(index)
                        break
            self.scope_combo.blockSignals(False)
            self._on_scope_changed()

    def _on_scope_changed(self) -> None:
        if self.scope_combo.currentData() is None:
            self.scope_label.setText("Select a ready corpus revision")
            return
        try:
            scope = self._scope()
            self.scope_label.setText(f"Corpus {scope.working_corpus_id} · revision {scope.revision_number} · generation {scope.index_generation} · {scope.message_count:,} messages · {scope.estimated_tokens:,} tokens · scope {scope.scope_hash[:12]}")
        except Exception as exc:
            self.scope_label.setText(f"Selected revision unavailable: {exc}")

    def _clear_embeddings(self) -> None:
        if any(worker is not None and worker.isRunning() for worker in (self.embedding_worker, self.conversation_worker)):
            QMessageBox.warning(self, "Work is running", "Wait for the current operation before clearing embeddings.")
            return
        if QMessageBox.question(self, "Clear local embeddings", "Delete every local embedding artifact? Canonical data, revisions, lexical indexes, evidence, and conversations are preserved.") != QMessageBox.StandardButton.Yes:
            return
        try:
            result = clear_local_embeddings(self.context.store)
            self.output.setPlainText(json.dumps({"status": "cleared", "artifacts_deleted": result.artifacts_deleted, "revision_indexes_marked_missing": result.revision_indexes_marked_missing}, indent=2))
            self._on_scope_changed()
        except Exception as exc:
            self.output.setPlainText(f"FAILED\n{exc}")
            QMessageBox.critical(self, "Clear embeddings failed", str(exc))

    def _fts(self) -> None:
        self._run(lambda: self._service_read(lambda service, scope: service.fts5_search(NarrowedSearchScope(scope), self.query.text().strip())))

    def _keyword(self) -> None:
        def operation():
            scope = self._scope()
            return KeywordSearchWorkflow(self.context.store, self.context.logger, self.context.gateway).execute(NarrowedSearchScope(scope), self.query.text().strip())
        self._run(operation)

    def _embedding(self) -> None:
        def operation():
            scope = self._scope()
            return EmbeddingSearchWorkflow(self.context.store, self.context.logger, self.context.gateway).execute(NarrowedSearchScope(scope), self.query.text().strip())
        self._run(operation)

    def _conversation(self) -> None:
        if self.conversation_worker is not None and self.conversation_worker.isRunning():
            return
        try:
            scope = self._scope()
            query = self.query.text().strip()
            if not query:
                raise ValueError("Conversational search requires a question")
        except Exception as exc:
            self.output.setPlainText(f"FAILED\n{exc}")
            QMessageBox.critical(self, "Conversational search failed", str(exc))
            return
        self.conversation_started_at = time.monotonic()
        completed = 0
        total = 0
        self.conversation_progress_state = ConversationalSearchProgress(
            "analysis_plan", completed, total, "Requesting analysis plan"
        )
        self.conversation_progress_label.setVisible(True)
        self.conversation_progress_bar.setVisible(True)
        self.cancel_conversation_button.setVisible(True)
        self.cancel_conversation_button.setEnabled(True)
        self.cancel_conversation_button.setText("Cancel conversational search")
        for button in self.search_buttons:
            button.setEnabled(False)
        self.rebuild_button.setEnabled(False)
        self.query.setEnabled(False)
        worker = ConversationalSearchWorker(self.context, scope, query)
        self.conversation_worker = worker
        worker.progress.connect(self._on_conversation_progress)
        worker.succeeded.connect(self._on_conversation_succeeded)
        worker.failed.connect(self._on_conversation_failed)
        worker.cancelled.connect(self._on_conversation_cancelled)
        worker.finished.connect(self._on_conversation_finished)
        self.conversation_timer.start()
        self._refresh_conversation_progress_text()
        worker.start()

    def _cancel_conversation(self) -> None:
        worker = self.conversation_worker
        if worker is None or not worker.isRunning():
            return
        self.cancel_conversation_button.setEnabled(False)
        self.cancel_conversation_button.setText("Cancelling...")
        worker.cancel_request()
        previous = self.conversation_progress_state
        completed = previous.completed if previous is not None else 0
        total = previous.total if previous is not None else 0
        self.conversation_progress_state = ConversationalSearchProgress(
            "cancelling",
            completed,
            total,
            "Cancelling conversational search",
        )
        self._refresh_conversation_progress_text()

    def _on_conversation_progress(self, progress: object) -> None:
        if not isinstance(progress, ConversationalSearchProgress):
            return
        self.conversation_progress_state = progress
        if progress.total > 0:
            self.conversation_progress_bar.setRange(0, progress.total)
            self.conversation_progress_bar.setValue(progress.completed)
        else:
            self.conversation_progress_bar.setRange(0, 0)
        self._refresh_conversation_progress_text()

    def _refresh_conversation_progress_text(self) -> None:
        progress = self.conversation_progress_state
        if progress is None:
            return
        elapsed = max(0, int(time.monotonic() - self.conversation_started_at))
        count = (
            f" · {progress.completed:,}/{progress.total:,} windows"
            if progress.total > 0
            else ""
        )
        text = (
            f"[{progress.phase}] {progress.message}{count} · elapsed "
            f"{elapsed // 60:02d}:{elapsed % 60:02d}"
        )
        self.conversation_progress_label.setText(text)
        self.output.setPlainText(f"CONVERSATIONAL SEARCH\n{text}")

    def _on_conversation_succeeded(self, result: object) -> None:
        if not isinstance(result, ConversationalExecutionResult) or self.conversation_worker is None:
            self._on_conversation_failed("Conversational worker returned an invalid result")
            return
        display = dict(result.result)
        if result.persistence_warning:
            display["local_persistence_warning"] = result.persistence_warning
            QMessageBox.warning(self, "Answer not saved", result.persistence_warning)
        completion_status = str(display.get("completion_status", "complete"))
        status_line = {
            "complete": "COMPLETE: all planned evidence and synthesis validated.",
            "complete_with_warnings": "COMPLETE WITH WARNINGS: readable results returned with validation annotations.",
            "partial": "PARTIAL: some evidence or synthesis output was unavailable; retained results remain visible.",
        }.get(completion_status, f"UNKNOWN COMPLETION STATUS: {completion_status}")
        self.output.setPlainText(status_line + "\n\n" + format_conversational_result(display))

    def _on_conversation_failed(self, message: str) -> None:
        previous = self.conversation_progress_state
        completed = previous.completed if previous is not None else 0
        total = previous.total if previous is not None else 0
        elapsed = max(0, int(time.monotonic() - self.conversation_started_at))
        self.conversation_progress_state = ConversationalSearchProgress(
            "failed",
            completed,
            total,
            f"Failed: {message}",
        )
        if total > 0:
            self.conversation_progress_bar.setRange(0, total)
            self.conversation_progress_bar.setValue(completed)
        else:
            self.conversation_progress_bar.setRange(0, 1)
            self.conversation_progress_bar.setValue(0)
        self.conversation_progress_label.setText(
            f"FAILED after {completed:,}/{total:,} windows · elapsed "
            f"{elapsed // 60:02d}:{elapsed % 60:02d} · {message}"
        )
        self.output.setPlainText(f"FAILED\n{message}")
        QMessageBox.critical(self, "Conversational search failed", message)

    def _on_conversation_cancelled(self) -> None:
        previous = self.conversation_progress_state
        completed = previous.completed if previous is not None else 0
        total = previous.total if previous is not None else 0
        elapsed = max(0, int(time.monotonic() - self.conversation_started_at))
        self.conversation_progress_state = ConversationalSearchProgress(
            "cancelled",
            completed,
            total,
            "Conversational search cancelled",
        )
        self.conversation_progress_label.setText(
            f"CANCELLED after {completed:,}/{total:,} windows · elapsed "
            f"{elapsed // 60:02d}:{elapsed % 60:02d}"
        )
        self.output.setPlainText("CANCELLED\nConversational search cancelled by user.")

    def _on_conversation_finished(self) -> None:
        self.conversation_timer.stop()
        self.conversation_button.setEnabled(True)
        self.conversation_button.setText("Conversational")
        for button in self.search_buttons:
            button.setEnabled(True)
        self.conversation_button.setEnabled(True)
        self.rebuild_button.setEnabled(True)
        self.query.setEnabled(True)
        self.cancel_conversation_button.setVisible(False)
        self.cancel_conversation_button.setEnabled(False)
        if self.conversation_worker is not None:
            self.conversation_worker.deleteLater()
            self.conversation_worker = None

    def _build_embeddings(self) -> None:
        if self.embedding_worker is not None and self.embedding_worker.isRunning():
            return
        try:
            scope = self._scope()
        except Exception as exc:
            self.output.setPlainText(f"FAILED\n{exc}")
            QMessageBox.critical(self, "Embedding build failed", str(exc))
            return
        self.embedding_started_at = time.monotonic()
        self.embedding_progress_state = EmbeddingBuildProgress(
            "starting",
            0,
            scope.message_count,
            0,
            0,
            f"Starting: reading {scope.message_count:,} messages from the selected revision",
        )
        self.embedding_progress_label.setVisible(True)
        self.embedding_progress_bar.setVisible(True)
        self.embedding_progress_bar.setRange(0, 0)
        self.rebuild_button.setEnabled(False)
        self.rebuild_button.setText("Embedding build running...")
        for button in self.search_buttons:
            button.setEnabled(False)
        self.output.setPlainText("EMBEDDING BUILD\nStarting...")
        worker = EmbeddingBuildWorker(self.context, scope)
        self.embedding_worker = worker
        worker.progress.connect(self._on_embedding_progress)
        worker.succeeded.connect(self._on_embedding_succeeded)
        worker.failed.connect(self._on_embedding_failed)
        worker.finished.connect(self._on_embedding_finished)
        self.embedding_timer.start()
        self._refresh_embedding_progress_text()
        worker.start()

    def _on_embedding_progress(self, progress: object) -> None:
        if not isinstance(progress, EmbeddingBuildProgress):
            return
        self.embedding_progress_state = progress
        if progress.total > 0:
            self.embedding_progress_bar.setRange(0, progress.total)
            self.embedding_progress_bar.setValue(progress.completed)
        else:
            self.embedding_progress_bar.setRange(0, 0)
        self._refresh_embedding_progress_text()

    def _refresh_embedding_progress_text(self) -> None:
        progress = self.embedding_progress_state
        if progress is None:
            return
        elapsed = max(0, int(time.monotonic() - self.embedding_started_at))
        count = (
            f"{progress.completed:,}/{progress.total:,}"
            if progress.total > 0
            else "counting"
        )
        batch = (
            f" · batch {progress.batch_number:,}/{progress.batch_count:,}"
            if progress.batch_count > 0
            else ""
        )
        text = f"{progress.message} · {count}{batch} · elapsed {elapsed // 60:02d}:{elapsed % 60:02d}"
        self.embedding_progress_label.setText(text)
        self.output.setPlainText(f"EMBEDDING BUILD\n{text}")

    def _on_embedding_succeeded(self, result: object) -> None:
        if not isinstance(result, EmbeddingBuildResult):
            self._on_embedding_failed("Embedding worker returned an invalid result")
            return
        self.embedding_progress_state = EmbeddingBuildProgress(
            "completed",
            result.required_inputs,
            result.required_inputs,
            0,
            0,
            (
                f"Complete: {result.message_count:,} corpus messages covered by "
                f"{result.required_inputs:,} unique vectors "
                f"({result.reused_artifacts:,} reused, "
                f"{result.generated_artifacts:,} generated)"
            ),
        )
        self.embedding_progress_bar.setRange(0, max(1, result.required_inputs))
        self.embedding_progress_bar.setValue(result.required_inputs)
        self._refresh_embedding_progress_text()
        payload = {
            "status": "complete",
            "working_corpus_messages": result.message_count,
            "unique_vector_inputs": result.required_inputs,
            "reused_vectors": result.reused_artifacts,
            "generated_vectors": result.generated_artifacts,
            "dimensions": result.dimensions,
            "normalization": result.normalization,
        }
        self.output.setPlainText(json.dumps(payload, ensure_ascii=False, indent=2))

    def _on_embedding_failed(self, message: str) -> None:
        elapsed = max(0, int(time.monotonic() - self.embedding_started_at))
        self.embedding_progress_state = EmbeddingBuildProgress(
            "failed", 0, 1, 0, 0, f"Failed: {message}"
        )
        self.embedding_progress_bar.setRange(0, 1)
        self.embedding_progress_bar.setValue(0)
        self.embedding_progress_label.setText(
            f"Failed · elapsed {elapsed // 60:02d}:{elapsed % 60:02d} · {message}"
        )
        self.output.setPlainText(f"FAILED\n{message}")
        QMessageBox.critical(self, "Embedding build failed", message)

    def _on_embedding_finished(self) -> None:
        self.embedding_timer.stop()
        self.rebuild_button.setEnabled(True)
        self.rebuild_button.setText("Build / refresh local embeddings")
        for button in self.search_buttons:
            button.setEnabled(True)
        if self.embedding_worker is not None:
            self.embedding_worker.deleteLater()
            self.embedding_worker = None

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self.embedding_worker is not None and self.embedding_worker.isRunning():
            QMessageBox.warning(
                self,
                "Embedding build is running",
                "Wait for the current embedding batch and build to finish before closing the client.",
            )
            event.ignore()
            return
        if self.conversation_worker is not None and self.conversation_worker.isRunning():
            QMessageBox.warning(
                self,
                "Conversational search is running",
                "Wait for the current model request to finish before closing the client.",
            )
            event.ignore()
            return
        try:
            self.context.store.close()
        except Exception as exc:
            QMessageBox.critical(self, "Workspace close failed", str(exc))
            event.ignore()
            return
        event.accept()
