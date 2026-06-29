"""Persistent Home tab and dataset load UI."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from message_evidence_workstation.config.settings import load_settings
from message_evidence_workstation.dataset_load_pipeline import (
    DatasetLoadRequest,
    DatasetLoadResult,
    PipelineCancelToken,
    run_import_pipeline,
)
from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.ui.background_tasks import run_background
from message_evidence_workstation.ui.embedding_worker import EmbeddingJobSpec, preload_embedding_model, run_embedding_job


class HomeTab(QWidget):
    dataset_imported = Signal(object)
    load_completed = Signal(object)
    load_failed = Signal(object)
    embeddings_ready = Signal(object)
    status_line = Signal(str)

    def __init__(
        self,
        conn,
        logger: ProcessLogger,
        *,
        db_path: Path,
        initial_dataset_path: Path | None = None,
        reload_dataset: bool = False,
        skip_embedding_on_load: bool = False,
        auto_run_on_show: bool = False,
    ) -> None:
        super().__init__()
        self.conn = conn
        self.logger = logger
        self.db_path = db_path
        self._selected_path = initial_dataset_path
        self._reload_dataset = reload_dataset
        self._skip_embedding_on_load = skip_embedding_on_load
        self._cancel_token = PipelineCancelToken()
        self._worker_thread = None
        self._phase = "idle"
        self._pending_dataset_id: int | None = None
        self._auto_run_pending = auto_run_on_show
        self._dataset_loaded_this_session = False
        self._preload_started = False

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Welcome to Message Evidence Workstation. "
                "Choose a normalized donor dataset folder, then click Load Dataset. "
                "Configure API keys on Setup / Settings first if needed."
            )
        )

        path_row = QHBoxLayout()
        self.path_label = QLabel(self._format_path_label())
        path_row.addWidget(self.path_label, stretch=1)
        self.browse_button = QPushButton("Choose folder…")
        self.browse_button.clicked.connect(self._choose_folder)
        path_row.addWidget(self.browse_button)
        layout.addLayout(path_row)

        button_row = QHBoxLayout()
        self.load_button = QPushButton("Load dataset")
        self.load_button.clicked.connect(self._start_load)
        button_row.addWidget(self.load_button)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel_pipeline)
        button_row.addWidget(self.cancel_button)

        self.skip_embedding_button = QPushButton("Skip embedding")
        self.skip_embedding_button.setEnabled(False)
        self.skip_embedding_button.clicked.connect(self._skip_embedding)
        button_row.addWidget(self.skip_embedding_button)

        self.retry_embedding_button = QPushButton("Retry embedding")
        self.retry_embedding_button.setEnabled(False)
        self.retry_embedding_button.clicked.connect(self._retry_embedding)
        button_row.addWidget(self.retry_embedding_button)
        button_row.addStretch()
        layout.addLayout(button_row)

        self.status_log = QTextEdit()
        self.status_log.setReadOnly(True)
        layout.addWidget(self.status_log)

        self._append_status("Ready. Choose a dataset folder and click Load dataset.")
        self.status_line.connect(self._append_status)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._preload_started:
            self._preload_started = True
            self._start_embedding_preload()
        if self._auto_run_pending:
            self._auto_run_pending = False
            self._start_load()

    def _start_embedding_preload(self) -> None:
        preload_embedding_model(
            self,
            db_path=self.db_path,
            on_success=lambda _result: self._append_status("Embedding model preload complete."),
            on_error=lambda exc: self._append_status(f"Embedding model preload failed: {exc}"),
        )

    def _format_path_label(self) -> str:
        if self._selected_path is None:
            return "No dataset folder selected."
        return f"Dataset folder: {self._selected_path}"

    def _append_status(self, message: str) -> None:
        self.status_log.append(message)
        scrollbar = self.status_log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _ui_narrator(self):
        def narrate(line: str) -> None:
            self.status_line.emit(line)

        return narrate

    def _run_import_on_worker(self, request: DatasetLoadRequest) -> DatasetLoadResult:
        worker_conn = connect(self.db_path)
        try:
            worker_logger = ProcessLogger(worker_conn, log_bus=self.logger.log_bus)
            return run_import_pipeline(
                worker_conn,
                worker_logger,
                request,
                narrator=self._ui_narrator(),
                cancel_check=self._cancel_token.is_cancelled,
            )
        finally:
            worker_conn.close()

    def _set_busy(self, busy: bool, *, phase: str = "idle") -> None:
        self._phase = phase
        can_load = not busy and not self._dataset_loaded_this_session
        self.load_button.setEnabled(can_load)
        self.browse_button.setEnabled(not busy)
        self.cancel_button.setEnabled(busy and phase in {"import", "embedding"})
        self.skip_embedding_button.setEnabled(busy and phase == "embedding")
        self.retry_embedding_button.setEnabled(not busy and self._pending_dataset_id is not None)

    def _choose_folder(self) -> None:
        start_dir = str(self._selected_path) if self._selected_path else ""
        chosen = QFileDialog.getExistingDirectory(self, "Select normalized dataset folder", start_dir)
        if not chosen:
            return
        self._selected_path = Path(chosen)
        self.path_label.setText(self._format_path_label())

    def _build_request(self, *, skip_embedding: bool = False, reload: bool | None = None) -> DatasetLoadRequest:
        if self._selected_path is None:
            raise ValueError("Select a dataset folder before loading.")
        return DatasetLoadRequest(
            dataset_path=self._selected_path,
            reload=self._reload_dataset if reload is None else reload,
            skip_import_if_existing=reload is not True,
            run_embedding=not skip_embedding,
            skip_embedding=skip_embedding,
        )

    def _start_load(self) -> None:
        if self._dataset_loaded_this_session:
            self._append_status("Dataset already loaded this session.")
            return
        if self._selected_path is None:
            self._append_status("Select a dataset folder before loading.")
            return
        self._cancel_token.reset()
        self._pending_dataset_id = None
        self.retry_embedding_button.setEnabled(False)
        self._set_busy(True, phase="import")
        self._append_status("Starting dataset import…")

        request = self._build_request(skip_embedding=self._skip_embedding_on_load)

        def work() -> DatasetLoadResult:
            return self._run_import_on_worker(request)

        def on_success(result: DatasetLoadResult) -> None:
            if not result.import_succeeded or result.dataset_id is None:
                self._on_pipeline_finished(result)
                return
            self._pending_dataset_id = result.dataset_id
            self.logger.dataset_id = result.dataset_id
            import_only = DatasetLoadResult(
                success=True,
                dataset_id=result.dataset_id,
                import_succeeded=True,
                embedding_available=False,
                narration=result.narration,
            )
            self.dataset_imported.emit(import_only)
            if request.skip_embedding or not request.run_embedding:
                self._on_pipeline_finished(import_only, handoff=True)
                return
            self._run_embedding_phase(result)

        def on_error(exc: BaseException) -> None:
            self._set_busy(False)
            self._append_status(f"Unexpected pipeline error: {exc}")
            self.load_failed.emit(DatasetLoadResult(success=False, error=str(exc), narration=[]))

        self._worker_thread = run_background(self, work, on_success=on_success, on_error=on_error)

    def _embedding_indexes_ready(self, dataset_id: int) -> bool:
        from message_evidence_workstation.embeddings.index_jobs import get_ready_index

        model_id = load_settings().embedding_model
        message_row = get_ready_index(self.conn, dataset_id, "message", model_id)
        chunk_row = get_ready_index(self.conn, dataset_id, "chunk", model_id)
        return message_row is not None and chunk_row is not None

    def _run_embedding_phase(self, import_result: DatasetLoadResult) -> None:
        assert import_result.dataset_id is not None
        dataset_id = import_result.dataset_id
        if self._embedding_indexes_ready(dataset_id):
            self._append_status("Reusing cached embeddings for the active model.")
            ready = DatasetLoadResult(
                success=True,
                dataset_id=dataset_id,
                import_succeeded=True,
                embedding_available=True,
                narration=[*import_result.narration, "Cached embeddings reused."],
            )
            self.embeddings_ready.emit(ready)
            self._on_pipeline_finished(ready, handoff=True)
            return

        self._set_busy(True, phase="embedding")
        self._append_status("Starting background embedding…")
        self._queue_message_embedding(dataset_id, import_result)

    def _queue_message_embedding(self, dataset_id: int, import_result: DatasetLoadResult) -> None:
        from message_evidence_workstation.embeddings.model_registry import get_model_spec

        model_id = load_settings().embedding_model
        spec = get_model_spec(model_id)
        if spec is None:
            self._append_status(f"Unknown embedding model: {model_id}")
            self._on_pipeline_finished(
                DatasetLoadResult(
                    success=True,
                    dataset_id=dataset_id,
                    import_succeeded=True,
                    embedding_available=False,
                    embedding_error=f"Unknown embedding model: {model_id}",
                    narration=import_result.narration,
                ),
                handoff=True,
            )
            return

        job = EmbeddingJobSpec(
            job_type="message_index",
            db_path=self.db_path,
            dataset_id=dataset_id,
            adapter_key=spec.adapter_key,
            model_id=spec.model_id,
        )

        def on_success(_result: object) -> None:
            if self._cancel_token.is_cancelled():
                self._finish_embedding(dataset_id, import_result, available=False, error="Cancelled")
                return
            self._queue_chunk_embedding(dataset_id, import_result, spec)

        def on_error(exc: BaseException) -> None:
            self._finish_embedding(dataset_id, import_result, available=False, error=str(exc))

        run_embedding_job(self, job, on_success=on_success, on_error=on_error)

    def _queue_chunk_embedding(self, dataset_id: int, import_result: DatasetLoadResult, spec) -> None:
        settings = load_settings()
        chunking_config = {
            "max_chars": int(settings.chunking.get("max_chars", 1200)),
            "desired_average_chunk_messages": int(
                settings.chunking.get("desired_average_chunk_messages", 8)
            ),
            "session_gap_hours": float(settings.chunking.get("session_gap_hours", 4)),
            "use_semantic_boundaries": bool(settings.chunking.get("use_semantic_boundaries", True)),
            "split_on_date_change": bool(settings.chunking.get("split_on_date_change", True)),
        }
        job = EmbeddingJobSpec(
            job_type="chunk_index",
            db_path=self.db_path,
            dataset_id=dataset_id,
            adapter_key=spec.adapter_key,
            model_id=spec.model_id,
            chunking_config=chunking_config,
        )

        def on_success(_result: object) -> None:
            self._finish_embedding(dataset_id, import_result, available=True, error=None)

        def on_error(exc: BaseException) -> None:
            self._finish_embedding(dataset_id, import_result, available=False, error=str(exc))

        run_embedding_job(self, job, on_success=on_success, on_error=on_error)

    def _finish_embedding(
        self,
        dataset_id: int,
        import_result: DatasetLoadResult,
        *,
        available: bool,
        error: str | None,
    ) -> None:
        result = DatasetLoadResult(
            success=True,
            dataset_id=dataset_id,
            import_succeeded=True,
            embedding_available=available,
            embedding_error=error,
            narration=[*import_result.narration],
        )
        if available:
            self.embeddings_ready.emit(result)
        self._on_pipeline_finished(result, handoff=True)

    def _cancel_pipeline(self) -> None:
        self._cancel_token.cancel()
        self._append_status("Cancel requested…")

    def _skip_embedding(self) -> None:
        if self._phase != "embedding":
            return
        self._cancel_token.cancel()
        self._append_status("Skipping embedding phase…")
        if self._pending_dataset_id is None:
            return
        result = DatasetLoadResult(
            success=True,
            dataset_id=self._pending_dataset_id,
            import_succeeded=True,
            embedding_available=False,
            embedding_error="skipped by user",
        )
        self._on_pipeline_finished(result, handoff=True)

    def _retry_embedding(self) -> None:
        if self._pending_dataset_id is None:
            return
        self._cancel_token.reset()
        import_result = DatasetLoadResult(
            success=True,
            dataset_id=self._pending_dataset_id,
            import_succeeded=True,
            narration=[],
        )
        self._run_embedding_phase(import_result)

    def _on_pipeline_finished(self, result: DatasetLoadResult, *, handoff: bool = False) -> None:
        if result.import_succeeded and result.dataset_id is not None:
            self._dataset_loaded_this_session = True
        self._set_busy(False)
        if result.dataset_id is not None:
            self._pending_dataset_id = result.dataset_id
            self.logger.dataset_id = result.dataset_id

        if not result.import_succeeded or result.dataset_id is None:
            self.retry_embedding_button.setEnabled(False)
            self._append_status(result.error or "Dataset load failed. Fix the dataset and retry.")
            self.load_failed.emit(result)
            return

        if result.embedding_error and not result.embedding_available:
            self.retry_embedding_button.setEnabled(True)
            self._append_status(
                "Dataset loaded; embedding features are unavailable until you retry or rebuild in Settings."
            )
        elif not result.embedding_available:
            self._append_status("Dataset loaded; embedding was skipped.")

        if handoff or result.success:
            self.load_completed.emit(result)

    def run_import_only(self, *, reload: bool = False, skip_embedding: bool = True) -> None:
        request = self._build_request(skip_embedding=skip_embedding, reload=reload)
        result = run_import_pipeline(
            self.conn,
            self.logger,
            request,
            narrator=self._ui_narrator(),
        )
        self._on_pipeline_finished(result, handoff=True)


# Backward compatibility for tests and legacy imports.
LoadDatasetTab = HomeTab
