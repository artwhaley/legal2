"""Conversational search tab — coverage-aware answering."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QMimeData, QPoint, Qt, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from message_evidence_workstation.config.settings import (
    is_role_configured,
    load_settings,
    resolve_role_model,
)
from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.embeddings.model_registry import get_model_spec
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.llm.router import ModelRouter
from message_evidence_workstation.llm.types import UserFacingModelRole
from message_evidence_workstation.nim.context_limits import (
    is_context_limit_error,
    parse_context_window_from_error,
)
from message_evidence_workstation.nim.client import (
    NimClientError,
    nim_error_log_details,
    nim_error_user_message,
)
from message_evidence_workstation.search.conversational_answer import (
    ANSWER_MODE_EXHAUSTIVE_WINDOW_SCAN,
    ANSWER_MODE_SESSION_COVERAGE,
    ANSWER_MODE_WHOLE_TRANSCRIPT,
    ANSWER_STRATEGY_WHOLE_TRANSCRIPT,
    AnswerBudget,
    AnswerRangeDraft,
    ConversationalAnswerParseError,
    ConversationalAnswerResult,
    build_dataset_transcript,
    log_answer_budget_resolved,
    resolve_answer_budget,
    run_exhaustive_window_scan_answer,
    run_whole_transcript_answer,
    run_session_coverage_answer,
)
from message_evidence_workstation.search.result_models import GroupedSearchResult, SearchHit
from message_evidence_workstation.ui.background_tasks import run_background
from message_evidence_workstation.ui.embedding_worker import EmbeddingJobSpec, run_embedding_job
from message_evidence_workstation.ui.evidence_block_transcript_widget import EvidenceBlockTranscriptWidget
from message_evidence_workstation.ui.simple_search_tab import MIME_SEARCH_RESULT


@dataclass(slots=True)
class ConversationResultEntry:
    turn_index: int
    result_index: int
    group: GroupedSearchResult
    button: "AnswerRangeLinkButton"


class AnswerRangeLinkButton(QPushButton):
    navigate_requested = Signal()
    create_requested = Signal()
    drag_requested = Signal(QPoint)

    def __init__(self, text: str, *, tooltip: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._press_pos: QPoint | None = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlat(True)
        self.setStyleSheet(
            "text-align: left; padding: 0; border: none; color: #0b57d0; "
            "text-decoration: underline;"
        )
        if tooltip:
            self.setToolTip(tooltip)

    def mousePressEvent(self, event) -> None:  # noqa: ANN001
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: ANN001
        if (
            self._press_pos is not None
            and event.buttons() & Qt.MouseButton.LeftButton
            and (event.position().toPoint() - self._press_pos).manhattanLength() >= 8
        ):
            self.drag_requested.emit(self._press_pos)
            self._press_pos = None
            return
        super().mouseMoveEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: ANN001
        if event.button() == Qt.MouseButton.LeftButton:
            self.create_requested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


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
        self._conversation_results: list[ConversationResultEntry] = []
        self._last_query_text = ""
        self._category_refresh_handler: Callable[[], None] | None = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Conversational Interface"))

        self.status_label = QLabel("Load a dataset to search.")
        layout.addWidget(self.status_label)

        splitter = QSplitter(Qt.Orientation.Vertical)
        stream_panel = QWidget()
        stream_layout = QVBoxLayout(stream_panel)
        stream_layout.setContentsMargins(0, 0, 0, 0)
        self.stream_scroll = QScrollArea()
        self.stream_scroll.setWidgetResizable(True)
        self.stream_scroll.setFrameShape(QFrame.Shape.StyledPanel)
        self.stream_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.stream_content = QWidget()
        self.stream_content_layout = QVBoxLayout(self.stream_content)
        self.stream_content_layout.setContentsMargins(12, 12, 12, 12)
        self.stream_content_layout.setSpacing(12)
        self.stream_content_layout.addStretch(1)
        self.stream_scroll.setWidget(self.stream_content)
        stream_layout.addWidget(self.stream_scroll)
        splitter.addWidget(stream_panel)

        transcript_panel = QWidget()
        transcript_layout = QVBoxLayout(transcript_panel)
        transcript_layout.setContentsMargins(0, 0, 0, 0)
        transcript_layout.addWidget(QLabel("Evidence transcript"))
        self.transcript_widget = EvidenceBlockTranscriptWidget(conn, logger, transcript_panel)
        self.transcript_widget.evidence_block_created.connect(self._on_evidence_block_created)
        transcript_layout.addWidget(self.transcript_widget, stretch=1)
        splitter.addWidget(transcript_panel)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 4)
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
        self._conversation_results = []
        self._last_query_text = ""
        self._clear_stream()
        self.transcript_widget.set_dataset(dataset_id)
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

    def _clear_stream(self) -> None:
        while self.stream_content_layout.count() > 1:
            item = self.stream_content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _scroll_stream_to_bottom(self) -> None:
        bar = self.stream_scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _append_system_message(self, text: str) -> None:
        card = QFrame()
        card.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 12, 12, 12)
        label = QLabel(f"System:\n{text}")
        label.setWordWrap(True)
        layout.addWidget(label)
        self.stream_content_layout.insertWidget(self.stream_content_layout.count() - 1, card)
        self._scroll_stream_to_bottom()

    def _result_bullet_text(
        self,
        result: ConversationalAnswerResult,
        group: GroupedSearchResult,
    ) -> str:
        if result.answer_format == "brief":
            return group.title or group.snippet or group.primary_hit_message_id
        return group.summary or group.title or group.snippet or group.primary_hit_message_id

    def _add_stream_turn(
        self,
        *,
        user_text: str,
        assistant_summary: str,
        result: ConversationalAnswerResult | None = None,
    ) -> None:
        turn_index = 0
        if self._conversation_results:
            turn_index = max(entry.turn_index for entry in self._conversation_results) + 1
        card = QFrame()
        card.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        user_label = QLabel(f"You:\n{user_text}")
        user_label.setWordWrap(True)
        layout.addWidget(user_label)

        assistant_label = QLabel(f"Assistant:\n{assistant_summary}")
        assistant_label.setWordWrap(True)
        layout.addWidget(assistant_label)

        if result is not None:
            result_groups = self._groups_from_answer_ranges(result.answer_ranges)
            for result_index, group in enumerate(result_groups):
                row = QWidget()
                row_layout = QHBoxLayout(row)
                row_layout.setContentsMargins(0, 0, 0, 0)
                row_layout.setSpacing(6)
                row_layout.addWidget(QLabel("•"), 0, Qt.AlignmentFlag.AlignTop)
                button = AnswerRangeLinkButton(
                    self._result_bullet_text(result, group),
                    tooltip=group.hits[0].snippet if group.hits else "",
                )
                row_layout.addWidget(button, stretch=1)
                entry = ConversationResultEntry(
                    turn_index=turn_index,
                    result_index=result_index,
                    group=group,
                    button=button,
                )
                button.navigate_requested.connect(
                    lambda e=entry: self._navigate_to_entry(
                        e,
                        source_action="answer_stream_click",
                    )
                )
                button.clicked.connect(lambda _checked=False, b=button: b.navigate_requested.emit())
                button.create_requested.connect(
                    lambda e=entry: self._create_evidence_block_for_entry(
                        e,
                        source_action="answer_stream_double_click",
                    )
                )
                button.drag_requested.connect(lambda _pos, e=entry: self.start_drag_for_entry(e))
                self._conversation_results.append(entry)
                layout.addWidget(row)

            if result.uncertainties:
                uncertainty_lines = "\n".join(f"- {item}" for item in result.uncertainties)
                uncertainties = QLabel(f"Uncertainties:\n{uncertainty_lines}")
                uncertainties.setWordWrap(True)
                layout.addWidget(uncertainties)

        self.stream_content_layout.insertWidget(self.stream_content_layout.count() - 1, card)
        self._scroll_stream_to_bottom()

    def _show_answer_result(self, result: ConversationalAnswerResult) -> None:
        self._add_stream_turn(
            user_text=self._last_query_text,
            assistant_summary=result.answer_summary or result.answer or "No answer returned.",
            result=result,
        )

    def _message_details(self, message_id: str) -> dict[str, str]:
        if self.dataset_id is None:
            return {"sender_display": "", "timestamp": "", "body": ""}
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

    def _groups_from_answer_ranges(
        self,
        ranges: list[AnswerRangeDraft],
    ) -> list[GroupedSearchResult]:
        groups: list[GroupedSearchResult] = []
        for index, answer_range in enumerate(ranges):
            details = self._message_details(answer_range.hit_message_id)
            hit = SearchHit(
                message_id=answer_range.hit_message_id,
                source_thread_id=answer_range.source_thread_id,
                match_type="answer",
                retrieval_method="conversational_answer",
                query_text=self._last_query_text,
                matched_term="",
                sender_display=details["sender_display"],
                timestamp=details["timestamp"],
                body=details["body"],
                snippet=(
                    answer_range.display_text
                    or answer_range.summary
                    or details["body"]
                ),
            )
            label = " ".join(
                part
                for part in (answer_range.date_description, answer_range.display_text)
                if part
            ).strip()
            groups.append(
                GroupedSearchResult(
                    group_id=f"answer_range_{index}_{answer_range.hit_message_id}",
                    source_thread_id=answer_range.source_thread_id,
                    primary_hit_message_id=answer_range.hit_message_id,
                    hits=[hit],
                    title=label or answer_range.title,
                    snippet=(label or answer_range.summary or details["body"])[:160],
                    retrieval_methods={"conversational_answer"},
                    relevant_start_message_id=answer_range.start_message_id,
                    relevant_end_message_id=answer_range.end_message_id,
                    leading_context_start_message_id=self._context_start_for_range(answer_range),
                    trailing_context_end_message_id=self._context_end_for_range(answer_range),
                    summary=answer_range.summary,
                )
            )
        return groups

    def _thread_order(self, source_thread_id: str) -> list[str]:
        if self.dataset_id is None:
            return []
        rows = self.conn.execute(
            """
            SELECT message_id
            FROM message
            WHERE dataset_id = ? AND source_thread_id = ?
            ORDER BY sort_index
            """,
            (self.dataset_id, source_thread_id),
        ).fetchall()
        return [str(row["message_id"]) for row in rows]

    def _context_start_for_range(self, answer_range: AnswerRangeDraft) -> str:
        ordered_ids = self._thread_order(answer_range.source_thread_id)
        if answer_range.start_message_id not in ordered_ids:
            return answer_range.start_message_id
        start_index = ordered_ids.index(answer_range.start_message_id)
        return ordered_ids[max(0, start_index - 3)]

    def _context_end_for_range(self, answer_range: AnswerRangeDraft) -> str:
        ordered_ids = self._thread_order(answer_range.source_thread_id)
        if answer_range.end_message_id not in ordered_ids:
            return answer_range.end_message_id
        end_index = ordered_ids.index(answer_range.end_message_id)
        return ordered_ids[min(len(ordered_ids) - 1, end_index + 3)]

    def _navigate_to_entry(
        self,
        entry: ConversationResultEntry,
        *,
        source_action: str,
    ) -> None:
        group = entry.group
        self.transcript_widget.load_source_thread(
            group.source_thread_id,
            source_action=source_action,
        )
        self.transcript_widget.focus_message(
            group.primary_hit_message_id,
            source_action=source_action,
        )

    def _create_evidence_block_for_entry(
        self,
        entry: ConversationResultEntry,
        *,
        source_action: str,
    ) -> None:
        group = entry.group
        self._navigate_to_entry(entry, source_action=source_action)
        block = self.transcript_widget.create_evidence_block_for_answer_range(
            hit_message_id=group.primary_hit_message_id,
            relevant_start_message_id=group.relevant_start_message_id,
            relevant_end_message_id=group.relevant_end_message_id,
            leading_context_start_message_id=(
                group.leading_context_start_message_id or group.relevant_start_message_id
            ),
            trailing_context_end_message_id=(
                group.trailing_context_end_message_id or group.relevant_end_message_id
            ),
            title=group.title or group.snippet or group.primary_hit_message_id,
            summary=group.summary or group.snippet,
            source_action=source_action,
        )
        if block is None:
            return
        self.status_label.setText(f"Saved evidence block '{block.title}' to Uncategorized.")

    def _on_evidence_block_created(self, _evidence_block_id: int) -> None:
        if self._category_refresh_handler is not None:
            self._category_refresh_handler()

    def start_drag_for_entry(self, entry: ConversationResultEntry) -> None:
        group = entry.group
        mime = QMimeData()
        mime.setData(MIME_SEARCH_RESULT, json.dumps(group.to_drag_payload()).encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)

    def _submit_query(self) -> None:
        query = self.query_input.text().strip()
        if not query:
            return
        if self.dataset_id is None:
            self.status_label.setText("Load a dataset before searching.")
            return
        settings = load_settings()
        if not is_role_configured(settings, UserFacingModelRole.WRITING):
            self.status_label.setText(
                "Writing model not configured — open Setup / Settings and assign a Writing model."
            )
            return

        self._last_query_text = query
        self.query_input.clear()
        self.send_button.setEnabled(False)
        self.status_label.setText("Resolving answer mode…")

        self._request_generation += 1
        generation = self._request_generation
        dataset_id = self.dataset_id
        db_path = self.db_path
        settings = load_settings()
        answer_settings = settings.answer
        writing_model = resolve_role_model(settings, UserFacingModelRole.WRITING)
        provider_metadata = settings.model_metadata.get(writing_model, {})

        transcript = build_dataset_transcript(self.conn, dataset_id)
        budget = resolve_answer_budget(
            transcript,
            answer_settings,
            writing_model or "unknown-model",
            nim_settings=settings.nim,
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
            if answer_settings.answer_strategy == ANSWER_STRATEGY_WHOLE_TRANSCRIPT:
                escalation = (
                    "Transcript exceeds model context budget; "
                    "switching to exhaustive window scan."
                )
                self.logger.warning(
                    component="ui.conversational_tab",
                    operation="whole_transcript_budget_escalation",
                    message=escalation,
                    details={
                        "transcript_tokens": budget.transcript_tokens,
                        "usable_input_tokens": budget.usable_input_tokens,
                    },
                    dataset_id=dataset_id,
                )
                self._append_system_message(escalation)
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
                budget,
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
                self._append_system_message(
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
            self._append_system_message(message)
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
        app_settings = load_settings()
        writing_model = resolve_role_model(app_settings, UserFacingModelRole.WRITING)

        def answer_work() -> ConversationalAnswerResult:
            worker_conn = connect(db_path)
            try:
                worker_logger = ProcessLogger(worker_conn, dataset_id=dataset_id)
                router = ModelRouter(app_settings)
                return run_exhaustive_window_scan_answer(
                    worker_conn,
                    worker_logger,
                    router,
                    user_query=query,
                    dataset_id=dataset_id,
                    session_gap_minutes=answer_settings.session_gap_minutes,
                    answer_settings=answer_settings,
                    model_id=writing_model,
                    provider_metadata=app_settings.model_metadata.get(writing_model, {}),
                )
            finally:
                worker_conn.close()

        def on_success(result: object) -> None:
            if generation != self._request_generation:
                return
            answer = result  # type: ignore[assignment]
            self._show_answer_result(answer)
            self.status_label.setText(
                f"Answer complete - mode: {answer.mode}; "
                f"{len(answer.answer_ranges)} answer hit(s)."
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
            self._append_system_message(message)
            self.logger.error(
                component="ui.conversational_tab",
                operation="exhaustive_window_scan_answer_failed",
                message=message,
                details=nim_error_log_details(exc) if isinstance(exc, NimClientError) else None,
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
        app_settings = load_settings()

        def answer_work() -> ConversationalAnswerResult:
            worker_conn = connect(db_path)
            try:
                worker_logger = ProcessLogger(worker_conn, dataset_id=dataset_id)
                router = ModelRouter(app_settings)
                return run_session_coverage_answer(
                    worker_conn,
                    worker_logger,
                    router,
                    user_query=query,
                    dataset_id=dataset_id,
                    session_gap_minutes=answer_settings.session_gap_minutes,
                    max_tokens=app_settings.nim.max_output_tokens,
                )
            finally:
                worker_conn.close()

        def on_success(result: object) -> None:
            if generation != self._request_generation:
                return
            answer = result  # type: ignore[assignment]
            self._show_answer_result(answer)
            self.status_label.setText(
                f"Answer complete — mode: {answer.mode}; "
                f"{len(answer.answer_ranges)} answer hit(s)."
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
            self._append_system_message(message)
            self.logger.error(
                component="ui.conversational_tab",
                operation="session_coverage_answer_failed",
                message=message,
                details=nim_error_log_details(exc) if isinstance(exc, NimClientError) else None,
                exc=exc,
                dataset_id=self.dataset_id,
            )
            self.send_button.setEnabled(True)

        run_background(self, answer_work, on_success=on_success, on_error=on_error)

    def _recover_from_context_limit_error(
        self,
        exc: NimClientError,
        *,
        generation: int,
        query: str,
        dataset_id: int,
        db_path: Path,
        answer_settings,
    ) -> bool:
        if not is_context_limit_error(exc):
            return False
        learned = parse_context_window_from_error(str(exc.details.get("body", "")))
        settings = load_settings()
        model_id = resolve_role_model(settings, UserFacingModelRole.WRITING) or "unknown-model"
        self.logger.warning(
            component="ui.conversational_tab",
            operation="context_limit_auto_recovery",
            message="Model context limit exceeded; retrying with exhaustive window scan",
            details={
                **nim_error_log_details(exc),
                "learned_context_tokens": learned,
                "model_id": model_id,
            },
            dataset_id=dataset_id,
        )
        self.status_label.setText("Model context limit reached — switching to windowed scan…")
        self._append_system_message(
            "Model context limit reached; automatically retrying with exhaustive window scan.",
        )
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
        return True

    def _run_whole_transcript_answer(
        self,
        generation: int,
        query: str,
        dataset_id: int,
        db_path: Path,
        transcript,
        answer_settings,
        budget: AnswerBudget,
    ) -> None:
        app_settings = load_settings()

        def answer_work() -> ConversationalAnswerResult:
            worker_conn = connect(db_path)
            try:
                worker_logger = ProcessLogger(worker_conn, dataset_id=dataset_id)
                router = ModelRouter(app_settings)
                return run_whole_transcript_answer(
                    worker_conn,
                    worker_logger,
                    router,
                    user_query=query,
                    dataset_id=dataset_id,
                    transcript=transcript,
                    max_tokens=budget.max_output_tokens,
                )
            finally:
                worker_conn.close()

        def on_success(result: object) -> None:
            if generation != self._request_generation:
                return
            answer = result  # type: ignore[assignment]
            self._show_answer_result(answer)
            self.status_label.setText(
                f"Answer complete — mode: {answer.mode}; "
                f"{len(answer.answer_ranges)} answer hit(s)."
            )
            self.send_button.setEnabled(True)

        def on_error(exc: BaseException) -> None:
            if generation != self._request_generation:
                return
            if isinstance(exc, NimClientError) and self._recover_from_context_limit_error(
                exc,
                generation=generation,
                query=query,
                dataset_id=dataset_id,
                db_path=db_path,
                answer_settings=answer_settings,
            ):
                return
            if isinstance(exc, ConversationalAnswerParseError):
                message = f"Answer output invalid: {exc}"
            elif isinstance(exc, NimClientError):
                message = f"NIM answer call failed: {nim_error_user_message(exc)}"
            else:
                message = f"Conversational answer failed: {exc}"
            self.status_label.setText(message)
            self._append_system_message(message)
            self.logger.error(
                component="ui.conversational_tab",
                operation="whole_transcript_answer_failed",
                message=message,
                details=nim_error_log_details(exc) if isinstance(exc, NimClientError) else None,
                exc=exc,
                dataset_id=self.dataset_id,
            )
            self.send_button.setEnabled(True)

        run_background(self, answer_work, on_success=on_success, on_error=on_error)
