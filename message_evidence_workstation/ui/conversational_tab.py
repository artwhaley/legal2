"""Conversational search tab — planner, harness, and synthesis (T17–T18)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from message_evidence_workstation.config.settings import load_settings, nim_settings_for_client
from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db import repositories
from message_evidence_workstation.domain.constants import CREATED_BY_CONVERSATIONAL_SEARCH
from message_evidence_workstation.embeddings.model_registry import get_model_spec
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.nim.client import NimClient, NimClientError, nim_error_user_message
from message_evidence_workstation.search.synthesis import (
    ConversationalSynthesisResult,
    SynthesisCandidate,
    SynthesisParseError,
    run_conversational_synthesis,
)
from message_evidence_workstation.search.tool_runner import (
    ConversationalPlanExecution,
    PlannerParseError,
    SearchPlannerPlan,
    fetch_conversational_plan,
)
from message_evidence_workstation.ui.background_tasks import run_background
from message_evidence_workstation.ui.embedding_worker import EmbeddingJobSpec, run_embedding_job


class ConversationalTab(QWidget):
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
        self._sort_index_by_message: dict[str, int] = {}
        self._request_generation = 0
        self._synthesis_candidates: list[SynthesisCandidate] = []
        self._category_refresh_handler: Callable[[], None] | None = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Conversational Interface"))

        self.status_label = QLabel("Load a dataset to search.")
        layout.addWidget(self.status_label)

        splitter = QSplitter()
        self.chat_log = QPlainTextEdit()
        self.chat_log.setReadOnly(True)
        self.chat_log.setPlaceholderText("Chat history appears here.")
        splitter.addWidget(self.chat_log)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(QLabel("Answer"))
        self.answer_view = QPlainTextEdit()
        self.answer_view.setReadOnly(True)
        self.answer_view.setPlaceholderText("Synthesized answer appears here.")
        right_layout.addWidget(self.answer_view)
        right_layout.addWidget(QLabel("Search harness"))
        self.plan_view = QPlainTextEdit()
        self.plan_view.setReadOnly(True)
        right_layout.addWidget(self.plan_view)
        right_layout.addWidget(QLabel("Candidate conversations"))
        self.results_list = QListWidget()
        self.results_list.currentRowChanged.connect(self._on_candidate_row_changed)
        right_layout.addWidget(self.results_list)
        candidate_actions = QHBoxLayout()
        self.add_candidate_button = QPushButton("Add selected to category…")
        self.add_candidate_button.setEnabled(False)
        self.add_candidate_button.clicked.connect(self._add_selected_candidate)
        candidate_actions.addWidget(self.add_candidate_button)
        candidate_actions.addStretch()
        right_layout.addLayout(candidate_actions)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        layout.addWidget(splitter, stretch=1)

        input_row = QWidget()
        input_layout = QVBoxLayout(input_row)
        input_layout.setContentsMargins(0, 0, 0, 0)
        self.query_input = QLineEdit()
        self.query_input.setPlaceholderText("Ask a natural-language question about the dataset…")
        self.query_input.returnPressed.connect(self._submit_query)
        input_layout.addWidget(self.query_input)
        self.send_button = QPushButton("Send")
        self.send_button.clicked.connect(self._submit_query)
        input_layout.addWidget(self.send_button)
        layout.addWidget(input_row)

    def set_dataset(self, dataset_id: int | None) -> None:
        self.dataset_id = dataset_id
        self._sort_index_by_message = {}
        self.results_list.clear()
        self.plan_view.clear()
        if dataset_id is None:
            self.status_label.setText("Load a dataset to search.")
            self.send_button.setEnabled(False)
            return
        rows = self.conn.execute(
            "SELECT message_id, sort_index FROM message WHERE dataset_id = ?",
            (dataset_id,),
        ).fetchall()
        self._sort_index_by_message = {row["message_id"]: row["sort_index"] for row in rows}
        self.status_label.setText("Ready. Configure NIM in Setup / Settings.")
        self.send_button.setEnabled(True)

    def set_category_refresh_handler(self, handler: Callable[[], None]) -> None:
        self._category_refresh_handler = handler

    def _append_chat(self, role: str, text: str) -> None:
        self.chat_log.appendPlainText(f"{role}: {text}")
        self.chat_log.appendPlainText("")

    def _format_execution(self, execution: ConversationalPlanExecution) -> str:
        lines = [
            f"Strategy: {execution.plan.strategy_summary}",
            "",
            "Retrieval harness (all methods always run):",
        ]
        for item in execution.tool_results:
            status = "ok" if item.success else f"FAILED: {item.error}"
            counts = []
            if item.hit_count:
                counts.append(f"hits={item.hit_count}")
            if item.message_count:
                counts.append(f"messages={item.message_count}")
            if item.group_count:
                counts.append(f"groups={item.group_count}")
            count_text = f" ({', '.join(counts)})" if counts else ""
            lines.append(
                f"- {item.tool} {json.dumps(item.arguments)} — {status}{count_text} [{item.duration_ms}ms]"
            )
        lines.append("")
        lines.append(f"Accumulated hits: {len(execution.accumulated_hits)}")
        lines.append(f"Grouped results: {len(execution.grouped_results)}")
        return "\n".join(lines)

    def _show_synthesis(self, synthesis: ConversationalSynthesisResult) -> None:
        self.answer_view.setPlainText(synthesis.answer)
        self._synthesis_candidates = [
            candidate for candidate in synthesis.candidates if candidate.group is not None
        ]
        self.results_list.clear()
        self.add_candidate_button.setEnabled(False)
        for candidate in self._synthesis_candidates:
            group = candidate.group
            if group is None:
                continue
            methods = ", ".join(sorted(group.retrieval_methods))
            confidence = candidate.confidence or "medium"
            label = f"[{confidence}] {candidate.title} | {group.source_thread_id} | {methods}"
            item = QListWidgetItem(label)
            tooltip_parts = [candidate.explanation, group.snippet]
            item.setToolTip("\n\n".join(part for part in tooltip_parts if part))
            self.results_list.addItem(item)
        if self._synthesis_candidates:
            self.results_list.setCurrentRow(0)

    def _on_candidate_row_changed(self, row: int) -> None:
        self.add_candidate_button.setEnabled(
            row >= 0
            and row < len(self._synthesis_candidates)
            and self._synthesis_candidates[row].group is not None
        )

    def _add_selected_candidate(self) -> None:
        row = self.results_list.currentRow()
        if row < 0 or row >= len(self._synthesis_candidates):
            return
        candidate = self._synthesis_candidates[row]
        group = candidate.group
        if group is None or self.dataset_id is None:
            return
        categories = repositories.list_categories(self.conn, self.dataset_id)
        if not categories:
            QMessageBox.information(
                self,
                "No categories",
                "Create a category in the sidebar first, then add this candidate.",
            )
            return
        from PySide6.QtWidgets import QInputDialog

        names = [category.name for category in categories]
        choice, ok = QInputDialog.getItem(
            self,
            "Choose Category",
            "Add candidate conversation to category:",
            names,
            editable=False,
        )
        if not ok:
            return
        category = categories[names.index(choice)]
        hit_ids = [hit.message_id for hit in group.hits]
        merge_id = repositories.find_merge_candidate_for_search_drop(
            self.conn,
            category_id=category.category_id,
            source_thread_id=group.source_thread_id,
            hit_message_ids=hit_ids,
        )
        repositories.create_workstation_conversation_from_search(
            self.conn,
            self.logger,
            dataset_id=self.dataset_id,
            category_id=category.category_id,
            source_thread_id=group.source_thread_id,
            primary_hit_message_id=group.primary_hit_message_id,
            title=candidate.title or group.title,
            hits=[asdict(hit) for hit in group.hits],
            merge_into_conversation_id=merge_id,
            created_by=CREATED_BY_CONVERSATIONAL_SEARCH,
        )
        self.status_label.setText(f"Added candidate to category '{category.name}'.")
        self.logger.info(
            component="ui.conversational_tab",
            operation="candidate_added_to_category",
            message="User added synthesis candidate to category",
            details={
                "category_id": category.category_id,
                "group_id": candidate.group_id,
                "merged": merge_id is not None,
            },
            dataset_id=self.dataset_id,
        )
        if self._category_refresh_handler is not None:
            self._category_refresh_handler()

    def _show_execution(self, execution: ConversationalPlanExecution) -> None:
        self.plan_view.setPlainText(self._format_execution(execution))
        self.results_list.clear()
        for group in execution.grouped_results:
            methods = ", ".join(sorted(group.retrieval_methods))
            item = QListWidgetItem(
                f"{group.title} | {group.source_thread_id} | {len(group.hits)} hits | {methods}"
            )
            item.setToolTip(group.snippet)
            self.results_list.addItem(item)
        if not execution.grouped_results and execution.accumulated_hits:
            for hit in execution.accumulated_hits[:50]:
                item = QListWidgetItem(
                    f"{hit.message_id} | {hit.retrieval_method} | {hit.snippet or hit.body[:120]}"
                )
                self.results_list.addItem(item)

    def _finish_execution(
        self,
        generation: int,
        query: str,
        plan: SearchPlannerPlan,
        execution: ConversationalPlanExecution,
    ) -> None:
        if generation != self._request_generation:
            return
        self._show_execution(execution)
        failed = [item.tool for item in execution.tool_results if not item.success]
        if failed:
            self.status_label.setText(
                f"Harness finished with step failures: {', '.join(failed)}. Synthesizing…"
            )
        else:
            self.status_label.setText("Search harness finished. Synthesizing answer…")
        self._run_synthesis(generation, query, plan, execution)

    def _run_synthesis(
        self,
        generation: int,
        query: str,
        plan: SearchPlannerPlan,
        execution: ConversationalPlanExecution,
    ) -> None:
        dataset_id = self.dataset_id
        if dataset_id is None:
            return
        db_path = self.db_path
        nim = nim_settings_for_client()

        def synthesis_work() -> ConversationalSynthesisResult:
            worker_conn = connect(db_path)
            try:
                worker_logger = ProcessLogger(worker_conn, dataset_id=dataset_id)
                client = NimClient(nim)
                return run_conversational_synthesis(
                    worker_conn,
                    worker_logger,
                    client,
                    user_query=query,
                    plan=plan,
                    execution=execution,
                    dataset_id=dataset_id,
                )
            finally:
                worker_conn.close()

        def on_success(result: object) -> None:
            if generation != self._request_generation:
                return
            synthesis = result  # type: ignore[assignment]
            self._show_synthesis(synthesis)
            self._append_chat("Assistant", synthesis.answer)
            self._append_chat("Planner", synthesis.strategy_summary)
            self.status_label.setText(
                f"Synthesis complete — {len(synthesis.candidates)} candidate conversation(s)."
            )
            self.send_button.setEnabled(True)

        def on_error(exc: BaseException) -> None:
            if generation != self._request_generation:
                return
            self._on_synthesis_error(exc, plan)

        run_background(self, synthesis_work, on_success=on_success, on_error=on_error)

    def _on_synthesis_error(self, exc: BaseException, plan: SearchPlannerPlan) -> None:
        if isinstance(exc, SynthesisParseError):
            message = f"Synthesis output invalid: {exc}"
        elif isinstance(exc, NimClientError):
            message = f"NIM synthesis call failed: {nim_error_user_message(exc)}"
        else:
            message = f"Conversational synthesis failed: {exc}"
        self.status_label.setText(message)
        self.answer_view.setPlainText(message)
        self._append_chat("System", message)
        self._append_chat("Planner", plan.strategy_summary)
        self.logger.error(
            component="ui.conversational_tab",
            operation="synthesis_failed",
            message=message,
            exc=exc,
            dataset_id=self.dataset_id,
        )
        self.send_button.setEnabled(True)

    def _submit_query(self) -> None:
        query = self.query_input.text().strip()
        if not query:
            return
        if self.dataset_id is None:
            self.status_label.setText("Load a dataset before searching.")
            return
        nim = nim_settings_for_client()
        if not nim.model:
            self.status_label.setText(
                "NIM model not configured — open Setup / Settings and select a model."
            )
            return

        self._append_chat("You", query)
        self.query_input.clear()
        self.send_button.setEnabled(False)
        self.status_label.setText("Planning search strategy…")
        self.answer_view.clear()
        self._synthesis_candidates = []

        self._request_generation += 1
        generation = self._request_generation
        dataset_id = self.dataset_id
        db_path = self.db_path
        sort_index = dict(self._sort_index_by_message)
        embedding_model = load_settings().embedding_model
        spec = get_model_spec(embedding_model)

        def plan_work() -> SearchPlannerPlan:
            worker_conn = connect(db_path)
            try:
                worker_logger = ProcessLogger(worker_conn, dataset_id=dataset_id)
                client = NimClient(nim)
                return fetch_conversational_plan(
                    worker_conn,
                    worker_logger,
                    client,
                    user_query=query,
                    dataset_id=dataset_id,
                )
            finally:
                worker_conn.close()

        def on_plan_success(plan: object) -> None:
            if generation != self._request_generation:
                return
            planner_plan = plan  # type: ignore[assignment]
            self.status_label.setText("Running full retrieval harness…")
            if spec is None:
                self._finish_with_plan_only(generation, query, planner_plan, db_path, dataset_id, sort_index)
                return
            job = EmbeddingJobSpec(
                job_type="conversational_search",
                db_path=db_path,
                dataset_id=dataset_id,
                adapter_key=spec.adapter_key,
                model_id=spec.model_id,
                harness_user_query=query,
                harness_strategy_summary=planner_plan.strategy_summary,
                harness_extra_queries=list(planner_plan.extra_search_queries),
                sort_index_by_message=sort_index,
            )
            run_embedding_job(
                self,
                job,
                on_success=lambda execution: self._finish_execution(
                    generation,
                    query,
                    planner_plan,
                    execution,  # type: ignore[arg-type]
                ),
                on_error=lambda exc: self._on_harness_error(generation, exc),
            )

        def on_plan_error(exc: BaseException) -> None:
            if generation != self._request_generation:
                return
            self._on_planner_error(exc)

        run_background(self, plan_work, on_success=on_plan_success, on_error=on_plan_error)

    def _finish_with_plan_only(
        self,
        generation: int,
        query: str,
        plan: SearchPlannerPlan,
        db_path: Path,
        dataset_id: int,
        sort_index: dict[str, int],
    ) -> None:
        from message_evidence_workstation.search.tool_runner import ToolRunnerDeps, execute_full_search_harness

        def harness_work() -> ConversationalPlanExecution:
            worker_conn = connect(db_path)
            try:
                worker_logger = ProcessLogger(worker_conn, dataset_id=dataset_id)
                client = NimClient(nim_settings_for_client())
                deps = ToolRunnerDeps(nim_client=client)
                return execute_full_search_harness(
                    worker_conn,
                    worker_logger,
                    dataset_id=dataset_id,
                    user_query=query,
                    plan=plan,
                    deps=deps,
                    sort_index_by_message=sort_index,
                )
            finally:
                worker_conn.close()

        run_background(
            self,
            harness_work,
            on_success=lambda execution: self._finish_execution(generation, query, plan, execution),
            on_error=lambda exc: self._on_harness_error(generation, exc),
        )

    def _on_planner_error(self, exc: BaseException) -> None:
        if isinstance(exc, PlannerParseError):
            message = f"Planner output invalid: {exc}"
        elif isinstance(exc, NimClientError):
            message = f"NIM planner call failed: {nim_error_user_message(exc)}"
        else:
            message = f"Conversational search failed: {exc}"
        self.status_label.setText(message)
        self.plan_view.setPlainText(message)
        self._append_chat("System", message)
        self.logger.error(
            component="ui.conversational_tab",
            operation="planner_failed",
            message=message,
            exc=exc,
            dataset_id=self.dataset_id,
        )
        self.send_button.setEnabled(True)

    def _on_harness_error(self, generation: int, exc: BaseException) -> None:
        if generation != self._request_generation:
            return
        message = f"Search harness failed: {exc}"
        self.status_label.setText(message)
        self.plan_view.setPlainText(message)
        self._append_chat("System", message)
        self.logger.error(
            component="ui.conversational_tab",
            operation="harness_failed",
            message=message,
            exc=exc,
            dataset_id=self.dataset_id,
        )
        self.send_button.setEnabled(True)
