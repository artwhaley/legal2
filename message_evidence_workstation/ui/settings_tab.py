"""Settings tab with verbose process log viewer."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from message_evidence_workstation.config.settings import AppSettings, load_settings, save_settings
from message_evidence_workstation.domain.constants import (
    SEVERITY_DEBUG,
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARNING,
)
from message_evidence_workstation.logging_ui.log_bus import LogBus
from message_evidence_workstation.logging_ui.process_log import ProcessLogger, fetch_process_logs
from message_evidence_workstation.nim.client import NimClient, NimClientError, nim_error_user_message


class SettingsTab(QWidget):
    def __init__(
        self,
        conn: sqlite3.Connection,
        logger: ProcessLogger,
        log_bus: LogBus,
        *,
        dataset_id: int | None = None,
        db_path: Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.conn = conn
        self.logger = logger
        self.log_bus = log_bus
        self.dataset_id = dataset_id
        from message_evidence_workstation.config.paths import default_db_path

        self.db_path = db_path or default_db_path()
        self._entries: list[dict[str, Any]] = []
        self._model_runs: list = []
        self.settings = load_settings()

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Setup / Settings"))

        nim_group = QGroupBox("NVIDIA NIM")
        nim_form = QFormLayout(nim_group)
        self.nim_base_url = QLineEdit(self.settings.nim.api_base_url)
        nim_form.addRow("API base URL", self.nim_base_url)
        self.nim_api_key = QLineEdit(self.settings.nim.api_key)
        self.nim_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.nim_api_key.setPlaceholderText("Use MEW_NIM_API_KEY env var or enter key")
        nim_form.addRow("API key", self.nim_api_key)
        self.nim_model = QComboBox()
        self.nim_model.setEditable(True)
        self.nim_model.setEditText(self.settings.nim.model)
        self.nim_model.activated.connect(lambda _index: self._persist_nim_model_selection())
        nim_form.addRow("Model", self.nim_model)
        self.nim_temperature = QDoubleSpinBox()
        self.nim_temperature.setRange(0.0, 2.0)
        self.nim_temperature.setSingleStep(0.1)
        self.nim_temperature.setValue(self.settings.nim.temperature)
        nim_form.addRow("Temperature", self.nim_temperature)
        self.nim_max_tokens = QSpinBox()
        self.nim_max_tokens.setRange(1, 32768)
        self.nim_max_tokens.setValue(self.settings.nim.max_output_tokens)
        nim_form.addRow("Max output tokens", self.nim_max_tokens)
        self.nim_timeout = QDoubleSpinBox()
        self.nim_timeout.setRange(1.0, 600.0)
        self.nim_timeout.setValue(self.settings.nim.timeout_seconds)
        self.nim_timeout.setToolTip("NIM chat completion wait time. Increase if calls time out.")
        self.nim_timeout.valueChanged.connect(self._persist_nim_timeout)
        nim_form.addRow("Timeout (s)", self.nim_timeout)
        self.nim_streaming = QCheckBox("Streaming enabled")
        self.nim_streaming.setChecked(self.settings.nim.streaming)
        nim_form.addRow("", self.nim_streaming)
        nim_buttons = QHBoxLayout()
        self.refresh_models_button = QPushButton("Refresh model list")
        self.refresh_models_button.clicked.connect(self._refresh_models)
        nim_buttons.addWidget(self.refresh_models_button)
        self.save_nim_button = QPushButton("Save NIM settings")
        self.save_nim_button.clicked.connect(self._save_nim_settings)
        nim_buttons.addWidget(self.save_nim_button)
        nim_form.addRow("", nim_buttons)
        layout.addWidget(nim_group)

        answer_group = QGroupBox("Conversational answer strategy")
        answer_form = QFormLayout(answer_group)
        self.answer_strategy = QComboBox()
        for label, value in (
            ("Auto (whole transcript if it fits, else exhaustive window scan)", "auto"),
            ("Whole transcript", "whole_transcript"),
            ("Exhaustive window scan (inspect every session)", "exhaustive_window_scan"),
            ("Session summary triage (faster, lower recall)", "session_coverage"),
            ("Retrieval fallback / debug (lower recall)", "retrieval_fallback"),
        ):
            self.answer_strategy.addItem(label, value)
        strategy_index = self.answer_strategy.findData(self.settings.answer.answer_strategy)
        if strategy_index >= 0:
            self.answer_strategy.setCurrentIndex(strategy_index)
        answer_form.addRow("Answer strategy", self.answer_strategy)
        self.whole_transcript_max_chars = QSpinBox()
        self.whole_transcript_max_chars.setRange(10_000, 2_000_000)
        self.whole_transcript_max_chars.setSingleStep(10_000)
        self.whole_transcript_max_chars.setValue(self.settings.answer.whole_transcript_max_chars)
        answer_form.addRow("Whole transcript max chars", self.whole_transcript_max_chars)
        self.answer_session_gap_minutes = QSpinBox()
        self.answer_session_gap_minutes.setRange(15, 24 * 60)
        self.answer_session_gap_minutes.setValue(self.settings.answer.session_gap_minutes)
        answer_form.addRow("Session gap (minutes)", self.answer_session_gap_minutes)
        self.max_inspected_sessions = QSpinBox()
        self.max_inspected_sessions.setRange(1, 100)
        self.max_inspected_sessions.setValue(self.settings.answer.max_inspected_sessions)
        answer_form.addRow("Max inspected sessions", self.max_inspected_sessions)
        self.transcript_window_padding = QSpinBox()
        self.transcript_window_padding.setRange(0, 20)
        self.transcript_window_padding.setValue(self.settings.answer.transcript_window_padding)
        answer_form.addRow("Transcript window padding", self.transcript_window_padding)
        self.context_window_override_tokens = QSpinBox()
        self.context_window_override_tokens.setRange(0, 2_000_000)
        self.context_window_override_tokens.setSingleStep(1024)
        self.context_window_override_tokens.setValue(self.settings.answer.context_window_override_tokens)
        answer_form.addRow("Context window override tokens", self.context_window_override_tokens)
        self.context_safety_ratio = QDoubleSpinBox()
        self.context_safety_ratio.setRange(0.25, 0.90)
        self.context_safety_ratio.setSingleStep(0.05)
        self.context_safety_ratio.setValue(self.settings.answer.context_safety_ratio)
        answer_form.addRow("Context safety ratio", self.context_safety_ratio)
        self.reserved_output_tokens = QSpinBox()
        self.reserved_output_tokens.setRange(256, 32768)
        self.reserved_output_tokens.setValue(self.settings.answer.reserved_output_tokens)
        answer_form.addRow("Reserved output tokens", self.reserved_output_tokens)
        self.prompt_overhead_tokens = QSpinBox()
        self.prompt_overhead_tokens.setRange(0, 20000)
        self.prompt_overhead_tokens.setValue(self.settings.answer.prompt_overhead_tokens)
        answer_form.addRow("Prompt overhead tokens", self.prompt_overhead_tokens)
        self.window_target_tokens = QSpinBox()
        self.window_target_tokens.setRange(500, 200000)
        self.window_target_tokens.setSingleStep(500)
        self.window_target_tokens.setValue(self.settings.answer.window_target_tokens)
        answer_form.addRow("Exhaustive window target tokens", self.window_target_tokens)
        self.window_overlap_messages = QSpinBox()
        self.window_overlap_messages.setRange(0, 20)
        self.window_overlap_messages.setValue(self.settings.answer.window_overlap_messages)
        answer_form.addRow("Exhaustive window overlap messages", self.window_overlap_messages)
        self.context_budget_readout = QLabel()
        self.context_budget_readout.setWordWrap(True)
        answer_form.addRow("Context budget readout", self.context_budget_readout)
        for widget in (
            self.answer_strategy,
            self.context_window_override_tokens,
            self.context_safety_ratio,
            self.reserved_output_tokens,
            self.prompt_overhead_tokens,
            self.window_target_tokens,
            self.window_overlap_messages,
            self.nim_model,
        ):
            if isinstance(widget, QComboBox):
                widget.currentIndexChanged.connect(self.refresh_context_budget_readout)
            else:
                widget.valueChanged.connect(self.refresh_context_budget_readout)
        answer_buttons = QHBoxLayout()
        self.save_answer_settings_button = QPushButton("Save answer settings")
        self.save_answer_settings_button.clicked.connect(self._save_answer_settings)
        answer_buttons.addWidget(self.save_answer_settings_button)
        self.rebuild_sessions_button = QPushButton("Rebuild transcript sessions")
        self.rebuild_sessions_button.clicked.connect(self._rebuild_transcript_sessions)
        answer_buttons.addWidget(self.rebuild_sessions_button)
        answer_form.addRow("", answer_buttons)
        layout.addWidget(answer_group)
        self.refresh_context_budget_readout()

        prompt_group = QGroupBox("Prompt templates")
        prompt_layout = QVBoxLayout(prompt_group)
        prompt_row = QHBoxLayout()
        self.prompt_type = QComboBox()
        for run_type in (
            "keyword_expansion",
            "conversational_search_planner",
            "conversational_search_synthesis",
            "evidence_range_suggestion",
            "whole_transcript_answer",
            "coverage_session_answer",
            "coverage_audit",
            "session_summary",
            "session_classification",
            "exhaustive_window_scan",
            "exhaustive_window_merge",
        ):
            self.prompt_type.addItem(run_type, run_type)
        self.prompt_type.currentIndexChanged.connect(self._load_selected_prompt)
        prompt_row.addWidget(QLabel("Run type"))
        prompt_row.addWidget(self.prompt_type)
        prompt_layout.addLayout(prompt_row)
        from PySide6.QtWidgets import QTextEdit

        self.prompt_body = QTextEdit()
        prompt_layout.addWidget(self.prompt_body)
        self.save_prompt_button = QPushButton("Save prompt version")
        self.save_prompt_button.clicked.connect(self._save_prompt)
        prompt_layout.addWidget(self.save_prompt_button)
        layout.addWidget(prompt_group)

        embedding_group = QGroupBox("Embedding model")
        embedding_form = QFormLayout(embedding_group)
        self.embedding_model = QComboBox()
        from message_evidence_workstation.embeddings.model_registry import EMBEDDING_MODELS

        for spec in EMBEDDING_MODELS:
            self.embedding_model.addItem(spec.label, spec.model_id)
        current_index = self.embedding_model.findData(self.settings.embedding_model)
        self.embedding_model.blockSignals(True)
        if current_index >= 0:
            self.embedding_model.setCurrentIndex(current_index)
        self.embedding_model.blockSignals(False)
        self.embedding_model.currentIndexChanged.connect(self._on_embedding_model_changed)
        embedding_form.addRow("Model", self.embedding_model)
        self.embedding_status = QLabel("Starting up…")
        embedding_form.addRow("Status", self.embedding_status)
        chunking_group = QGroupBox("Semantic chunking")
        chunking_form = QFormLayout(chunking_group)
        from message_evidence_workstation.embeddings.chunking import (
            DEFAULT_MAX_CHARS,
            DEFAULT_SEMANTIC_SIMILARITY_THRESHOLD,
            DEFAULT_SESSION_GAP_HOURS,
        )

        chunking_settings = self.settings.chunking or {}
        self.chunk_similarity_threshold = QDoubleSpinBox()
        self.chunk_similarity_threshold.setRange(0.0, 1.0)
        self.chunk_similarity_threshold.setDecimals(2)
        self.chunk_similarity_threshold.setSingleStep(0.05)
        self.chunk_similarity_threshold.setValue(
            float(chunking_settings.get("semantic_similarity_threshold", DEFAULT_SEMANTIC_SIMILARITY_THRESHOLD))
        )
        self.chunk_similarity_threshold.setToolTip(
            "Start a new chronological chunk when the next message is below this cosine similarity."
        )
        self.chunk_similarity_threshold.valueChanged.connect(self._on_chunking_controls_changed)
        chunking_form.addRow("Semantic similarity threshold", self.chunk_similarity_threshold)

        self.chunk_session_gap_hours = QDoubleSpinBox()
        self.chunk_session_gap_hours.setRange(0.25, 168.0)
        self.chunk_session_gap_hours.setDecimals(2)
        self.chunk_session_gap_hours.setSingleStep(0.5)
        self.chunk_session_gap_hours.setSuffix(" h")
        self.chunk_session_gap_hours.setValue(
            float(chunking_settings.get("session_gap_hours", DEFAULT_SESSION_GAP_HOURS))
        )
        self.chunk_session_gap_hours.setToolTip(
            "Start a new chunk after this much silence; day changes also start a new chunk."
        )
        self.chunk_session_gap_hours.valueChanged.connect(self._on_chunking_controls_changed)
        chunking_form.addRow("Day/session gap", self.chunk_session_gap_hours)

        self.chunk_max_chars = QSpinBox()
        self.chunk_max_chars.setRange(100, 5000)
        self.chunk_max_chars.setSingleStep(50)
        self.chunk_max_chars.setValue(int(chunking_settings.get("max_chars", DEFAULT_MAX_CHARS)))
        self.chunk_max_chars.setToolTip("Maximum normalized text characters per chunk.")
        self.chunk_max_chars.valueChanged.connect(self._on_chunking_controls_changed)
        chunking_form.addRow("Maximum chunk size", self.chunk_max_chars)

        self.chunk_preview_label = QLabel("Chunk preview unavailable until a dataset is loaded.")
        self.chunk_preview_label.setWordWrap(True)
        chunking_form.addRow("Live preview", self.chunk_preview_label)
        layout.addWidget(chunking_group)

        embedding_buttons = QHBoxLayout()
        self.load_embedding_button = QPushButton("Reload embedding model")
        self.load_embedding_button.clicked.connect(self._load_embedding_model)
        embedding_buttons.addWidget(self.load_embedding_button)
        self.validate_sqlite_vec_button = QPushButton("Validate sqlite-vec")
        self.validate_sqlite_vec_button.clicked.connect(self._validate_sqlite_vec)
        embedding_buttons.addWidget(self.validate_sqlite_vec_button)
        self.build_message_index_button = QPushButton("Build message embeddings")
        self.build_message_index_button.clicked.connect(self._build_message_index)
        self.build_message_index_button.setEnabled(False)
        embedding_buttons.addWidget(self.build_message_index_button)
        self.restart_message_index_button = QPushButton("Restart message build")
        self.restart_message_index_button.clicked.connect(self._restart_message_index)
        self.restart_message_index_button.setEnabled(False)
        embedding_buttons.addWidget(self.restart_message_index_button)
        self.build_chunk_index_button = QPushButton("Build chunk embeddings")
        self.build_chunk_index_button.clicked.connect(self._build_chunk_index)
        self.build_chunk_index_button.setEnabled(False)
        embedding_buttons.addWidget(self.build_chunk_index_button)
        self.restart_chunk_index_button = QPushButton("Restart chunk build")
        self.restart_chunk_index_button.clicked.connect(self._restart_chunk_index)
        self.restart_chunk_index_button.setEnabled(False)
        embedding_buttons.addWidget(self.restart_chunk_index_button)
        embedding_form.addRow("", embedding_buttons)
        layout.addWidget(embedding_group)

        audit_group = QGroupBox("Audit export and ModelRun viewer")
        audit_layout = QVBoxLayout(audit_group)
        audit_buttons = QHBoxLayout()
        self.export_log_json_button = QPushButton("Export process log (JSON)")
        self.export_log_json_button.clicked.connect(self._export_process_log_json)
        audit_buttons.addWidget(self.export_log_json_button)
        self.export_log_text_button = QPushButton("Export process log (text)")
        self.export_log_text_button.clicked.connect(self._export_process_log_text)
        audit_buttons.addWidget(self.export_log_text_button)
        self.export_audit_bundle_button = QPushButton("Export audit bundle…")
        self.export_audit_bundle_button.clicked.connect(self._export_audit_bundle)
        audit_buttons.addWidget(self.export_audit_bundle_button)
        audit_buttons.addStretch()
        audit_layout.addLayout(audit_buttons)
        audit_layout.addWidget(QLabel("ModelRun records"))
        self.model_run_list = QListWidget()
        self.model_run_list.currentRowChanged.connect(self._on_model_run_selected)
        audit_layout.addWidget(self.model_run_list)
        from PySide6.QtWidgets import QTextEdit

        self.model_run_detail = QTextEdit()
        self.model_run_detail.setReadOnly(True)
        audit_layout.addWidget(self.model_run_detail)
        layout.addWidget(audit_group)

        layout.addWidget(QLabel("Verbose process log (live + persisted)"))

        controls = QHBoxLayout()
        self.severity_filter = QComboBox()
        self.severity_filter.addItem("All severities", "")
        for severity in (SEVERITY_DEBUG, SEVERITY_INFO, SEVERITY_WARNING, SEVERITY_ERROR):
            self.severity_filter.addItem(severity, severity)
        self.severity_filter.currentIndexChanged.connect(self.refresh_persisted_logs)
        controls.addWidget(QLabel("Severity:"))
        controls.addWidget(self.severity_filter)

        self.test_log_button = QPushButton("Emit test logs")
        self.test_log_button.clicked.connect(self._emit_test_logs)
        controls.addWidget(self.test_log_button)

        self.clear_view_button = QPushButton("Clear visible log")
        self.clear_view_button.clicked.connect(self._clear_visible_log)
        controls.addWidget(self.clear_view_button)

        self.refresh_button = QPushButton("Reload persisted logs")
        self.refresh_button.clicked.connect(self.refresh_persisted_logs)
        controls.addWidget(self.refresh_button)
        controls.addStretch()
        layout.addLayout(controls)

        self.log_list = QListWidget()
        self.log_list.setWordWrap(True)
        layout.addWidget(self.log_list)

        self.log_bus.entry_added.connect(
            self._on_live_entry,
            Qt.ConnectionType.QueuedConnection,
        )
        self._load_selected_prompt()
        self.refresh_persisted_logs()
        self.refresh_model_runs()
        self._chunk_preview_timer = QTimer(self)
        self._chunk_preview_timer.setSingleShot(True)
        self._chunk_preview_timer.timeout.connect(self._update_chunk_preview)
        self.start_embedding_model_preload()
        self._update_chunk_preview()

    _MAX_LIVE_LOG_ENTRIES = 500
    _LIVE_LOG_STATUS_ONLY = frozenset(
        {
            "message_batch_progress",
            "chunk_batch_progress",
            "chunk_index_count_start",
        }
    )
    _embedding_model_ready = False

    def start_embedding_model_preload(self) -> None:
        from message_evidence_workstation.ui.embedding_worker import preload_embedding_model

        self.load_embedding_button.setEnabled(False)
        self.embedding_status.setText("Loading embedding model at startup…")
        self.logger.info(
            component="ui.settings_tab",
            operation="embedding_model_preload_requested",
            message="Preloading embedding model on app startup",
            dataset_id=self.dataset_id,
        )
        started = preload_embedding_model(
            self,
            db_path=self.db_path,
            dataset_id=self.dataset_id,
            on_success=self._on_embedding_model_ready,
            on_error=self._on_embedding_model_preload_failed,
        )
        if not started:
            self.load_embedding_button.setEnabled(True)
            self.embedding_status.setText("Unknown embedding model selection.")

    def _on_embedding_model_ready(self, result: object) -> None:
        load = result  # type: ignore[assignment]
        self._embedding_model_ready = True
        self.load_embedding_button.setEnabled(True)
        self.build_message_index_button.setEnabled(self.dataset_id is not None)
        self.restart_message_index_button.setEnabled(self.dataset_id is not None)
        self.build_chunk_index_button.setEnabled(self.dataset_id is not None)
        self.restart_chunk_index_button.setEnabled(self.dataset_id is not None)
        self.embedding_status.setText(
            f"Ready: {load.model_name} ({load.dimensions} dims, {load.normalization_mode})"
        )
        self._update_chunk_preview()

    def _on_embedding_model_preload_failed(self, exc: BaseException) -> None:
        self._embedding_model_ready = False
        self.load_embedding_button.setEnabled(True)
        self.embedding_status.setText(f"Model load failed: {exc} — click Reload to retry")
        self.logger.error(
            component="ui.settings_tab",
            operation="embedding_model_preload_failed",
            message=str(exc),
            exc=exc,
            dataset_id=self.dataset_id,
        )

    def _format_entry(self, entry: dict[str, Any]) -> str:
        parts = [
            f"[{entry['timestamp']}]",
            entry["severity"].upper(),
            f"{entry['component']}::{entry['operation']}",
            entry["message"],
        ]
        if entry.get("operation_id"):
            parts.append(f"(op={entry['operation_id']})")
        if entry.get("exception_type"):
            parts.append(f"EXCEPTION={entry['exception_type']}")
        if entry.get("stack_trace"):
            parts.append(entry["stack_trace"].strip())
        if entry.get("details_json"):
            parts.append(json.dumps(entry["details_json"], ensure_ascii=True))
        return " | ".join(parts)

    def _append_entry(self, entry: dict[str, Any]) -> None:
        self._entries.append(entry)
        if len(self._entries) > self._MAX_LIVE_LOG_ENTRIES:
            overflow = len(self._entries) - self._MAX_LIVE_LOG_ENTRIES
            del self._entries[:overflow]
            for _ in range(overflow):
                item = self.log_list.takeItem(0)
                if item is not None:
                    del item
        item = QListWidgetItem(self._format_entry(entry))
        if entry.get("severity") == SEVERITY_ERROR:
            item.setForeground(Qt.GlobalColor.red)
        elif entry.get("severity") == SEVERITY_WARNING:
            item.setForeground(Qt.GlobalColor.darkYellow)
        self.log_list.addItem(item)
        self.log_list.scrollToBottom()

    def _on_live_entry(self, entry: dict[str, Any]) -> None:
        severity_filter = self.severity_filter.currentData()
        if severity_filter and entry.get("severity") != severity_filter:
            return
        operation = entry.get("operation", "")
        if operation in self._LIVE_LOG_STATUS_ONLY:
            details = entry.get("details_json") or {}
            embedded = details.get("embedded")
            total = details.get("total")
            if embedded is not None and total is not None:
                self.embedding_status.setText(f"Embedding progress: {embedded}/{total}")
            elif entry.get("message"):
                self.embedding_status.setText(str(entry["message"]))
            return
        self._append_entry(entry)

    def _clear_visible_log(self) -> None:
        self._entries.clear()
        self.log_list.clear()
        self.logger.info(
            component="ui.settings_tab",
            operation="clear_visible_log",
            message="Cleared visible log view without deleting persisted logs",
        )

    def refresh_persisted_logs(self) -> None:
        severity = self.severity_filter.currentData() or None
        persisted = fetch_process_logs(self.conn, severity=severity, limit=500)
        self._entries.clear()
        self.log_list.clear()
        for row in persisted:
            entry = {
                "process_log_id": row.process_log_id,
                "dataset_id": row.dataset_id,
                "timestamp": row.timestamp,
                "severity": row.severity,
                "component": row.component,
                "operation": row.operation,
                "message": row.message,
                "details_json": row.details_json,
                "exception_type": row.exception_type,
                "stack_trace": row.stack_trace,
            }
            self._append_entry(entry)

    def _emit_test_logs(self) -> None:
        self.logger.info(
            component="ui.settings_tab",
            operation="test_log_info",
            message="Test info log entry",
            details={"source": "test_log_button"},
        )
        self.logger.warning(
            component="ui.settings_tab",
            operation="test_log_warning",
            message="Test warning log entry",
        )
        try:
            raise RuntimeError("deliberate settings-tab test exception")
        except RuntimeError as exc:
            self.logger.error(
                component="ui.settings_tab",
                operation="test_log_error",
                message="Test error log entry with stack trace",
                exc=exc,
            )

    def _current_nim_settings(self):
        self.settings.nim.api_base_url = self.nim_base_url.text().strip()
        self.settings.nim.api_key = self.nim_api_key.text().strip()
        self.settings.nim.model = self.nim_model.currentText().strip()
        self.settings.nim.temperature = float(self.nim_temperature.value())
        self.settings.nim.max_output_tokens = int(self.nim_max_tokens.value())
        self.settings.nim.timeout_seconds = float(self.nim_timeout.value())
        self.settings.nim.streaming = self.nim_streaming.isChecked()
        return self.settings.nim

    def _save_nim_settings(self) -> None:
        nim = self._current_nim_settings()
        self.settings.nim = nim
        save_settings(self.settings)
        self.logger.info(
            component="ui.settings_tab",
            operation="nim_settings_saved",
            message="NIM settings saved",
            details={"api_base_url": nim.api_base_url, "model": nim.model},
        )

    def set_dataset(self, dataset_id: int | None) -> None:
        self.dataset_id = dataset_id
        self.refresh_context_budget_readout()

    def refresh_context_budget_readout(self) -> None:
        from message_evidence_workstation.config.settings import AnswerSettings
        from message_evidence_workstation.search.conversational_answer import (
            build_dataset_transcript,
            resolve_answer_budget,
        )

        model_id = self.nim_model.currentText().strip() or self.settings.nim.model or "unknown-model"
        provider_metadata = self.settings.nim_model_metadata.get(model_id, {})
        answer_settings = AnswerSettings(
            answer_strategy=str(self.answer_strategy.currentData() or "auto"),
            whole_transcript_max_chars=int(self.whole_transcript_max_chars.value()),
            session_gap_minutes=int(self.answer_session_gap_minutes.value()),
            max_inspected_sessions=int(self.max_inspected_sessions.value()),
            transcript_window_padding=int(self.transcript_window_padding.value()),
            context_window_override_tokens=int(self.context_window_override_tokens.value()),
            context_safety_ratio=float(self.context_safety_ratio.value()),
            reserved_output_tokens=int(self.reserved_output_tokens.value()),
            prompt_overhead_tokens=int(self.prompt_overhead_tokens.value()),
            window_target_tokens=int(self.window_target_tokens.value()),
            window_overlap_messages=int(self.window_overlap_messages.value()),
        )
        transcript_tokens = "n/a"
        auto_decision = "n/a"
        if self.dataset_id is not None:
            transcript = build_dataset_transcript(self.conn, self.dataset_id)
            budget = resolve_answer_budget(
                transcript,
                answer_settings,
                model_id,
                provider_metadata=provider_metadata,
            )
            transcript_tokens = (
                f"{budget.transcript_tokens} ({budget.transcript_token_method})"
            )
            auto_decision = budget.decision
            usable_input = budget.usable_input_tokens
            context_window = budget.context_window_tokens
            context_source = budget.context_source
            if context_source == "default":
                context_source = "safe default (override in settings if needed)"
        else:
            from message_evidence_workstation.nim.model_context import resolve_model_context

            model_context = resolve_model_context(
                model_id,
                provider_metadata=provider_metadata,
                user_override_tokens=(
                    answer_settings.context_window_override_tokens
                    if answer_settings.context_window_override_tokens > 0
                    else None
                ),
            )
            context_window = model_context.context_window_tokens
            context_source = (
                "safe default (override in settings if needed)"
                if model_context.source == "default"
                else model_context.source
            )
            safety_ratio = max(0.25, min(0.90, answer_settings.context_safety_ratio))
            usable_input = max(
                1000,
                int(context_window * safety_ratio)
                - answer_settings.reserved_output_tokens
                - answer_settings.prompt_overhead_tokens,
            )
        self.context_budget_readout.setText(
            "\n".join(
                [
                    f"Selected answer model: {model_id or '(not set)'}",
                    f"Context window tokens: {context_window}",
                    f"Context source: {context_source}",
                    f"Usable input budget: {usable_input}",
                    f"Reserved output tokens: {answer_settings.reserved_output_tokens}",
                    f"Prompt overhead tokens: {answer_settings.prompt_overhead_tokens}",
                    f"Transcript token estimate: {transcript_tokens}",
                    f"Auto mode decision: {auto_decision}",
                ]
            )
        )

    def _save_answer_settings(self) -> None:
        self.settings.answer.answer_strategy = str(
            self.answer_strategy.currentData() or "auto"
        )
        self.settings.answer.whole_transcript_max_chars = int(self.whole_transcript_max_chars.value())
        self.settings.answer.session_gap_minutes = int(self.answer_session_gap_minutes.value())
        self.settings.answer.max_inspected_sessions = int(self.max_inspected_sessions.value())
        self.settings.answer.transcript_window_padding = int(self.transcript_window_padding.value())
        self.settings.answer.context_window_override_tokens = int(
            self.context_window_override_tokens.value()
        )
        self.settings.answer.context_safety_ratio = float(self.context_safety_ratio.value())
        self.settings.answer.reserved_output_tokens = int(self.reserved_output_tokens.value())
        self.settings.answer.prompt_overhead_tokens = int(self.prompt_overhead_tokens.value())
        self.settings.answer.window_target_tokens = int(self.window_target_tokens.value())
        self.settings.answer.window_overlap_messages = int(self.window_overlap_messages.value())
        save_settings(self.settings)
        self.refresh_context_budget_readout()
        self.logger.info(
            component="ui.settings_tab",
            operation="answer_settings_saved",
            message="Conversational answer settings saved",
            details={
                "answer_strategy": self.settings.answer.answer_strategy,
                "whole_transcript_max_chars": self.settings.answer.whole_transcript_max_chars,
            },
        )

    def _rebuild_transcript_sessions(self) -> None:
        if self.dataset_id is None:
            self.embedding_status.setText("Load a dataset before rebuilding transcript sessions.")
            return
        from message_evidence_workstation.search.session_map import rebuild_dataset_sessions

        sessions = rebuild_dataset_sessions(
            self.conn,
            self.logger,
            self.dataset_id,
            gap_minutes=int(self.answer_session_gap_minutes.value()),
        )
        self.embedding_status.setText(
            f"Rebuilt {len(sessions)} transcript session(s) for dataset {self.dataset_id}."
        )

    def _persist_nim_model_selection(self) -> None:
        model = self.nim_model.currentText().strip()
        if not model:
            return
        self.settings.nim = self._current_nim_settings()
        self.settings.nim.model = model
        save_settings(self.settings)

    def _persist_nim_timeout(self, _value: float) -> None:
        self.settings.nim = self._current_nim_settings()
        save_settings(self.settings)

    def _refresh_models(self) -> None:
        nim = self._current_nim_settings()
        self.refresh_models_button.setEnabled(False)
        self.embedding_status.setText("Fetching NIM model list…")
        db_path = self.db_path
        dataset_id = self.dataset_id

        def work():
            from message_evidence_workstation.db.connection import connect
            from message_evidence_workstation.logging_ui.log_bus import get_log_bus
            from message_evidence_workstation.logging_ui.process_log import ProcessLogger

            worker_conn = connect(db_path)
            try:
                worker_logger = ProcessLogger(
                    worker_conn, log_bus=get_log_bus(), dataset_id=dataset_id
                )
                worker_logger.info(
                    component="ui.settings_tab",
                    operation="nim_model_list_start",
                    message="Refreshing NIM model list (HTTP request running in background)",
                    details={"api_base_url": nim.api_base_url},
                    dataset_id=dataset_id,
                )
                return NimClient(nim).list_models()
            finally:
                worker_conn.close()

        def on_success(models: object) -> None:
            self.refresh_models_button.setEnabled(True)
            model_list = list(models)  # type: ignore[arg-type]
            self.nim_model.clear()
            for model in model_list:
                self.nim_model.addItem(model.id)
            selected = self.nim_model.currentText().strip()
            if model_list and not selected:
                self.nim_model.setCurrentText(model_list[0].id)
            self.settings.nim.manual_model_entry_enabled = False
            self.settings.nim_model_metadata = {
                model.id: dict(model.metadata) for model in model_list
            }
            save_settings(self.settings)
            self._persist_nim_model_selection()
            self.refresh_context_budget_readout()
            self.embedding_status.setText(f"NIM model list refreshed ({len(model_list)} models)")
            self.logger.info(
                component="ui.settings_tab",
                operation="nim_model_list_success",
                message="NIM model list refreshed",
                details={
                    "model_count": len(model_list),
                    "selected_model": self.nim_model.currentText().strip(),
                },
            )

        def on_error(exc: BaseException) -> None:
            self.refresh_models_button.setEnabled(True)
            if isinstance(exc, NimClientError):
                self.settings.nim.manual_model_entry_enabled = True
                self.nim_model.setEditable(True)
                self.embedding_status.setText(f"NIM model list failed: {nim_error_user_message(exc)}")
                self.logger.error(
                    component="ui.settings_tab",
                    operation="nim_model_list_failed",
                    message=str(exc),
                    details={"error_type": exc.error_type, **exc.details},
                    exc=exc,
                )
            else:
                self.embedding_status.setText(f"NIM model list failed: {exc}")
                self.logger.error(
                    component="ui.settings_tab",
                    operation="nim_model_list_failed",
                    message="Unexpected model list failure",
                    exc=exc,
                )

        from message_evidence_workstation.ui.background_tasks import run_background

        run_background(self, work, on_success=on_success, on_error=on_error)

    def _load_selected_prompt(self) -> None:
        run_type = self.prompt_type.currentData()
        from message_evidence_workstation.nim.prompts import get_active_prompt

        row = get_active_prompt(self.conn, run_type)
        self.prompt_body.setPlainText(row["body"] if row else "")

    def _save_prompt(self) -> None:
        run_type = self.prompt_type.currentData()
        body = self.prompt_body.toPlainText().strip()
        from message_evidence_workstation.nim.prompts import save_prompt_version

        save_prompt_version(self.conn, self.logger, run_type, body)
        self.logger.info(
            component="ui.settings_tab",
            operation="prompt_saved",
            message=f"Saved prompt for {run_type}",
        )

    def _load_embedding_model(self) -> None:
        model_id = self.embedding_model.currentData()
        from message_evidence_workstation.embeddings.model_registry import get_model_spec
        from message_evidence_workstation.ui.embedding_worker import (
            EmbeddingJobSpec,
            invalidate_embedding_model_cache,
            run_embedding_job,
        )

        spec = get_model_spec(model_id)
        if spec is None:
            self.embedding_status.setText("Unknown model selection")
            return
        invalidate_embedding_model_cache(self)
        self.load_embedding_button.setEnabled(False)
        self.embedding_status.setText("Reloading embedding model…")
        self.logger.info(
            component="ui.settings_tab",
            operation="embedding_model_load_requested",
            message=f"Reloading embedding model {model_id}",
            dataset_id=self.dataset_id,
        )

        job = EmbeddingJobSpec(
            job_type="load",
            db_path=self.db_path,
            dataset_id=self.dataset_id or 0,
            adapter_key=spec.adapter_key,
            model_id=spec.model_id,
        )

        def on_success(result: object) -> None:
            self._on_embedding_model_ready(result)
            self.settings.embedding_model = model_id
            save_settings(self.settings)

        def on_error(exc: BaseException) -> None:
            self._on_embedding_model_preload_failed(exc)

        run_embedding_job(self, job, on_success=on_success, on_error=on_error)

    def _validate_sqlite_vec(self) -> None:
        from message_evidence_workstation.embeddings.sqlite_vec_backend import (
            record_validation_status,
            validate_sqlite_vec,
        )

        result = validate_sqlite_vec(self.conn, self.logger)
        record_validation_status(self.conn, self.logger, dataset_id=self.logger.dataset_id, result=result)
        if result.success:
            self.embedding_status.setText("sqlite-vec validation succeeded")
        else:
            self.embedding_status.setText(result.message)

    def _on_embedding_model_changed(self) -> None:
        model_id = self.embedding_model.currentData()
        if not model_id:
            return
        self.settings.embedding_model = model_id
        save_settings(self.settings)
        from message_evidence_workstation.ui.embedding_worker import invalidate_embedding_model_cache

        invalidate_embedding_model_cache(self)
        if self.dataset_id is not None:
            from message_evidence_workstation.embeddings.index_jobs import mark_indexes_stale_for_model_change

            mark_indexes_stale_for_model_change(self.conn, self.logger, self.dataset_id, model_id)
        self._update_chunk_preview()

    def _current_chunking_config(self):
        from message_evidence_workstation.embeddings.chunking import ChunkingConfig

        return ChunkingConfig(
            max_chars=int(self.chunk_max_chars.value()),
            semantic_similarity_threshold=float(self.chunk_similarity_threshold.value()),
            session_gap_hours=float(self.chunk_session_gap_hours.value()),
            use_semantic_boundaries=True,
            split_on_date_change=True,
        )

    def _on_chunking_controls_changed(self, *_args: object) -> None:
        config = self._current_chunking_config()
        self.settings.chunking = {
            "max_chars": config.max_chars,
            "semantic_similarity_threshold": config.semantic_similarity_threshold,
            "session_gap_hours": config.session_gap_hours,
            "use_semantic_boundaries": config.use_semantic_boundaries,
            "split_on_date_change": config.split_on_date_change,
        }
        save_settings(self.settings)
        if hasattr(self, "_chunk_preview_timer"):
            self._chunk_preview_timer.start(150)

    def _update_chunk_preview(self) -> None:
        if self.dataset_id is None:
            self.chunk_preview_label.setText("Load a dataset to preview chunk counts.")
            return
        try:
            from message_evidence_workstation.embeddings.chunking import count_dataset_chunks, message_vector_count

            message_count = int(
                self.conn.execute(
                    "SELECT COUNT(*) FROM message WHERE dataset_id = ?",
                    (self.dataset_id,),
                ).fetchone()[0]
            )
            vector_count = message_vector_count(self.conn, self.dataset_id)
            if vector_count < message_count:
                self.chunk_preview_label.setText(
                    f"Build message embeddings first for semantic chunking "
                    f"({vector_count}/{message_count} message vectors ready)."
                )
                return
            config = self._current_chunking_config()
            chunk_count = count_dataset_chunks(self.conn, self.dataset_id, config=config)
            self.chunk_preview_label.setText(
                f"{chunk_count} chunks from {message_count} messages | "
                f"threshold={config.semantic_similarity_threshold:.2f}, "
                f"gap={config.session_gap_hours:g}h, max={config.max_chars} chars"
            )
        except Exception as exc:
            self.chunk_preview_label.setText(f"Chunk preview failed: {exc}")

    def _start_index_job(self, granularity: str, *, force_restart: bool = False) -> None:
        if self.dataset_id is None:
            self.embedding_status.setText("Load a dataset before building embedding indexes.")
            return
        if not self._embedding_model_ready:
            self.embedding_status.setText("Wait for the embedding model to finish loading at startup.")
            return
        model_id = self.embedding_model.currentData()
        from message_evidence_workstation.embeddings.index_jobs import IndexBuildResult
        from message_evidence_workstation.embeddings.model_registry import get_model_spec
        from message_evidence_workstation.ui.embedding_worker import (
            EmbeddingJobSpec,
            run_embedding_job,
        )

        spec = get_model_spec(model_id)
        if spec is None:
            self.embedding_status.setText("Unknown embedding model selection.")
            return
        chunking_config = None
        if granularity == "chunk":
            from message_evidence_workstation.embeddings.chunking import message_vector_count

            message_count = int(
                self.conn.execute(
                    "SELECT COUNT(*) FROM message WHERE dataset_id = ?",
                    (self.dataset_id,),
                ).fetchone()[0]
            )
            vector_count = message_vector_count(self.conn, self.dataset_id)
            if vector_count < message_count:
                self.embedding_status.setText(
                    f"Build message embeddings first ({vector_count}/{message_count} message vectors ready)."
                )
                self._update_chunk_preview()
                return
            chunking_config = self._current_chunking_config().to_metadata()
        self.build_message_index_button.setEnabled(False)
        self.restart_message_index_button.setEnabled(False)
        self.build_chunk_index_button.setEnabled(False)
        self.restart_chunk_index_button.setEnabled(False)
        action = "Restarting" if force_restart else "Building"
        self.embedding_status.setText(
            f"{action} {granularity} embedding index — watch progress in the log below…"
        )
        self.logger.info(
            component="ui.settings_tab",
            operation="embedding_index_build_requested",
            message=f"{action} {granularity} embedding index for model {model_id}",
            details={
                "granularity": granularity,
                "force_restart": force_restart,
                "chunking_config": chunking_config,
            },
            dataset_id=self.dataset_id,
        )

        job = EmbeddingJobSpec(
            job_type="message_index" if granularity == "message" else "chunk_index",
            db_path=self.db_path,
            dataset_id=self.dataset_id or 0,
            adapter_key=spec.adapter_key,
            model_id=spec.model_id,
            force_restart=force_restart,
            chunking_config=chunking_config or {},
        )

        def on_success(result: object) -> None:
            from message_evidence_workstation.diagnostics.trace_log import trace

            trace(
                "settings_tab",
                "index_build_on_success_enter",
                granularity=granularity,
                result_type=type(result).__name__,
            )
            self.build_message_index_button.setEnabled(True)
            self.restart_message_index_button.setEnabled(True)
            self.build_chunk_index_button.setEnabled(True)
            self.restart_chunk_index_button.setEnabled(True)
            if not isinstance(result, IndexBuildResult):
                return
            build = result
            if build.success:
                resumed = " (resumed)" if build.resumed else ""
                self.embedding_status.setText(
                    f"{granularity} index ready{resumed}: "
                    f"{build.count}/{build.total_target or build.count} vectors in {build.elapsed_ms}ms"
                )
            elif build.count > 0:
                self.embedding_status.setText(
                    f"{granularity} index failed after {build.count} vectors — "
                    f"click Build to resume or Restart to begin again"
                )
            else:
                self.embedding_status.setText(f"{granularity} index failed: {build.error}")
            self._update_chunk_preview()
            trace("settings_tab", "index_build_on_success_exit", granularity=granularity)

        def on_error(exc: BaseException) -> None:
            from message_evidence_workstation.diagnostics.trace_log import trace

            trace("settings_tab", "index_build_on_error", granularity=granularity, error=str(exc))
            self.build_message_index_button.setEnabled(True)
            self.restart_message_index_button.setEnabled(True)
            self.build_chunk_index_button.setEnabled(True)
            self.restart_chunk_index_button.setEnabled(True)
            self.embedding_status.setText(f"{granularity} index failed: {exc}")
            self.logger.error(
                component="ui.settings_tab",
                operation=f"{granularity}_index_build_failed",
                message=str(exc),
                exc=exc,
                dataset_id=self.dataset_id,
            )

        run_embedding_job(self, job, on_success=on_success, on_error=on_error)

    def _build_message_index(self) -> None:
        self._start_index_job("message")

    def _restart_message_index(self) -> None:
        self._start_index_job("message", force_restart=True)

    def _build_chunk_index(self) -> None:
        self._start_index_job("chunk")

    def _restart_chunk_index(self) -> None:
        self._start_index_job("chunk", force_restart=True)

    def refresh_model_runs(self) -> None:
        from message_evidence_workstation.export.audit_export import list_model_runs

        self._model_runs = list_model_runs(self.conn, dataset_id=self.dataset_id, limit=200)
        self.model_run_list.clear()
        for run in self._model_runs:
            status = "FAILED" if run.error_type else "ok"
            latency = f"{run.latency_ms}ms" if run.latency_ms is not None else "—"
            prompt_version = run.prompt_version if run.prompt_version is not None else "—"
            item = QListWidgetItem(
                f"[{run.created_at}] {run.run_type} | {run.model} | v{prompt_version} | {latency} | {status}"
            )
            item.setData(Qt.ItemDataRole.UserRole, run.model_run_id)
            self.model_run_list.addItem(item)
        if self._model_runs:
            self.model_run_list.setCurrentRow(len(self._model_runs) - 1)

    def _on_model_run_selected(self, row: int) -> None:
        if row < 0:
            self.model_run_detail.clear()
            return
        from message_evidence_workstation.export.audit_export import get_model_run_detail

        item = self.model_run_list.item(row)
        if item is None:
            return
        detail = get_model_run_detail(self.conn, int(item.data(Qt.ItemDataRole.UserRole)))
        if detail is None:
            self.model_run_detail.clear()
            return
        self.model_run_detail.setPlainText(json.dumps(detail, indent=2))

    def _export_process_log_json(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        from message_evidence_workstation.export.audit_export import export_process_log_json

        path, _ = QFileDialog.getSaveFileName(self, "Export process log", "process_log.json", "JSON (*.json)")
        if not path:
            return
        size = export_process_log_json(self.conn, Path(path), dataset_id=self.dataset_id)
        self.logger.info(
            component="ui.settings_tab",
            operation="process_log_export_json",
            message=f"Exported process log JSON ({size} bytes)",
            details={"path": path},
            dataset_id=self.dataset_id,
        )

    def _export_process_log_text(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        from message_evidence_workstation.export.audit_export import export_process_log_text

        path, _ = QFileDialog.getSaveFileName(self, "Export process log", "process_log.txt", "Text (*.txt)")
        if not path:
            return
        size = export_process_log_text(self.conn, Path(path), dataset_id=self.dataset_id)
        self.logger.info(
            component="ui.settings_tab",
            operation="process_log_export_text",
            message=f"Exported process log text ({size} bytes)",
            details={"path": path},
            dataset_id=self.dataset_id,
        )

    def _export_audit_bundle(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        from message_evidence_workstation.export.audit_export import export_audit_bundle

        path = QFileDialog.getExistingDirectory(self, "Choose audit export folder")
        if not path:
            return
        sizes = export_audit_bundle(
            self.conn,
            self.logger,
            Path(path),
            dataset_id=self.dataset_id,
        )
        self.refresh_model_runs()
        self.model_run_detail.setPlainText(json.dumps(sizes, indent=2))
