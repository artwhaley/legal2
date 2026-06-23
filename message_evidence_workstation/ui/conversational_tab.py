"""Conversational search tab — coverage-aware answering and retrieval fallback."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import Qt, Signal
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
from message_evidence_workstation.db.evidence_blocks import (
    create_evidence_block_from_conversational_candidate,
)
from message_evidence_workstation.domain.constants import CREATED_BY_CONVERSATIONAL_SEARCH
from message_evidence_workstation.embeddings.model_registry import get_model_spec
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.nim.client import NimClient, NimClientError, nim_error_user_message
from message_evidence_workstation.search.conversational_answer import (
    ANSWER_MODE_EXHAUSTIVE_WINDOW_SCAN,
    ANSWER_MODE_RETRIEVAL_FALLBACK,
    ANSWER_MODE_SESSION_COVERAGE,
    ANSWER_MODE_WHOLE_TRANSCRIPT,
    ANSWER_STRATEGY_RETRIEVAL_FALLBACK,
    ANSWER_STRATEGY_WHOLE_TRANSCRIPT,
    CandidateEvidenceBlockDraft,
    ConversationalAnswerParseError,
    ConversationalAnswerResult,
    build_dataset_transcript,
    log_answer_budget_resolved,
    resolve_answer_budget,
    resolve_answer_mode,
    run_exhaustive_window_scan_answer,
    run_whole_transcript_answer,
    run_session_coverage_answer,
)
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
    message_citation_selected = Signal(str, str)

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
        self._answer_candidates: list[CandidateEvidenceBlockDraft] = []
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
        right_layout.addWidget(QLabel("Cited message IDs"))
        self.citations_list = QListWidget()
        self.citations_list.itemDoubleClicked.connect(self._on_citation_activated)
        right_layout.addWidget(self.citations_list)
        right_layout.addWidget(QLabel("Search harness / coverage"))
        self.plan_view = QPlainTextEdit()
        self.plan_view.setReadOnly(True)
        right_layout.addWidget(self.plan_view)
        right_layout.addWidget(QLabel("Candidate evidence blocks"))
        self.results_list = QListWidget()
        self.results_list.currentRowChanged.connect(self._on_candidate_row_changed)
        right_layout.addWidget(self.results_list)
        candidate_actions = QHBoxLayout()
        self.add_candidate_button = QPushButton("Save selected evidence block")
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

    def _format_answer_result(self, result: ConversationalAnswerResult) -> str:
        lines = [
            f"Mode: {result.mode}",
            f"Messages considered: {result.coverage_summary.messages_considered}",
        ]
        if result.coverage_summary.sessions_considered:
            lines.append(f"Sessions considered: {result.coverage_summary.sessions_considered}")
            lines.append(f"Sessions inspected: {result.coverage_summary.sessions_inspected}")
            lines.append(f"Sessions skipped: {result.coverage_summary.sessions_skipped}")
        if result.coverage_summary.retrieval_assists:
            lines.append("Retrieval assists:")
            for assist in result.coverage_summary.retrieval_assists[:10]:
                lines.append(
                    f"- {assist.get('session_id')} | {assist.get('message_id')} | "
                    f"{assist.get('retrieval_method')}"
                )
        if result.cited_message_ids:
            lines.append(f"Cited message IDs: {', '.join(result.cited_message_ids)}")
        if result.uncertainties:
            lines.append("Uncertainties:")
            lines.extend(f"- {item}" for item in result.uncertainties)
        lines.append("")
        lines.append(result.answer)
        return "\n".join(lines)

    def _show_answer_result(self, result: ConversationalAnswerResult) -> None:
        self.answer_view.setPlainText(self._format_answer_result(result))
        self.citations_list.clear()
        for message_id in result.cited_message_ids:
            row = self.conn.execute(
                """
                SELECT source_thread_id
                FROM message
                WHERE dataset_id = ? AND message_id = ?
                """,
                (self.dataset_id, message_id),
            ).fetchone()
            thread_id = str(row["source_thread_id"]) if row else ""
            item = QListWidgetItem(f"{message_id} | {thread_id}")
            item.setData(Qt.ItemDataRole.UserRole, message_id)
            item.setData(Qt.ItemDataRole.UserRole + 1, thread_id)
            self.citations_list.addItem(item)
        self._answer_candidates = list(result.candidate_evidence_blocks)
        self._synthesis_candidates = []
        self.results_list.clear()
        self.add_candidate_button.setEnabled(False)
        for candidate in self._answer_candidates:
            label = f"{candidate.title} | {candidate.source_thread_id} | {candidate.core_message_id}"
            item = QListWidgetItem(label)
            item.setToolTip(candidate.summary)
            self.results_list.addItem(item)
        if self._answer_candidates:
            self.results_list.setCurrentRow(0)

    def _on_citation_activated(self, item: QListWidgetItem) -> None:
        message_id = item.data(Qt.ItemDataRole.UserRole)
        thread_id = item.data(Qt.ItemDataRole.UserRole + 1)
        if isinstance(message_id, str) and isinstance(thread_id, str) and thread_id:
            self.message_citation_selected.emit(message_id, thread_id)

    def _show_synthesis(self, synthesis: ConversationalSynthesisResult, *, mode: str) -> None:
        header = f"Mode: {mode} (lower-recall retrieval fallback)\n\n"
        self.answer_view.setPlainText(header + synthesis.answer)
        self.citations_list.clear()
        self._answer_candidates = []
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
        has_answer_candidate = 0 <= row < len(self._answer_candidates)
        has_synthesis_candidate = (
            row >= 0
            and row < len(self._synthesis_candidates)
            and self._synthesis_candidates[row].group is not None
        )
        self.add_candidate_button.setEnabled(has_answer_candidate or has_synthesis_candidate)

    def _add_selected_candidate(self) -> None:
        row = self.results_list.currentRow()
        if row < 0 or self.dataset_id is None:
            return
        if 0 <= row < len(self._answer_candidates):
            self._save_answer_candidate(self._answer_candidates[row])
            return
        if row < len(self._synthesis_candidates):
            self._add_synthesis_candidate(self._synthesis_candidates[row])

    def _save_answer_candidate(self, candidate: CandidateEvidenceBlockDraft) -> None:
        if self.dataset_id is None:
            return
        messages = repositories.list_messages_for_thread(
            self.conn,
            self.dataset_id,
            candidate.source_thread_id,
        )
        ordered_ids = [message.message_id for message in messages]
        create_evidence_block_from_conversational_candidate(
            self.conn,
            self.logger,
            dataset_id=self.dataset_id,
            source_thread_id=candidate.source_thread_id,
            ordered_message_ids=ordered_ids,
            title=candidate.title,
            summary=candidate.summary,
            core_message_id=candidate.core_message_id,
            leading_context_start_message_id=candidate.leading_context_start_message_id,
            relevant_start_message_id=candidate.relevant_start_message_id,
            relevant_end_message_id=candidate.relevant_end_message_id,
            trailing_context_end_message_id=candidate.trailing_context_end_message_id,
            highlighted_message_ids=list(candidate.highlighted_message_ids),
        )
        self.status_label.setText(
            f"Saved evidence block '{candidate.title}' to Uncategorized."
        )
        if self._category_refresh_handler is not None:
            self._category_refresh_handler()

    def _add_synthesis_candidate(self, candidate: SynthesisCandidate) -> None:
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
            self._show_synthesis(synthesis, mode=ANSWER_MODE_RETRIEVAL_FALLBACK)
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
        self.citations_list.clear()
        self._synthesis_candidates = []
        self._answer_candidates = []

        self._request_generation += 1
        generation = self._request_generation
        dataset_id = self.dataset_id
        db_path = self.db_path
        settings = load_settings()
        answer_settings = settings.answer
        nim = nim_settings_for_client(settings)
        provider_metadata = settings.nim_model_metadata.get(nim.model, {})

        transcript = build_dataset_transcript(self.conn, dataset_id)
        budget = resolve_answer_budget(
            transcript,
            answer_settings,
            nim.model or "unknown-model",
            provider_metadata=provider_metadata,
        )
        log_answer_budget_resolved(
            self.logger,
            budget=budget,
            dataset_id=dataset_id,
            strategy=answer_settings.answer_strategy,
            target_tokens=answer_settings.window_target_tokens,
            overlap_messages=answer_settings.window_overlap_messages,
        )
        if budget.decision == ANSWER_MODE_WHOLE_TRANSCRIPT:
            if (
                answer_settings.answer_strategy == ANSWER_STRATEGY_WHOLE_TRANSCRIPT
                and budget.transcript_tokens > budget.usable_input_tokens
            ):
                self.logger.warning(
                    component="ui.conversational_tab",
                    operation="whole_transcript_selected",
                    message="Whole transcript requested but token budget exceeded; routing to exhaustive scan",
                    details={
                        "transcript_tokens": budget.transcript_tokens,
                        "usable_input_tokens": budget.usable_input_tokens,
                    },
                    dataset_id=dataset_id,
                )
            else:
                self.logger.info(
                    component="ui.conversational_tab",
                    operation="whole_transcript_selected",
                    message="Selected whole transcript answering mode",
                    details={
                        "transcript_tokens": budget.transcript_tokens,
                        "usable_input_tokens": budget.usable_input_tokens,
                    },
                    dataset_id=dataset_id,
                )
        elif budget.decision == ANSWER_MODE_EXHAUSTIVE_WINDOW_SCAN:
            self.logger.info(
                component="ui.conversational_tab",
                operation="exhaustive_window_scan_selected",
                message="Selected exhaustive window scan answering mode",
                details={
                    "transcript_tokens": budget.transcript_tokens,
                    "usable_input_tokens": budget.usable_input_tokens,
                },
                dataset_id=dataset_id,
            )
        answer_mode = budget.decision
        if answer_mode == ANSWER_MODE_WHOLE_TRANSCRIPT:
            self.status_label.setText("Answering from full transcript…")
            self._run_whole_transcript_answer(
                generation,
                query,
                dataset_id,
                db_path,
                transcript,
                answer_settings,
            )
            return
        if answer_mode == ANSWER_MODE_EXHAUSTIVE_WINDOW_SCAN:
            self.status_label.setText("Answering with exhaustive transcript window scan...")
            self._ensure_message_embeddings_then(
                generation,
                dataset_id,
                db_path,
                lambda: self._run_exhaustive_window_scan_answer(
                    generation,
                    query,
                    dataset_id,
                    db_path,
                    answer_settings,
                ),
            )
            return
        if answer_mode == ANSWER_MODE_SESSION_COVERAGE:
            self.status_label.setText("Answering with session summary triage...")
            self._ensure_message_embeddings_then(
                generation,
                dataset_id,
                db_path,
                lambda: self._run_session_coverage_answer(
                    generation,
                    query,
                    dataset_id,
                    db_path,
                    answer_settings,
                ),
            )
            return
        if answer_mode == ANSWER_MODE_RETRIEVAL_FALLBACK or answer_settings.answer_strategy == ANSWER_STRATEGY_RETRIEVAL_FALLBACK:
            self._run_retrieval_fallback(generation, query, dataset_id, db_path)
            return

    def _ensure_message_embeddings_then(
        self,
        generation: int,
        dataset_id: int,
        db_path: Path,
        continuation: Callable[[], None],
    ) -> None:
        from message_evidence_workstation.embeddings.chunking import message_vector_count

        message_count = int(
            self.conn.execute(
                "SELECT COUNT(*) FROM message WHERE dataset_id = ?",
                (dataset_id,),
            ).fetchone()[0]
        )
        vector_count = message_vector_count(self.conn, dataset_id)
        if vector_count >= message_count:
            continuation()
            return

        embedding_model = load_settings().embedding_model
        spec = get_model_spec(embedding_model)
        if spec is None:
            self.status_label.setText(
                "Cannot build message embeddings automatically: unknown embedding model."
            )
            self.send_button.setEnabled(True)
            return

        self.status_label.setText(
            f"Building message embeddings for semantic session boundaries "
            f"({vector_count}/{message_count} ready)..."
        )
        job = EmbeddingJobSpec(
            job_type="message_index",
            db_path=db_path,
            dataset_id=dataset_id,
            adapter_key=spec.adapter_key,
            model_id=spec.model_id,
        )

        def on_success(result: object) -> None:
            if generation != self._request_generation:
                return
            success = bool(getattr(result, "success", False))
            count = int(getattr(result, "count", 0))
            total = int(getattr(result, "total_target", message_count) or message_count)
            if not success:
                error = str(getattr(result, "error", "unknown embedding build failure"))
                self.status_label.setText(f"Message embedding build failed: {error}")
                self.answer_view.setPlainText(
                    "Session-based answering needs message embeddings for semantic boundaries. "
                    f"Embedding build failed after {count}/{total} messages: {error}"
                )
                self.send_button.setEnabled(True)
                return
            self.status_label.setText(
                f"Message embeddings ready ({count}/{total}). Continuing answer..."
            )
            continuation()

        def on_error(exc: BaseException) -> None:
            if generation != self._request_generation:
                return
            message = f"Automatic message embedding build failed: {exc}"
            self.status_label.setText(message)
            self.answer_view.setPlainText(message)
            self.logger.error(
                component="ui.conversational_tab",
                operation="auto_message_embeddings_failed",
                message=message,
                exc=exc,
                dataset_id=dataset_id,
            )
            self.send_button.setEnabled(True)

        run_embedding_job(self, job, on_success=on_success, on_error=on_error)

    def _run_exhaustive_window_scan_answer(
        self,
        generation: int,
        query: str,
        dataset_id: int,
        db_path: Path,
        answer_settings,
    ) -> None:
        nim = nim_settings_for_client()
        app_settings = load_settings()

        def answer_work() -> ConversationalAnswerResult:
            worker_conn = connect(db_path)
            try:
                worker_logger = ProcessLogger(worker_conn, dataset_id=dataset_id)
                client = NimClient(nim)
                return run_exhaustive_window_scan_answer(
                    worker_conn,
                    worker_logger,
                    client,
                    user_query=query,
                    dataset_id=dataset_id,
                    transcript_window_padding=answer_settings.transcript_window_padding,
                    session_gap_minutes=answer_settings.session_gap_minutes,
                    answer_settings=answer_settings,
                    model_id=nim.model,
                    provider_metadata=app_settings.nim_model_metadata.get(nim.model, {}),
                    max_tokens=answer_settings.reserved_output_tokens,
                )
            finally:
                worker_conn.close()

        def on_success(result: object) -> None:
            if generation != self._request_generation:
                return
            answer = result  # type: ignore[assignment]
            self._show_answer_result(answer)
            coverage = answer.coverage_summary
            self.plan_view.setPlainText(
                f"Exhaustive window scan\n"
                f"Sessions considered: {coverage.sessions_considered}\n"
                f"Sessions inspected: {coverage.sessions_inspected}\n"
                f"Windows inspected: {coverage.windows_inspected}\n"
                f"Sessions skipped: {coverage.sessions_skipped}\n"
                f"Messages in inspected windows: {coverage.messages_considered}"
            )
            self._append_chat("Assistant", answer.answer)
            self.status_label.setText(
                f"Answer complete - mode: {answer.mode}; "
                f"{len(answer.candidate_evidence_blocks)} candidate block(s)."
            )
            self.send_button.setEnabled(True)

        def on_error(exc: BaseException) -> None:
            if generation != self._request_generation:
                return
            if isinstance(exc, ConversationalAnswerParseError):
                message = f"Exhaustive window scan answer invalid: {exc}"
            elif isinstance(exc, NimClientError):
                message = f"NIM exhaustive window scan call failed: {nim_error_user_message(exc)}"
            else:
                message = f"Exhaustive window scan answer failed: {exc}"
            self.status_label.setText(message)
            self.answer_view.setPlainText(message)
            self._append_chat("System", message)
            self.logger.error(
                component="ui.conversational_tab",
                operation="exhaustive_window_scan_answer_failed",
                message=message,
                exc=exc,
                dataset_id=self.dataset_id,
            )
            self.send_button.setEnabled(True)

        run_background(self, answer_work, on_success=on_success, on_error=on_error)

    def _run_session_coverage_answer(
        self,
        generation: int,
        query: str,
        dataset_id: int,
        db_path: Path,
        answer_settings,
    ) -> None:
        nim = nim_settings_for_client()

        def answer_work() -> ConversationalAnswerResult:
            worker_conn = connect(db_path)
            try:
                worker_logger = ProcessLogger(worker_conn, dataset_id=dataset_id)
                client = NimClient(nim)
                return run_session_coverage_answer(
                    worker_conn,
                    worker_logger,
                    client,
                    user_query=query,
                    dataset_id=dataset_id,
                    max_inspected_sessions=answer_settings.max_inspected_sessions,
                    transcript_window_padding=answer_settings.transcript_window_padding,
                    session_gap_minutes=answer_settings.session_gap_minutes,
                    max_tokens=answer_settings.reserved_output_tokens,
                )
            finally:
                worker_conn.close()

        def on_success(result: object) -> None:
            if generation != self._request_generation:
                return
            answer = result  # type: ignore[assignment]
            self._show_answer_result(answer)
            coverage = answer.coverage_summary
            self.plan_view.setPlainText(
                f"Session-coverage answer\n"
                f"Sessions considered: {coverage.sessions_considered}\n"
                f"Sessions inspected: {coverage.sessions_inspected}\n"
                f"Sessions skipped: {coverage.sessions_skipped}\n"
                f"Messages in inspected windows: {coverage.messages_considered}"
            )
            self._append_chat("Assistant", answer.answer)
            self.status_label.setText(
                f"Answer complete — mode: {answer.mode}; "
                f"{len(answer.candidate_evidence_blocks)} candidate block(s)."
            )
            self.send_button.setEnabled(True)

        def on_error(exc: BaseException) -> None:
            if generation != self._request_generation:
                return
            if isinstance(exc, ConversationalAnswerParseError):
                message = f"Session coverage answer invalid: {exc}"
            elif isinstance(exc, NimClientError):
                message = f"NIM session coverage call failed: {nim_error_user_message(exc)}"
            else:
                message = f"Session coverage answer failed: {exc}"
            self.status_label.setText(message)
            self.answer_view.setPlainText(message)
            self._append_chat("System", message)
            self.logger.error(
                component="ui.conversational_tab",
                operation="session_coverage_answer_failed",
                message=message,
                exc=exc,
                dataset_id=self.dataset_id,
            )
            self.send_button.setEnabled(True)

        run_background(self, answer_work, on_success=on_success, on_error=on_error)

    def _run_whole_transcript_answer(
        self,
        generation: int,
        query: str,
        dataset_id: int,
        db_path: Path,
        transcript,
        answer_settings,
    ) -> None:
        nim = nim_settings_for_client()

        def answer_work() -> ConversationalAnswerResult:
            worker_conn = connect(db_path)
            try:
                worker_logger = ProcessLogger(worker_conn, dataset_id=dataset_id)
                client = NimClient(nim)
                return run_whole_transcript_answer(
                    worker_conn,
                    worker_logger,
                    client,
                    user_query=query,
                    dataset_id=dataset_id,
                    transcript=transcript,
                    max_tokens=answer_settings.reserved_output_tokens,
                )
            finally:
                worker_conn.close()

        def on_success(result: object) -> None:
            if generation != self._request_generation:
                return
            answer = result  # type: ignore[assignment]
            self._show_answer_result(answer)
            self.plan_view.setPlainText(
                f"Whole-transcript answer\n"
                f"Messages considered: {answer.coverage_summary.messages_considered}\n"
                f"Threads: {', '.join(answer.coverage_summary.source_thread_ids)}"
            )
            self._append_chat("Assistant", answer.answer)
            self.status_label.setText(
                f"Answer complete — mode: {answer.mode}; "
                f"{len(answer.candidate_evidence_blocks)} candidate block(s)."
            )
            self.send_button.setEnabled(True)

        def on_error(exc: BaseException) -> None:
            if generation != self._request_generation:
                return
            if isinstance(exc, ConversationalAnswerParseError):
                message = f"Answer output invalid: {exc}"
            elif isinstance(exc, NimClientError):
                message = f"NIM answer call failed: {nim_error_user_message(exc)}"
            else:
                message = f"Conversational answer failed: {exc}"
            self.status_label.setText(message)
            self.answer_view.setPlainText(message)
            self._append_chat("System", message)
            self.logger.error(
                component="ui.conversational_tab",
                operation="whole_transcript_answer_failed",
                message=message,
                exc=exc,
                dataset_id=self.dataset_id,
            )
            self.send_button.setEnabled(True)

        run_background(self, answer_work, on_success=on_success, on_error=on_error)

    def _run_retrieval_fallback(
        self,
        generation: int,
        query: str,
        dataset_id: int,
        db_path: Path,
    ) -> None:
        self.status_label.setText("Planning retrieval fallback (lower recall)…")
        sort_index = dict(self._sort_index_by_message)
        embedding_model = load_settings().embedding_model
        spec = get_model_spec(embedding_model)
        nim = nim_settings_for_client()

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
