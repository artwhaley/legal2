"""Settings tab with verbose process log viewer."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from message_evidence_workstation.config.settings import (
    AppSettings,
    ModelRoleConfig,
    ModelRoutingSettings,
    PROVIDER_GOOGLE,
    PROVIDER_NIM,
    default_model_routing,
    load_settings,
    save_settings,
)
from message_evidence_workstation.domain.constants import (
    SEVERITY_DEBUG,
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARNING,
)
from message_evidence_workstation.llm.errors import ModelError, model_error_user_message
from message_evidence_workstation.llm.router import ModelRouter
from message_evidence_workstation.llm.types import ModelTaskRole, ModelTestResult, UserFacingModelRole
from message_evidence_workstation.logging_ui.log_bus import LogBus
from message_evidence_workstation.logging_ui.process_log import ProcessLogger, fetch_process_logs
from message_evidence_workstation.nim.client import (
    NimClientError,
    nim_error_log_details,
    nim_error_user_message,
)


# T25: task roles for settings-only NIM operations (not routed through run_nim_chat).
MODEL_LIST_TASK_ROLE = ModelTaskRole.MODEL_LIST
MODEL_TEST_TASK_ROLE = ModelTaskRole.MODEL_TEST


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
        self._logs_loaded = False
        self._chunk_preview_generation = 0
        self.settings = load_settings()
        self._models_by_provider: dict[str, list] = {}
        self._initializing = True

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        scroll.setWidget(content)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.addWidget(scroll)

        layout = QVBoxLayout(content)
        layout.addWidget(QLabel("Setup / Settings"))

        nim_group = QGroupBox("API settings")
        nim_form = QFormLayout(nim_group)
        self.nim_base_url = QLineEdit(self.settings.nim.api_base_url)
        nim_form.addRow("NIM API base URL", self.nim_base_url)
        self.nim_api_key = QLineEdit(self.settings.nim.api_key)
        self.nim_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.nim_api_key.setPlaceholderText("Use MEW_NIM_API_KEY env var or enter key")
        nim_form.addRow("NIM API key", self.nim_api_key)
        self.google_api_key = QLineEdit(self._google_api_key_from_settings())
        self.google_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.google_api_key.setPlaceholderText("Use MEW_GOOGLE_API_KEY env var or enter key")
        nim_form.addRow("Google API key", self.google_api_key)
        self.nim_temperature = QDoubleSpinBox()
        self.nim_temperature.setRange(0.0, 2.0)
        self.nim_temperature.setSingleStep(0.1)
        self.nim_temperature.setValue(self.settings.nim.temperature)
        nim_form.addRow("Shared temperature", self.nim_temperature)
        self.nim_max_tokens = QSpinBox()
        self.nim_max_tokens.setRange(256, 131_072)
        self.nim_max_tokens.setSingleStep(256)
        self.nim_max_tokens.setValue(self.settings.nim.max_output_tokens)
        self.nim_max_tokens.setToolTip(
            "Maximum output tokens sent on every routed model call, including conversational answers."
        )
        nim_form.addRow("Max output tokens", self.nim_max_tokens)
        self.context_window_tokens = QSpinBox()
        self.context_window_tokens.setRange(0, 2_000_000)
        self.context_window_tokens.setSingleStep(1024)
        self.context_window_tokens.setValue(self.settings.nim.context_window_tokens)
        self.context_window_tokens.setToolTip(
            "Context window size for the selected writing model. "
            "Must be set before conversational features can run."
        )
        nim_form.addRow("Model context window (tokens)", self.context_window_tokens)
        self.context_safety_ratio = QDoubleSpinBox()
        self.context_safety_ratio.setRange(0.25, 0.90)
        self.context_safety_ratio.setSingleStep(0.05)
        self.context_safety_ratio.setValue(self.settings.nim.context_safety_ratio)
        nim_form.addRow("Context safety ratio", self.context_safety_ratio)
        self.prompt_overhead_tokens = QSpinBox()
        self.prompt_overhead_tokens.setRange(0, 20000)
        self.prompt_overhead_tokens.setValue(self.settings.nim.prompt_overhead_tokens)
        nim_form.addRow("Prompt overhead tokens", self.prompt_overhead_tokens)
        self.nim_timeout = QDoubleSpinBox()
        self.nim_timeout.setRange(1.0, 3600.0)
        self.nim_timeout.setValue(self.settings.nim.timeout_seconds)
        self.nim_timeout.setToolTip(
            "Shared model timeout for routed provider calls. Increase if calls time out."
        )
        self.nim_timeout.valueChanged.connect(self._persist_nim_timeout)
        nim_form.addRow("Shared timeout (s)", self.nim_timeout)
        self.nim_streaming = QCheckBox("Streaming enabled")
        self.nim_streaming.setChecked(self.settings.nim.streaming)
        nim_form.addRow("", self.nim_streaming)
        for widget in (
            self.nim_max_tokens,
            self.context_window_tokens,
            self.context_safety_ratio,
            self.prompt_overhead_tokens,
        ):
            widget.valueChanged.connect(self.refresh_context_budget_readout)
        layout.addWidget(nim_group)

        routing_group = QGroupBox("Model routing")
        routing_form = QFormLayout(routing_group)
        self.role_provider: dict[UserFacingModelRole, QComboBox] = {}
        self.role_model: dict[UserFacingModelRole, QComboBox] = {}
        self.role_test_result: dict[UserFacingModelRole, QLabel] = {}
        for label, role in (
            ("Expansion model", UserFacingModelRole.EXPANSION),
            ("Research model", UserFacingModelRole.RESEARCH),
            ("Writing model", UserFacingModelRole.WRITING),
        ):
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            provider = QComboBox()
            provider.addItem("NVIDIA NIM", PROVIDER_NIM)
            provider.addItem("Google AI Studio", PROVIDER_GOOGLE)
            model = QComboBox()
            model.setEditable(True)
            test_button = QPushButton("Test")
            test_button.clicked.connect(lambda _checked=False, r=role: self._test_role_model(r))
            self.role_provider[role] = provider
            self.role_model[role] = model
            provider.currentIndexChanged.connect(
                lambda _index, r=role: self._on_role_provider_changed(r)
            )
            self.role_model[role].currentIndexChanged.connect(self.refresh_context_budget_readout)
            self.role_model[role].editTextChanged.connect(self.refresh_context_budget_readout)
            row_layout.addWidget(provider)
            row_layout.addWidget(model, stretch=1)
            row_layout.addWidget(test_button)
            routing_form.addRow(label, row)
            result_label = QLabel("Not tested yet.")
            result_label.setWordWrap(True)
            result_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.role_test_result[role] = result_label
            routing_form.addRow(f"{label} test", result_label)
        self._populate_role_routing_controls()
        routing_buttons = QHBoxLayout()
        self.refresh_models_button = QPushButton("Refresh model lists")
        self.refresh_models_button.setToolTip(
            "Fetch available models from NIM and Google (when credentials are configured)."
        )
        self.refresh_models_button.clicked.connect(self._refresh_models)
        routing_buttons.addWidget(self.refresh_models_button)
        self.save_routing_button = QPushButton("Save API settings")
        self.save_routing_button.clicked.connect(self._save_api_settings)
        routing_buttons.addWidget(self.save_routing_button)
        routing_form.addRow("", routing_buttons)
        layout.addWidget(routing_group)

        answer_group = QGroupBox("Conversational answer strategy")
        answer_form = QFormLayout(answer_group)
        self.answer_strategy = QComboBox()
        for label, value in (
            ("Whole transcript (default)", "whole_transcript"),
            ("Exhaustive window scan (inspect every session)", "exhaustive_window_scan"),
            ("Session summary triage (faster, lower recall)", "session_coverage"),
        ):
            self.answer_strategy.addItem(label, value)
        strategy_index = self.answer_strategy.findData(self.settings.answer.answer_strategy)
        if strategy_index >= 0:
            self.answer_strategy.setCurrentIndex(strategy_index)
        answer_form.addRow("Answer strategy", self.answer_strategy)
        self.answer_session_gap_minutes = QSpinBox()
        self.answer_session_gap_minutes.setRange(15, 24 * 60)
        self.answer_session_gap_minutes.setValue(self.settings.answer.session_gap_minutes)
        answer_form.addRow("Session gap (minutes)", self.answer_session_gap_minutes)
        self.window_overlap_messages = QSpinBox()
        self.window_overlap_messages.setRange(0, 20)
        self.window_overlap_messages.setValue(self.settings.nim.window_overlap_messages)
        answer_form.addRow("Window overlap (messages)", self.window_overlap_messages)
        self.context_budget_readout = QLabel()
        self.context_budget_readout.setWordWrap(True)
        answer_form.addRow("Context budget readout", self.context_budget_readout)
        for widget in (
            self.answer_strategy,
            self.window_overlap_messages,
            self.role_model[UserFacingModelRole.WRITING],
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

        prompt_group = QGroupBox("Prompt templates")
        prompt_layout = QVBoxLayout(prompt_group)
        prompt_row = QHBoxLayout()
        from message_evidence_workstation.nim.prompts import ALL_RUN_TYPES

        self.prompt_type = QComboBox()
        for run_type in ALL_RUN_TYPES:
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
            DEFAULT_DESIRED_AVERAGE_CHUNK_MESSAGES,
            DEFAULT_MAX_CHARS,
            DEFAULT_SESSION_GAP_HOURS,
        )

        chunking_settings = self.settings.chunking or {}
        self.chunk_desired_average = QSlider(Qt.Orientation.Horizontal)
        self.chunk_desired_average.setRange(2, 20)
        self.chunk_desired_average.setSingleStep(1)
        self.chunk_desired_average.setPageStep(1)
        self.chunk_desired_average.setValue(
            int(chunking_settings.get("desired_average_chunk_messages", DEFAULT_DESIRED_AVERAGE_CHUNK_MESSAGES))
        )
        self.chunk_desired_average.setToolTip(
            "Target average messages per semantic chunk. The app calibrates the similarity threshold to match this."
        )
        self.chunk_desired_average_label = QLabel()
        self.chunk_desired_average_label.setText(f"{self.chunk_desired_average.value()} messages")
        desired_layout = QHBoxLayout()
        desired_layout.addWidget(self.chunk_desired_average)
        desired_layout.addWidget(self.chunk_desired_average_label)
        self.chunk_desired_average.valueChanged.connect(self._on_chunking_controls_changed)
        chunking_form.addRow("Desired average chunk length", desired_layout)

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
        self._chunk_preview_timer = QTimer(self)
        self._chunk_preview_timer.setSingleShot(True)
        self._chunk_preview_timer.timeout.connect(self._update_chunk_preview)
        self._initializing = False
        self.refresh_context_budget_readout()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._logs_loaded:
            self._logs_loaded = True
            self.refresh_persisted_logs()
        self._chunk_preview_timer.start(250)

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

    def _append_entry(self, entry: dict[str, Any], *, scroll: bool = True) -> None:
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
        if scroll:
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
            self._append_entry(entry, scroll=False)
        if self.log_list.count() > 0:
            self.log_list.scrollToBottom()

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

    def _ensure_model_routing(self) -> ModelRoutingSettings:
        if self.settings.model_routing is None:
            self.settings.model_routing = default_model_routing(self.settings.nim)
        return self.settings.model_routing

    def _google_api_key_from_settings(self) -> str:
        routing = self.settings.model_routing
        if routing is not None and routing.expansion.provider == PROVIDER_GOOGLE:
            return routing.expansion.api_key
        if routing is not None and routing.research.api_key:
            return routing.research.api_key
        if routing is not None and routing.writing.api_key:
            return routing.writing.api_key
        return ""

    def _populate_role_routing_controls(self) -> None:
        routing = self._ensure_model_routing()
        for role, config in (
            (UserFacingModelRole.EXPANSION, routing.expansion),
            (UserFacingModelRole.RESEARCH, routing.research),
            (UserFacingModelRole.WRITING, routing.writing),
        ):
            self.role_provider[role].blockSignals(True)
            self.role_model[role].blockSignals(True)
            provider_index = self.role_provider[role].findData(config.provider)
            if provider_index >= 0:
                self.role_provider[role].setCurrentIndex(provider_index)
            self.role_model[role].setEditable(True)
            self.role_model[role].setCurrentText(config.model)
            self.role_model[role].blockSignals(False)
            self.role_provider[role].blockSignals(False)

    def _role_config_from_ui(self, role: UserFacingModelRole) -> ModelRoleConfig:
        nim = self._current_nim_settings()
        provider = str(self.role_provider[role].currentData() or PROVIDER_NIM)
        google_key = self.google_api_key.text().strip()
        routing = self._ensure_model_routing()
        existing = {
            UserFacingModelRole.EXPANSION: routing.expansion,
            UserFacingModelRole.RESEARCH: routing.research,
            UserFacingModelRole.WRITING: routing.writing,
        }[role]
        model = self.role_model[role].currentText().strip()
        if not model and existing.provider == provider:
            model = existing.model.strip()
        if provider == PROVIDER_NIM:
            return replace(
                existing,
                provider=provider,
                model=model,
                api_base_url=nim.api_base_url,
                api_key=nim.api_key,
                temperature=nim.temperature,
                max_output_tokens=nim.max_output_tokens,
                timeout_seconds=nim.timeout_seconds,
            )
        return replace(
            existing,
            provider=provider,
            model=model,
            api_base_url="",
            api_key=google_key,
            temperature=nim.temperature,
            max_output_tokens=nim.max_output_tokens,
            timeout_seconds=nim.timeout_seconds,
        )

    def _apply_role_routing_to_settings(self) -> None:
        routing = self._ensure_model_routing()
        routing.expansion = self._role_config_from_ui(UserFacingModelRole.EXPANSION)
        routing.research = self._role_config_from_ui(UserFacingModelRole.RESEARCH)
        routing.writing = self._role_config_from_ui(UserFacingModelRole.WRITING)
        self.settings.model_routing = routing

    def _save_api_settings(self) -> None:
        self.settings.nim = self._current_nim_settings()
        self._apply_role_routing_to_settings()
        save_settings(self.settings)
        self._populate_role_routing_controls()
        self.refresh_context_budget_readout()
        self.logger.info(
            component="ui.settings_tab",
            operation="api_settings_saved",
            message="API settings saved",
            details={
                "nim_api_base_url": self.settings.nim.api_base_url,
                "expansion_provider": self.settings.model_routing.expansion.provider if self.settings.model_routing else "",
                "research_provider": self.settings.model_routing.research.provider if self.settings.model_routing else "",
                "writing_provider": self.settings.model_routing.writing.provider if self.settings.model_routing else "",
            },
        )

    def _router_from_ui(self) -> ModelRouter:
        self.settings.nim = self._current_nim_settings()
        self._apply_role_routing_to_settings()
        return ModelRouter(self.settings)

    def _current_nim_settings(self):
        self.settings.nim.api_base_url = self.nim_base_url.text().strip()
        self.settings.nim.api_key = self.nim_api_key.text().strip()
        self.settings.nim.temperature = float(self.nim_temperature.value())
        self.settings.nim.max_output_tokens = int(self.nim_max_tokens.value())
        self.settings.nim.context_window_tokens = int(self.context_window_tokens.value())
        self.settings.nim.context_safety_ratio = float(self.context_safety_ratio.value())
        self.settings.nim.prompt_overhead_tokens = int(self.prompt_overhead_tokens.value())
        self.settings.nim.timeout_seconds = float(self.nim_timeout.value())
        self.settings.nim.streaming = self.nim_streaming.isChecked()
        return self.settings.nim

    def set_dataset(self, dataset_id: int | None) -> None:
        self.dataset_id = dataset_id
        self.refresh_context_budget_readout()
        if self.isVisible():
            self._chunk_preview_timer.start(250)
        elif hasattr(self, "chunk_preview_label"):
            self.chunk_preview_label.setText(
                "Switch to Setup / Settings to preview chunk counts after message embeddings are checked."
            )

    def refresh_context_budget_readout(self) -> None:
        if getattr(self, "_initializing", False):
            return
        if not hasattr(self, "answer_strategy") or not hasattr(self, "context_budget_readout"):
            return
        from message_evidence_workstation.config.settings import AnswerSettings
        from message_evidence_workstation.search.dataset_budget import compute_dataset_budget_stats
        from message_evidence_workstation.search.conversational_answer import resolve_answer_budget

        nim_settings = self._current_nim_settings()
        model_id = (
            self.role_model[UserFacingModelRole.WRITING].currentText().strip()
            or (self.settings.model_routing.writing.model if self.settings.model_routing else "")
            or "unknown-model"
        )
        provider_metadata = self.settings.model_metadata.get(model_id, {})
        answer_settings = AnswerSettings(
            answer_strategy=str(self.answer_strategy.currentData() or "whole_transcript"),
            session_gap_minutes=int(self.answer_session_gap_minutes.value()),
        )
        transcript_tokens = "n/a"
        auto_decision = "n/a"
        if self.dataset_id is not None:
            if nim_settings.context_window_tokens <= 0:
                transcript_tokens = "n/a"
                auto_decision = "n/a"
                context_window = 0
                context_source = "not configured — set Model context window in API settings"
                usable_input = 0
                max_output = max(1, nim_settings.max_output_tokens)
            else:
                stats = compute_dataset_budget_stats(self.conn, self.dataset_id)
                budget = resolve_answer_budget(
                    stats,
                    answer_settings,
                    model_id,
                    nim_settings=nim_settings,
                    provider_metadata=provider_metadata,
                )
                transcript_tokens = (
                    f"{budget.transcript_tokens} ({budget.transcript_token_method})"
                )
                auto_decision = budget.decision
                usable_input = budget.usable_input_tokens
                max_output = budget.max_output_tokens
                context_window = budget.context_window_tokens
                context_source = budget.context_source
        else:
            from message_evidence_workstation.nim.model_context import resolve_model_context
            from message_evidence_workstation.search.token_budget import compute_usable_input_tokens

            if nim_settings.context_window_tokens <= 0:
                context_window = 0
                context_source = "not configured — set Model context window in API settings"
                usable_input = 0
                max_output = max(1, nim_settings.max_output_tokens)
            else:
                model_context = resolve_model_context(
                    model_id,
                    context_window_tokens=nim_settings.context_window_tokens,
                    provider_metadata=provider_metadata,
                )
                context_window = model_context.context_window_tokens
                context_source = model_context.source
                usable_input = compute_usable_input_tokens(
                    context_window_tokens=context_window,
                    safety_ratio=max(0.25, min(0.90, nim_settings.context_safety_ratio)),
                    prompt_overhead_tokens=nim_settings.prompt_overhead_tokens,
                )
                max_output = max(1, nim_settings.max_output_tokens)
        self.context_budget_readout.setText(
            "\n".join(
                [
                    f"Selected answer model: {model_id or '(not set)'}",
                    f"Context window tokens: {context_window}",
                    f"Context source: {context_source}",
                    f"Usable input budget: {usable_input}",
                    f"Max output tokens (API settings): {max_output}",
                    f"Prompt overhead tokens (API settings): {nim_settings.prompt_overhead_tokens}",
                    f"Transcript token estimate: {transcript_tokens}",
                    f"Auto mode decision: {auto_decision}",
                ]
            )
        )

    def _save_answer_settings(self) -> None:
        self.settings.answer.answer_strategy = str(
            self.answer_strategy.currentData() or "whole_transcript"
        )
        self.settings.answer.session_gap_minutes = int(self.answer_session_gap_minutes.value())
        self.settings.nim.window_overlap_messages = int(self.window_overlap_messages.value())
        save_settings(self.settings)
        self.refresh_context_budget_readout()
        self.logger.info(
            component="ui.settings_tab",
            operation="answer_settings_saved",
            message="Conversational answer settings saved",
            details={
                "answer_strategy": self.settings.answer.answer_strategy,
                "session_gap_minutes": self.settings.answer.session_gap_minutes,
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

    def _settings_for_model_list(self):
        import copy

        self.settings.nim = self._current_nim_settings()
        self._apply_role_routing_to_settings()
        settings = copy.deepcopy(self.settings)
        google_key = self.google_api_key.text().strip()
        if google_key and settings.model_routing is not None:
            routing = settings.model_routing
            settings.model_routing = replace(
                routing,
                expansion=replace(routing.expansion, api_key=google_key),
                research=replace(routing.research, api_key=google_key),
                writing=replace(routing.writing, api_key=google_key),
            )
        return settings

    def _on_role_provider_changed(self, role: UserFacingModelRole) -> None:
        self._populate_role_model_combo(role, prefer_current=False)
        if self._initializing:
            return
        self.refresh_context_budget_readout()

    def _stored_model_for_role_provider(self, role: UserFacingModelRole, provider: str) -> str:
        routing = self._ensure_model_routing()
        config = {
            UserFacingModelRole.EXPANSION: routing.expansion,
            UserFacingModelRole.RESEARCH: routing.research,
            UserFacingModelRole.WRITING: routing.writing,
        }[role]
        if config.provider != provider:
            return ""
        return config.model.strip()

    def _populate_role_model_combo(
        self,
        role: UserFacingModelRole,
        *,
        prefer_current: bool = True,
    ) -> None:
        provider = str(self.role_provider[role].currentData() or PROVIDER_NIM)
        combo = self.role_model[role]
        current = combo.currentText().strip()
        stored = self._stored_model_for_role_provider(role, provider)
        models = self._models_by_provider.get(provider, [])
        combo.blockSignals(True)
        combo.clear()
        for model in models:
            combo.addItem(model.id)
        combo.setEditable(True)
        preferred = current if prefer_current and current else stored
        if preferred:
            combo.setCurrentText(preferred)
        elif models:
            combo.setCurrentText(models[0].id)
        combo.blockSignals(False)

    def _apply_cached_models_to_ui(self) -> None:
        nim_models = self._models_by_provider.get(PROVIDER_NIM, [])
        if nim_models:
            self.settings.model_metadata = {
                model.id: self._merge_model_metadata(model.id, dict(model.metadata))
                for model in nim_models
            }
        for role in (
            UserFacingModelRole.EXPANSION,
            UserFacingModelRole.RESEARCH,
            UserFacingModelRole.WRITING,
        ):
            self._populate_role_model_combo(role)

    def _persist_nim_timeout(self, _value: float) -> None:
        self.settings.nim = self._current_nim_settings()
        save_settings(self.settings)

    def _refresh_models(self) -> None:
        settings_snapshot = self._settings_for_model_list()
        self.refresh_models_button.setEnabled(False)
        self.embedding_status.setText("Fetching model lists from NIM and Google…")
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
                    operation="model_list_start",
                    message="Refreshing provider model lists (background)",
                    details={"task_role": MODEL_LIST_TASK_ROLE.value},
                    dataset_id=dataset_id,
                )
                router = ModelRouter(settings_snapshot)
                models_by_provider: dict[str, list] = {}
                errors: dict[str, str] = {}
                for provider in (PROVIDER_NIM, PROVIDER_GOOGLE):
                    try:
                        models_by_provider[provider] = router.list_models_for_provider(provider)
                    except (NimClientError, ModelError) as exc:
                        errors[provider] = (
                            nim_error_user_message(exc)
                            if isinstance(exc, NimClientError)
                            else model_error_user_message(exc)
                        )
                return models_by_provider, errors
            finally:
                worker_conn.close()

        def on_success(result: object) -> None:
            self.refresh_models_button.setEnabled(True)
            models_by_provider, errors = result  # type: ignore[misc]
            for provider, models in models_by_provider.items():
                self._models_by_provider[provider] = list(models)
            if models_by_provider:
                self._apply_cached_models_to_ui()
                save_settings(self.settings)
                self.refresh_context_budget_readout()
            parts = []
            nim_count = len(models_by_provider.get(PROVIDER_NIM, []))
            google_count = len(models_by_provider.get(PROVIDER_GOOGLE, []))
            if nim_count:
                parts.append(f"NIM {nim_count}")
            if google_count:
                parts.append(f"Google {google_count}")
            if parts:
                summary = "Model lists refreshed (" + ", ".join(parts) + ")"
            else:
                summary = "No model lists returned"
            if errors:
                summary += " — " + "; ".join(f"{provider}: {message}" for provider, message in errors.items())
            self.embedding_status.setText(summary)
            self.logger.info(
                component="ui.settings_tab",
                operation="model_list_success",
                message="Provider model lists refreshed",
                details={
                    "nim_model_count": nim_count,
                    "google_model_count": google_count,
                    "errors": errors,
                },
            )

        def on_error(exc: BaseException) -> None:
            self.refresh_models_button.setEnabled(True)
            if isinstance(exc, (NimClientError, ModelError)):
                message = (
                    nim_error_user_message(exc)
                    if isinstance(exc, NimClientError)
                    else model_error_user_message(exc)
                )
                for combo in self.role_model.values():
                    combo.setEditable(True)
                self.embedding_status.setText(f"Model list refresh failed: {message}")
                self.logger.error(
                    component="ui.settings_tab",
                    operation="model_list_failed",
                    message=str(exc),
                    details={"error_type": exc.error_type, **getattr(exc, "details", {})},
                    exc=exc,
                )
            else:
                self.embedding_status.setText(f"Model list refresh failed: {exc}")
                self.logger.error(
                    component="ui.settings_tab",
                    operation="model_list_failed",
                    message="Unexpected model list failure",
                    exc=exc,
                )

        from message_evidence_workstation.ui.background_tasks import run_background

        run_background(self, work, on_success=on_success, on_error=on_error)

    def _merge_model_metadata(self, model_id: str, provider_metadata: dict) -> dict:
        merged = dict(provider_metadata)
        existing = self.settings.model_metadata.get(model_id, {})
        for key in ("supports_system_role", "message_role_source"):
            if key in existing:
                merged[key] = existing[key]
        return merged

    def _format_model_test_result(self, result: ModelTestResult) -> str:
        lines = [
            f"{'OK' if result.success else 'FAILED'} | {result.provider} {result.model}",
        ]
        if result.latency_ms is not None:
            lines.append(f"latency={result.latency_ms}ms")
        if result.method:
            lines.append(f"{result.method} {result.url}".strip())
        if result.success:
            lines.append(f"reply={result.response_preview!r}")
        else:
            if result.status_code is not None:
                lines.append(f"status={result.status_code}")
            if result.error_message:
                lines.append(result.error_message)
            elif result.error_type:
                lines.append(f"error_type={result.error_type}")
        return "\n".join(lines)

    def _test_role_model(self, role: UserFacingModelRole) -> None:
        model = self.role_model[role].currentText().strip()
        if not model:
            self.role_test_result[role].setText("Model test: select or enter a model first.")
            return
        self.refresh_models_button.setEnabled(False)
        self.role_test_result[role].setText(f"Testing {role.value} model {model}…")
        self.logger.info(
            component="ui.settings_tab",
            operation="model_test_start",
            message="Starting routed model test",
            details={"model": model, "role": role.value, "task_role": MODEL_TEST_TASK_ROLE.value},
        )

        def work() -> ModelTestResult:
            return self._router_from_ui().test_model(user_facing_role=role)

        def on_success(result: object) -> None:
            self.refresh_models_button.setEnabled(True)
            test_result = result  # type: ignore[assignment]
            assert isinstance(test_result, ModelTestResult)
            summary = self._format_model_test_result(test_result)
            self.role_test_result[role].setText(summary)
            if test_result.success:
                self.embedding_status.setText(
                    f"{role.value} model test OK ({test_result.latency_ms}ms): {test_result.response_preview!r}"
                )
                self.logger.info(
                    component="ui.settings_tab",
                    operation="model_test_success",
                    message="Model test succeeded",
                    details={
                        "model": test_result.model,
                        "provider": test_result.provider,
                        "role": role.value,
                        "latency_ms": test_result.latency_ms,
                        "response_preview": test_result.response_preview,
                        "task_role": MODEL_TEST_TASK_ROLE.value,
                    },
                )
            else:
                self.embedding_status.setText(f"{role.value} model test failed — see readout.")
                self.logger.error(
                    component="ui.settings_tab",
                    operation="model_test_failed",
                    message=test_result.error_message or "Model test failed",
                    details={
                        "model": test_result.model,
                        "provider": test_result.provider,
                        "role": role.value,
                        "latency_ms": test_result.latency_ms,
                        "status_code": test_result.status_code,
                        "response_body": test_result.response_body,
                        "error_type": test_result.error_type,
                        "task_role": MODEL_TEST_TASK_ROLE.value,
                    },
                )

        def on_error(exc: BaseException) -> None:
            self.refresh_models_button.setEnabled(True)
            if isinstance(exc, (NimClientError, ModelError)):
                message = (
                    nim_error_user_message(exc)
                    if isinstance(exc, NimClientError)
                    else model_error_user_message(exc)
                )
                self.role_test_result[role].setText(message)
                self.logger.error(
                    component="ui.settings_tab",
                    operation="model_test_failed",
                    message=message,
                    details=nim_error_log_details(exc) if isinstance(exc, NimClientError) else {"error_type": exc.error_type},
                    exc=exc,
                )
            else:
                self.role_test_result[role].setText(f"Model test failed: {exc}")
                self.logger.error(
                    component="ui.settings_tab",
                    operation="model_test_failed",
                    message="Unexpected model test failure",
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
            desired_average_chunk_messages=int(self.chunk_desired_average.value()),
            session_gap_hours=float(self.chunk_session_gap_hours.value()),
            use_semantic_boundaries=True,
            split_on_date_change=True,
        )

    def _on_chunking_controls_changed(self, *_args: object) -> None:
        config = self._current_chunking_config()
        self.settings.chunking = {
            "max_chars": config.max_chars,
            "semantic_similarity_threshold": config.semantic_similarity_threshold,
            "desired_average_chunk_messages": config.desired_average_chunk_messages,
            "session_gap_hours": config.session_gap_hours,
            "use_semantic_boundaries": config.use_semantic_boundaries,
            "split_on_date_change": config.split_on_date_change,
        }
        save_settings(self.settings)
        if hasattr(self, "_chunk_preview_timer"):
            self._chunk_preview_timer.start(150)

    def _apply_chunk_preview_from_metadata(self) -> None:
        """O(1) chunk preview from persisted index metadata — safe on UI thread."""
        if self.dataset_id is None:
            self.chunk_preview_label.setText("Load a dataset to preview chunk counts.")
            return
        from message_evidence_workstation.config.settings import load_settings
        from message_evidence_workstation.embeddings.index_jobs import get_ready_index

        model_id = load_settings().embedding_model
        message_row = get_ready_index(self.conn, self.dataset_id, "message", model_id)
        chunk_row = get_ready_index(self.conn, self.dataset_id, "chunk", model_id)
        message_count = int(
            self.conn.execute(
                "SELECT COUNT(*) FROM message WHERE dataset_id = ?",
                (self.dataset_id,),
            ).fetchone()[0]
        )
        if message_row is None:
            embedded = 0
        else:
            embedded = int(message_row["message_count"] or 0)
        if embedded < message_count:
            self.chunk_preview_label.setText(
                f"Build message embeddings first for semantic chunking "
                f"({embedded}/{message_count} message vectors ready)."
            )
            return
        if chunk_row is None:
            self.chunk_preview_label.setText(
                f"Message embeddings ready ({embedded}/{message_count}). Build chunk embeddings to preview chunks."
            )
            return
        import json

        chunk_meta = json.loads(chunk_row["chunking_config_json"] or "{}")
        chunk_count = int(chunk_row["chunk_count"] or chunk_meta.get("chunk_count") or 0)
        threshold = chunk_meta.get("semantic_similarity_threshold")
        threshold_text = f"{float(threshold):.2f}" if threshold is not None else "n/a"
        average = message_count / chunk_count if chunk_count else 0
        config = self._current_chunking_config()
        self.chunk_desired_average_label.setText(f"{config.desired_average_chunk_messages} messages")
        self.chunk_preview_label.setText(
            f"{chunk_count} chunks from {message_count} messages | "
            f"avg={average:.1f} msg/chunk, target={config.desired_average_chunk_messages}, "
            f"threshold={threshold_text}, gap={config.session_gap_hours:g}h, max={config.max_chars} chars"
        )

    def _update_chunk_preview(self) -> None:
        if not self.isVisible():
            return
        if self.dataset_id is None:
            self.chunk_preview_label.setText("Load a dataset to preview chunk counts.")
            return
        dataset_id = self.dataset_id
        config = self._current_chunking_config()
        self.chunk_desired_average_label.setText(f"{config.desired_average_chunk_messages} messages")
        self._chunk_preview_generation += 1
        generation = self._chunk_preview_generation
        self.chunk_preview_label.setText("Calculating chunk preview...")
        model_id = self.embedding_model.currentData()
        from message_evidence_workstation.embeddings.model_registry import get_model_spec

        spec = get_model_spec(model_id)
        embedding_model_name = spec.model_name if spec else None

        def compute_preview() -> str:
            from message_evidence_workstation.db.connection import connect
            from message_evidence_workstation.embeddings.chunking import (
                calibrated_config_for_dataset,
                count_dataset_chunks,
                message_vector_count,
            )

            worker_conn = connect(self.db_path)
            try:
                message_count = int(
                    worker_conn.execute(
                        "SELECT COUNT(*) FROM message WHERE dataset_id = ?",
                        (dataset_id,),
                    ).fetchone()[0]
                )
                vector_count = message_vector_count(
                    worker_conn, dataset_id, embedding_model_name
                )
                if vector_count < message_count:
                    return (
                        f"Build message embeddings first for semantic chunking "
                        f"({vector_count}/{message_count} message vectors ready)."
                    )
                calibrated_config = calibrated_config_for_dataset(
                    worker_conn, dataset_id, config, model_name=embedding_model_name
                )
                chunk_count = count_dataset_chunks(
                    worker_conn,
                    dataset_id,
                    config=calibrated_config,
                    model_name=embedding_model_name,
                )
                average = message_count / chunk_count if chunk_count else 0
                return (
                    f"{chunk_count} chunks from {message_count} messages | "
                    f"avg={average:.1f} msg/chunk, target={config.desired_average_chunk_messages}, "
                    f"threshold={calibrated_config.semantic_similarity_threshold:.2f}, "
                    f"gap={config.session_gap_hours:g}h, max={config.max_chars} chars"
                )
            finally:
                worker_conn.close()

        def on_success(text: str) -> None:
            if generation != self._chunk_preview_generation:
                return
            self.chunk_preview_label.setText(text)

        def on_error(exc: BaseException) -> None:
            if generation != self._chunk_preview_generation:
                return
            self.chunk_preview_label.setText(f"Chunk preview failed: {exc}")

        from message_evidence_workstation.ui.background_tasks import run_background

        run_background(
            self,
            compute_preview,
            on_success=on_success,
            on_error=on_error,
        )

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
            vector_count = message_vector_count(self.conn, self.dataset_id, spec.model_name)
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
            if self.isVisible():
                self._chunk_preview_timer.start(150)
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

