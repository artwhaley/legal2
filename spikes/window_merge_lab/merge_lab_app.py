"""PySide6 GUI spike for Window Merge Lab."""

from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path
from threading import Thread
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from PySide6 import QtCore, QtGui, QtWidgets

from message_evidence_workstation.config.settings import load_settings

from spikes.window_merge_lab.data_loader import (
    INPUTS_DIR,
    RICH_PATH,
    extract_scan_result,
    get_window_summary,
    load_compact_windows,
    load_scan_windows,
)
from spikes.window_merge_lab.strategies import (
    EXPECTED_CALL_COUNTS,
    STRATEGY_DESCRIPTIONS,
    STRATEGY_REGISTRY,
    _save_outputs,
)
from spikes.window_merge_lab.evaluator import evaluate_strategy_outputs

SPIKE_DIR = Path(__file__).resolve().parent
OUTPUTS_DIR = SPIKE_DIR / "outputs"
CRASH_LOG = SPIKE_DIR / "crash.log"


class ActivityLog(QtWidgets.QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumBlockCount(10000)

    def log(self, message: str) -> None:
        ts = time.strftime("%H:%M:%S")
        self.appendPlainText(f"[{ts}] {message}")
        self.ensureCursorVisible()


class SourceWindowTable(QtWidgets.QTableWidget):
    selectionChangedSignal = QtCore.Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(7)
        self.setHorizontalHeaderLabels(
            ["Run ID", "Window", "Output chars", "Ranges", "Parse", "Latency", "Error"]
        )
        self.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.horizontalHeader().setStretchLastSection(True)
        self.itemSelectionChanged.connect(self._on_selection_changed)

    def populate(self, windows: list[dict]) -> None:
        self.setRowCount(len(windows))
        for i, w in enumerate(windows):
            s = get_window_summary(w)
            self.setItem(i, 0, QtWidgets.QTableWidgetItem(str(s["model_run_id"])))
            self.setItem(i, 1, QtWidgets.QTableWidgetItem(s["window_id"]))
            self.setItem(i, 2, QtWidgets.QTableWidgetItem(str(s["output_estimated_chars"])))
            self.setItem(i, 3, QtWidgets.QTableWidgetItem(str(s["range_count"])))
            self.setItem(i, 4, QtWidgets.QTableWidgetItem(s["parse_status"]))
            self.setItem(i, 5, QtWidgets.QTableWidgetItem(str(s["latency_ms"] or "")))
            self.setItem(i, 6, QtWidgets.QTableWidgetItem(s["error_type"] or ""))
        self.resizeColumnsToContents()

    def _on_selection_changed(self) -> None:
        rows = self.selectionModel().selectedRows()
        if rows:
            self.selectionChangedSignal.emit(rows[0].row())


class MergeLabWindow(QtWidgets.QMainWindow):
    log_signal = QtCore.Signal(str)
    display_result_signal = QtCore.Signal(object)
    error_signal = QtCore.Signal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Window Merge Lab")
        self.setMinimumSize(1200, 800)

        self._windows: list[dict] = []
        self._compact_windows: list[dict] = []
        self._last_result: Any = None
        self._last_output_dir: Path | None = None
        self._abort_flag = False

        self._built_messages_per_call: list[list[dict[str, str]]] | None = None
        self._built_strategy_name: str | None = None
        self._built_messages_ready: bool = False

        self._build_ui()
        self.log_signal.connect(self._log.log)
        self.display_result_signal.connect(self._display_results)
        self.error_signal.connect(self._result_error_text.setPlainText)
        self._log.log("Window Merge Lab started")

    def _build_ui(self) -> None:
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        main_layout = QtWidgets.QVBoxLayout(central)

        # Activity log first so self._log exists
        self._log = ActivityLog()

        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)

        left_panel = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)

        # Settings
        self._build_settings(left_layout)

        # Source Windows table
        src_label = QtWidgets.QLabel("Source Windows")
        src_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        left_layout.addWidget(src_label)
        self._source_table = SourceWindowTable()
        self._source_table.selectionChangedSignal.connect(self._on_window_selected)
        left_layout.addWidget(self._source_table)

        # Window detail tabs
        self._detail_tabs = QtWidgets.QTabWidget()
        self._raw_response_text = QtWidgets.QPlainTextEdit()
        self._raw_response_text.setReadOnly(True)
        self._parsed_json_text = QtWidgets.QPlainTextEdit()
        self._parsed_json_text.setReadOnly(True)
        self._compact_ranges_text = QtWidgets.QPlainTextEdit()
        self._compact_ranges_text.setReadOnly(True)
        self._detail_tabs.addTab(self._raw_response_text, "Raw Response")
        self._detail_tabs.addTab(self._parsed_json_text, "Parsed JSON")
        self._detail_tabs.addTab(self._compact_ranges_text, "Compact Ranges")
        left_layout.addWidget(self._detail_tabs)

        splitter.addWidget(left_panel)

        right_panel = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # Strategy info
        strat_label = QtWidgets.QLabel("Strategy")
        strat_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        right_layout.addWidget(strat_label)
        self._strategy_info = QtWidgets.QLabel("Select a strategy and click Build Prompt or Run Strategy")
        self._strategy_info.setWordWrap(True)
        right_layout.addWidget(self._strategy_info)

        # Prompt / Payload tabs
        prompt_label = QtWidgets.QLabel("Prompt / Payload")
        prompt_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        right_layout.addWidget(prompt_label)
        self._prompt_tabs = QtWidgets.QTabWidget()
        self._prompt_preview_text = QtWidgets.QPlainTextEdit()
        self._payload_json_text = QtWidgets.QPlainTextEdit()
        self._compact_input_text = QtWidgets.QPlainTextEdit()
        self._compact_input_text.setReadOnly(True)
        self._prompt_tabs.addTab(self._prompt_preview_text, "Prompt Preview")
        self._prompt_tabs.addTab(self._payload_json_text, "Exact JSON Payload")
        self._prompt_tabs.addTab(self._compact_input_text, "Compact Input Data")
        right_layout.addWidget(self._prompt_tabs)

        # Result tabs
        result_label = QtWidgets.QLabel("Result")
        result_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        right_layout.addWidget(result_label)
        self._result_tabs = QtWidgets.QTabWidget()
        self._result_raw_text = QtWidgets.QPlainTextEdit()
        self._result_raw_text.setReadOnly(True)
        self._result_parsed_text = QtWidgets.QPlainTextEdit()
        self._result_parsed_text.setReadOnly(True)
        self._result_readable_text = QtWidgets.QPlainTextEdit()
        self._result_readable_text.setReadOnly(True)
        self._result_eval_text = QtWidgets.QPlainTextEdit()
        self._result_eval_text.setReadOnly(True)
        self._result_error_text = QtWidgets.QPlainTextEdit()
        self._result_error_text.setReadOnly(True)
        self._result_tabs.addTab(self._result_raw_text, "Raw Response")
        self._result_tabs.addTab(self._result_parsed_text, "Parsed JSON")
        self._result_tabs.addTab(self._result_readable_text, "Readable Markdown")
        self._result_tabs.addTab(self._result_eval_text, "Evaluation")
        self._result_tabs.addTab(self._result_error_text, "Error / Traceback")
        right_layout.addWidget(self._result_tabs)

        splitter.addWidget(right_panel)
        splitter.setSizes([600, 600])
        main_layout.addWidget(splitter)

        # Activity log at bottom
        log_label = QtWidgets.QLabel("Activity Log")
        log_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        main_layout.addWidget(log_label)
        main_layout.addWidget(self._log)

    def _build_settings(self, layout: QtWidgets.QVBoxLayout) -> None:
        settings_group = QtWidgets.QGroupBox("Settings")
        grid = QtWidgets.QGridLayout(settings_group)

        row = 0
        grid.addWidget(QtWidgets.QLabel("Workspace .evw path:"), row, 0)
        self._evw_path = QtWidgets.QLineEdit(
            str(Path.home() / ".message_evidence_workstation" / "workspace.evw")
        )
        grid.addWidget(self._evw_path, row, 1)

        row += 1
        grid.addWidget(QtWidgets.QLabel("Input JSON path:"), row, 0)
        self._input_path = QtWidgets.QLineEdit(str(RICH_PATH))
        grid.addWidget(self._input_path, row, 1)

        row += 1
        grid.addWidget(QtWidgets.QLabel("Output directory:"), row, 0)
        self._output_dir = QtWidgets.QLineEdit(str(OUTPUTS_DIR))
        grid.addWidget(self._output_dir, row, 1)

        row += 1
        grid.addWidget(QtWidgets.QLabel("Strategy:"), row, 0)
        self._strategy_combo = QtWidgets.QComboBox()
        for name in STRATEGY_REGISTRY:
            self._strategy_combo.addItem(name, name)
        self._strategy_combo.currentIndexChanged.connect(self._on_strategy_changed)
        grid.addWidget(self._strategy_combo, row, 1)

        row += 1
        grid.addWidget(QtWidgets.QLabel("Provider:"), row, 0)
        self._provider_combo = QtWidgets.QComboBox()
        self._provider_combo.addItems(["settings", "nim", "google"])
        grid.addWidget(self._provider_combo, row, 1)

        row += 1
        grid.addWidget(QtWidgets.QLabel("Model override:"), row, 0)
        self._model_override = QtWidgets.QLineEdit()
        grid.addWidget(self._model_override, row, 1)

        row += 1
        grid.addWidget(QtWidgets.QLabel("Max output tokens:"), row, 0)
        self._max_tokens = QtWidgets.QSpinBox()
        self._max_tokens.setRange(256, 65536)
        self._max_tokens.setValue(4096)
        grid.addWidget(self._max_tokens, row, 1)

        row += 1
        grid.addWidget(QtWidgets.QLabel("Model context:"), row, 0)
        self._model_context = QtWidgets.QSpinBox()
        self._model_context.setRange(8192, 524288)
        self._model_context.setValue(32768)
        self._model_context.setSingleStep(8192)
        grid.addWidget(self._model_context, row, 1)

        row += 1
        grid.addWidget(QtWidgets.QLabel("Timeout seconds:"), row, 0)
        self._timeout = QtWidgets.QDoubleSpinBox()
        self._timeout.setRange(10, 3600)
        self._timeout.setValue(600.0)
        grid.addWidget(self._timeout, row, 1)

        row += 1
        self._dry_run_cb = QtWidgets.QCheckBox("Dry run (no API calls)")
        grid.addWidget(self._dry_run_cb, row, 0, 1, 2)

        row += 1
        self._no_api_cb = QtWidgets.QCheckBox("No API")
        grid.addWidget(self._no_api_cb, row, 0, 1, 2)

        row += 1
        self._include_raw_cb = QtWidgets.QCheckBox("Include raw scan text")
        grid.addWidget(self._include_raw_cb, row, 0, 1, 2)

        row += 1
        self._compact_display_cb = QtWidgets.QCheckBox("Compact display text")
        self._compact_display_cb.setChecked(True)
        grid.addWidget(self._compact_display_cb, row, 0, 1, 2)

        row += 1
        grid.addWidget(QtWidgets.QLabel("Max ranges per window:"), row, 0)
        self._max_ranges = QtWidgets.QSpinBox()
        self._max_ranges.setRange(0, 100)
        self._max_ranges.setValue(0)
        self._max_ranges.setSpecialValueText("Unlimited")
        grid.addWidget(self._max_ranges, row, 1)

        row += 1
        grid.addWidget(QtWidgets.QLabel("Merge batch size:"), row, 0)
        self._batch_size = QtWidgets.QSpinBox()
        self._batch_size.setRange(1, 10)
        self._batch_size.setValue(3)
        grid.addWidget(self._batch_size, row, 1)

        # Buttons
        btn_row = row + 1
        btn_widget = QtWidgets.QWidget()
        btn_layout = QtWidgets.QHBoxLayout(btn_widget)
        btn_layout.setContentsMargins(0, 0, 0, 0)

        self._btn_load_evw = QtWidgets.QPushButton("Load From .evw")
        self._btn_load_evw.clicked.connect(self._on_load_evw)
        btn_layout.addWidget(self._btn_load_evw)

        self._btn_load_json = QtWidgets.QPushButton("Load Input JSON")
        self._btn_load_json.clicked.connect(self._on_load_json)
        btn_layout.addWidget(self._btn_load_json)

        self._btn_save_json = QtWidgets.QPushButton("Save Input JSON")
        self._btn_save_json.clicked.connect(self._on_save_json)
        btn_layout.addWidget(self._btn_save_json)

        self._btn_build_prompt = QtWidgets.QPushButton("Build Prompt")
        self._btn_build_prompt.clicked.connect(self._on_build_prompt)
        btn_layout.addWidget(self._btn_build_prompt)

        self._btn_run_strategy = QtWidgets.QPushButton("Run Strategy")
        self._btn_run_strategy.clicked.connect(self._on_run_strategy)
        btn_layout.addWidget(self._btn_run_strategy)

        self._btn_parse = QtWidgets.QPushButton("Parse Last Result")
        self._btn_parse.clicked.connect(self._on_parse_last)
        btn_layout.addWidget(self._btn_parse)

        self._btn_evaluate = QtWidgets.QPushButton("Evaluate Outputs")
        self._btn_evaluate.clicked.connect(self._on_evaluate)
        btn_layout.addWidget(self._btn_evaluate)

        self._btn_open_folder = QtWidgets.QPushButton("Open Output Folder")
        self._btn_open_folder.clicked.connect(self._on_open_folder)
        btn_layout.addWidget(self._btn_open_folder)

        self._btn_clear_log = QtWidgets.QPushButton("Clear Log")
        self._btn_clear_log.clicked.connect(self._log.clear)
        btn_layout.addWidget(self._btn_clear_log)

        grid.addWidget(btn_widget, btn_row, 0, 1, 2)
        layout.addWidget(settings_group)

    def _on_strategy_changed(self, index: int) -> None:
        name = self._strategy_combo.itemData(index)
        desc = STRATEGY_DESCRIPTIONS.get(name, "")
        calls = EXPECTED_CALL_COUNTS.get(name, "?")
        self._strategy_info.setText(
            f"<b>{name}</b><br>{desc}<br><b>Expected calls:</b> {calls}"
        )
        self._built_messages_ready = False

    def _on_window_selected(self, row: int) -> None:
        if row < 0 or row >= len(self._windows):
            return
        w = self._windows[row]
        raw = w.get("raw_response_text", "")
        self._raw_response_text.setPlainText(raw)
        parsed = extract_scan_result(w)
        self._parsed_json_text.setPlainText(
            json.dumps(parsed, indent=2, ensure_ascii=False) if parsed else "(unparseable)"
        )
        if row < len(self._compact_windows):
            cw = self._compact_windows[row]
            ranges = cw.get("answer_ranges", [])
            compact_text = json.dumps(
                {
                    "window_id": cw.get("window_id", ""),
                    "answer_summary": cw.get("answer_summary", ""),
                    "answer_ranges": ranges,
                    "cited_message_ids": cw.get("cited_message_ids", []),
                },
                indent=2,
                ensure_ascii=False,
            )
            self._compact_ranges_text.setPlainText(compact_text)

    def _on_load_evw(self) -> None:
        path = Path(self._evw_path.text())
        if not path.exists():
            self._log.log(f"ERROR: Workspace not found: {path}")
            return
        try:
            from message_evidence_workstation.db.connection import connect
            conn = connect(path)
            try:
                from spikes.window_merge_lab.db_export import export_scan_windows
                windows = export_scan_windows(conn, run_ids=[165, 166, 167, 168, 169, 170])
                self._windows = windows
                self._compact_windows = [
                    self._make_compact(w) for w in windows
                ]
                self._source_table.populate(windows)
                self._log.log(f"Loaded {len(windows)} windows from .evw")
            finally:
                conn.close()
        except Exception as e:
            self._log.log(f"ERROR loading .evw: {e}")
            self._result_error_text.setPlainText(traceback.format_exc())

    def _make_compact(self, w: dict) -> dict:
        from spikes.window_merge_lab.data_loader import compact_from_rich
        return compact_from_rich(w)

    def _on_load_json(self) -> None:
        path_str, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Load Input JSON", str(INPUTS_DIR), "JSON Files (*.json)"
        )
        if not path_str:
            return
        path = Path(path_str)
        self._input_path.setText(str(path))
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list) and len(data) > 0:
                first = data[0]
                if "model_run_id" in first and "raw_response_text" in first:
                    self._windows = data
                    self._compact_windows = [self._make_compact(w) for w in data]
                elif "model_run_id" in first and "answer_summary" in first:
                    self._compact_windows = data
                    self._windows = []
                else:
                    self._log.log(f"WARNING: Unknown format in {path.name}")
                    return
                self._source_table.populate(self._compact_windows if self._compact_windows else self._windows)
                self._log.log(f"Loaded {len(self._compact_windows or self._windows)} windows from {path.name}")
            else:
                self._log.log(f"ERROR: Expected JSON array in {path.name}")
        except Exception as e:
            self._log.log(f"ERROR loading JSON: {e}")
            self._result_error_text.setPlainText(traceback.format_exc())

    def _on_save_json(self) -> None:
        if not self._compact_windows:
            self._log.log("ERROR: No data to save")
            return
        path_str, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save Input JSON", str(INPUTS_DIR), "JSON Files (*.json)"
        )
        if not path_str:
            return
        path = Path(path_str)
        try:
            path.write_text(
                json.dumps(self._compact_windows, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            self._log.log(f"Saved {len(self._compact_windows)} windows to {path.name}")
        except Exception as e:
            self._log.log(f"ERROR saving JSON: {e}")

    def _get_kwargs(self) -> dict:
        kwargs: dict = {}
        strategy = self._strategy_combo.currentData()
        if strategy == "one_shot_compact":
            kwargs["include_raw_scan"] = self._include_raw_cb.isChecked()
        kwargs["max_ranges_per_window"] = self._max_ranges.value()
        kwargs["model_context_tokens"] = self._model_context.value()
        kwargs["max_output_tokens"] = self._max_tokens.value()
        return kwargs

    def _on_build_prompt(self) -> None:
        data = self._compact_windows or self._windows
        if not data:
            self._log.log("ERROR: No windows loaded. Load input first.")
            return
        strategy = self._strategy_combo.currentData()
        fn = STRATEGY_REGISTRY.get(strategy)
        if not fn:
            self._log.log(f"ERROR: Unknown strategy {strategy}")
            return

        def _noop(*args, **kw):
            return "", 0

        try:
            kwargs = self._get_kwargs()
            result = fn("Show me all the times we talked about school", data, model_call=_noop, **kwargs)
            self._last_result = result
            if result.error:
                self._log.log(f"WARNING: strategy reported error during prompt build: {result.error}")
            self._built_messages_per_call = result.messages_per_call
            self._built_strategy_name = result.strategy_name
            self._built_messages_ready = True

            preview_lines = []
            for i, msgs in enumerate(result.messages_per_call):
                preview_lines.append(f"=== Call {i + 1} ===")
                for m in msgs:
                    role = m.get("role", "")
                    content = m.get("content", "")
                    preview_lines.append(f"[{role}] {content[:300]}...")
                    preview_lines.append("")
            self._prompt_preview_text.setPlainText("\n".join(preview_lines))
            self._payload_json_text.setPlainText(
                json.dumps(result.messages_per_call, indent=2, ensure_ascii=False)
            )
            compact_input_lines = []
            for i, w in enumerate(data):
                rc = len(w.get("answer_ranges", []))
                output_chars = w.get("output_estimated_chars", 0)
                wid = w.get("window_id", "")
                thread = w.get("source_thread_id", "") or wid.split("__")[0] if "__" in wid else wid
                compact_input_lines.append(
                    f"Batch {i + 1}: {wid} | thread={thread} | ~{output_chars} output chars | "
                    f"{rc} ranges | {w.get('answer_summary', '')[:100]}"
                )
            self._compact_input_text.setPlainText("\n".join(compact_input_lines))
            self._log.log(f"Built prompt for {strategy} ({result.call_count} call(s))")
        except Exception as e:
            self._log.log(f"ERROR building prompt: {e}")
            self._result_error_text.setPlainText(traceback.format_exc())

    def _collect_settings_snapshot(self) -> dict:
        return {
            "strategy": self._strategy_combo.currentData(),
            "provider": self._provider_combo.currentText(),
            "model_override": self._model_override.text().strip() or "",
            "max_output_tokens": self._max_tokens.value(),
            "model_context_tokens": self._model_context.value(),
            "timeout_seconds": self._timeout.value(),
            "dry_run": self._dry_run_cb.isChecked(),
            "no_api": self._no_api_cb.isChecked(),
            "include_raw_scan": self._include_raw_cb.isChecked(),
            "compact_display": self._compact_display_cb.isChecked(),
            "max_ranges_per_window": self._max_ranges.value(),
            "batch_size": self._batch_size.value(),
            "evw_path": self._evw_path.text(),
            "input_path": self._input_path.text(),
            "output_dir": self._output_dir.text(),
        }

    def _resolve_messages_from_gui(self) -> list[list[dict[str, str]]] | None:
        edited = self._payload_json_text.toPlainText().strip()
        if not edited:
            return self._built_messages_per_call
        try:
            parsed = json.loads(edited)
            if isinstance(parsed, list) and len(parsed) > 0:
                return parsed
        except json.JSONDecodeError:
            pass
        return None

    def _on_run_strategy(self) -> None:
        data = self._compact_windows or self._windows
        if not data:
            self._log.log("ERROR: No windows loaded. Load input first.")
            return

        strategy = self._strategy_combo.currentData()
        fn = STRATEGY_REGISTRY.get(strategy)
        if not fn:
            self._log.log(f"ERROR: Unknown strategy {strategy}")
            return
        if strategy == "deterministic_baseline":
            self._log.log("Deterministic baseline requires no API call — click Build Prompt to preview.")
            return

        dry_run = self._dry_run_cb.isChecked() or self._no_api_cb.isChecked()
        provider = self._provider_combo.currentText()
        settings_snapshot = self._collect_settings_snapshot()
        output_base = Path(self._output_dir.text())

        def model_call(messages):
            if dry_run:
                return "", 0
            from message_evidence_workstation.config.settings import (
                PROVIDER_GOOGLE, PROVIDER_NIM, ModelRoleConfig,
            )
            from message_evidence_workstation.llm.providers.nim_provider import NimModelProvider
            from message_evidence_workstation.llm.types import ModelTaskRole
            model_override = self._model_override.text().strip() or None
            config = ModelRoleConfig(
                provider=provider,
                model=model_override or "",
                max_output_tokens=self._max_tokens.value(),
                timeout_seconds=self._timeout.value(),
                temperature=0.1,
            )
            if provider == "settings":
                from message_evidence_workstation.llm.router import ModelRouter
                router = ModelRouter.from_settings()
                result = router.chat(
                    messages=messages,
                    task_role=ModelTaskRole.WINDOWED_RESULT_MERGE,
                    max_output_tokens=self._max_tokens.value(),
                    timeout_seconds=self._timeout.value(),
                    temperature=0.1,
                )
                return result.content, result.latency_ms
            elif provider == PROVIDER_NIM:
                prov = NimModelProvider(config)
            elif provider == PROVIDER_GOOGLE:
                from message_evidence_workstation.llm.providers.google_provider import GoogleModelProvider
                prov = GoogleModelProvider(config)
            else:
                raise ValueError(f"Unknown provider: {provider}")
            result = prov.chat_completion(
                messages, model=config.model or None, task_role=ModelTaskRole.WINDOWED_RESULT_MERGE,
            )
            return result.content, result.latency_ms

        def _persist_crash(exc: Exception) -> None:
            import sys as _sys
            try:
                CRASH_LOG.parent.mkdir(parents=True, exist_ok=True)
                with open(CRASH_LOG, "a", encoding="utf-8") as f:
                    f.write(f"=== {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
                    f.write(f"Strategy: {strategy}\n")
                    f.write(traceback.format_exc())
                    f.write("\n\n")
            except Exception:
                pass
            print(f"CRASH [{strategy}]: {exc}", file=_sys.stderr)

        def run():
            self._abort_flag = False
            self.log_signal.emit(f"Running {strategy} ({'dry-run' if dry_run else provider})...")
            try:
                _call_num = [0]
                def logged_model_call(msgs):
                    _call_num[0] += 1
                    self.log_signal.emit(f"  Call {_call_num[0]}...")
                    return model_call(msgs)
                kwargs = self._get_kwargs()
                result = fn("Show me all the times we talked about school", data, model_call=logged_model_call, **kwargs)
                self._last_result = result
                ts = time.strftime("%Y%m%d_%H%M%S")
                output_dir = output_base / f"{ts}_{strategy}"
                _save_outputs(
                    output_dir,
                    result.strategy_name,
                    result.messages_per_call,
                    result.responses,
                    result.latency_ms,
                    result.call_count,
                    result.last_parsed,
                    result.error,
                    planner_plans=result.planner_plans,
                )
                (output_dir / "settings_snapshot.json").write_text(
                    json.dumps(settings_snapshot, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                self._last_output_dir = output_dir
                self.log_signal.emit(
                    f"Completed: {result.call_count} calls, {result.latency_ms}ms, "
                    f"parse={'OK' if result.last_parsed else 'FAILED'}, error={result.error or 'none'}"
                )
                self.log_signal.emit(f"Output: {output_dir}")
                self.display_result_signal.emit(result)
            except Exception as e:
                _persist_crash(e)
                self.log_signal.emit(f"ERROR: {e}")
                self.error_signal.emit(traceback.format_exc())

        Thread(target=run, daemon=True).start()

    def _display_results(self, result) -> None:
        self._result_raw_text.setPlainText(
            "\n\n---\n\n".join(result.responses) if result.responses else "(no responses)"
        )
        self._result_parsed_text.setPlainText(
            json.dumps(result.last_parsed, indent=2, ensure_ascii=False) if result.last_parsed else "(unparseable)"
        )
        readable = self._parsed_to_readable(result.last_parsed) if result.last_parsed else "(no parsed result)"
        prepend = []
        if result.planner_plans:
            prepend.append("## Budget Planner")
            for p in result.planner_plans:
                mode = p.get("mode", "?")
                fmt = p.get("answer_format", "?")
                in_est = p.get("estimated_input_tokens", "?")
                out_est = p.get("estimated_output_tokens", "?")
                avail_in = p.get("available_input_tokens", "?")
                avail_out = p.get("available_output_tokens", "?")
                reason = p.get("fallback_reason")
                prepend.append(
                    f"- **Mode:** {mode} | **Format:** {fmt} | "
                    f"**Est in:** {in_est} | **Est out:** {out_est} | "
                    f"**Avail in:** {avail_in} | **Avail out:** {avail_out}"
                )
                if reason:
                    prepend.append(f"  - Fallback: {reason}")
            prepend.append("")
        if prepend:
            readable = "\n".join(prepend) + "\n" + readable
        self._result_readable_text.setPlainText(readable)
        if result.last_parsed:
            try:
                eval_text = evaluate_strategy_outputs(
                    result.last_parsed,
                    self._compact_windows or self._windows,
                    strategy_name=result.strategy_name,
                    planner_plans=result.planner_plans,
                )
                self._result_eval_text.setPlainText(eval_text)
            except Exception as e:
                self._result_eval_text.setPlainText(f"Evaluation error: {e}")
        if result.error:
            self._result_tabs.setCurrentWidget(self._result_error_text)
            self._result_error_text.setPlainText(result.error)

    def _parsed_to_readable(self, parsed: dict) -> str:
        lines = []
        lines.append(f"# {parsed.get('answer_summary', 'Merge Result')}")
        lines.append("")
        answer = parsed.get("answer", "")
        if answer:
            lines.append(answer)
            lines.append("")
        ranges = parsed.get("answer_ranges", [])
        if ranges:
            lines.append(f"## Answer Ranges ({len(ranges)})")
            lines.append("")
            for i, r in enumerate(ranges, 1):
                if isinstance(r, dict):
                    lines.append(f"### {i}. {r.get('title', 'Untitled')}")
                    lines.append(f"- **Summary:** {r.get('summary', '')}")
                    lines.append(f"- **Date:** {r.get('date_description', '')}")
                    lines.append(f"- **Hit:** `{r.get('hit_message_id', '')}`")
                    lines.append("")
        uncertainties = parsed.get("uncertainties", [])
        if uncertainties:
            lines.append("## Uncertainties")
            for u in uncertainties:
                lines.append(f"- {u}")
        return "\n".join(lines)

    def _on_parse_last(self) -> None:
        if self._last_result is None:
            self._log.log("ERROR: No last result to parse")
            return
        self._display_results(self._last_result)
        self._log.log("Re-displayed last result")

    def _on_evaluate(self) -> None:
        if not self._last_result or not self._last_result.last_parsed:
            self._log.log("ERROR: No parsed result to evaluate")
            return
        try:
            eval_text = evaluate_strategy_outputs(
                self._last_result.last_parsed, self._compact_windows or self._windows
            )
            self._result_eval_text.setPlainText(eval_text)
            self._result_tabs.setCurrentWidget(self._result_eval_text)
            self._log.log("Evaluation generated")
        except Exception as e:
            self._log.log(f"ERROR evaluating: {e}")
            self._result_error_text.setPlainText(traceback.format_exc())

    def _on_open_folder(self) -> None:
        path = self._last_output_dir or Path(self._output_dir.text())
        if path.exists():
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path)))
            self._log.log(f"Opened {path}")
        else:
            self._log.log(f"Folder does not exist: {path}")


def main() -> None:
    app = QtWidgets.QApplication(sys.argv)
    window = MergeLabWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
