"""LLM-generated transcript session summaries."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from message_evidence_workstation.llm.router import ModelRouter
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.nim.model_runs import run_nim_chat
from message_evidence_workstation.nim.prompts import RUN_TYPE_SESSION_SUMMARY
from message_evidence_workstation.search.session_map import (
    SUMMARY_STATUS_FAILED,
    SUMMARY_STATUS_PENDING,
    SUMMARY_STATUS_READY,
    TranscriptSession,
    list_sessions,
    serialize_session_transcript,
    update_session_summary,
)
from message_evidence_workstation.search.tool_runner import _extract_json_object

SUMMARY_FIELDS = (
    "topics",
    "people",
    "events",
    "commitments",
    "conflicts",
    "appointments",
    "money",
    "parenting_school",
    "medical",
    "travel",
    "notable_quotes",
)


class SessionSummaryParseError(ValueError):
    pass


def empty_summary() -> dict[str, Any]:
    return {field: [] for field in SUMMARY_FIELDS}


def build_session_summary_user_content(session: TranscriptSession, transcript_text: str) -> str:
    return json.dumps(
        {
            "session_id": session.session_id,
            "source_thread_id": session.source_thread_id,
            "calendar_date": session.calendar_date,
            "participants": session.participants,
            "message_count": session.message_count,
            "transcript": transcript_text,
        },
        ensure_ascii=False,
    )


def parse_session_summary_response(content: str) -> dict[str, Any]:
    try:
        payload = _extract_json_object(content)
    except Exception as exc:
        raise SessionSummaryParseError(f"Session summary response is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise SessionSummaryParseError("Session summary response must be a JSON object")
    summary = empty_summary()
    for field in SUMMARY_FIELDS:
        value = payload.get(field, [])
        if field == "notable_quotes":
            if not isinstance(value, list):
                value = []
            summary[field] = [
                item
                for item in value
                if isinstance(item, dict) and str(item.get("message_id", "")).strip()
            ]
        else:
            if not isinstance(value, list):
                value = []
            summary[field] = [str(item).strip() for item in value if str(item).strip()]
    return summary


def generate_session_summary(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    router: ModelRouter,
    *,
    dataset_id: int,
    session: TranscriptSession,
) -> dict[str, Any]:
    transcript_text, _ = serialize_session_transcript(conn, dataset_id, session)
    result = run_nim_chat(
        conn,
        logger,
        router,
        run_type=RUN_TYPE_SESSION_SUMMARY,
        user_content=build_session_summary_user_content(session, transcript_text),
        dataset_id=dataset_id,
    )
    summary = parse_session_summary_response(result.content)
    update_session_summary(
        conn,
        dataset_id=dataset_id,
        session_id=session.session_id,
        summary_json=summary,
        summary_status=SUMMARY_STATUS_READY,
    )
    session.summary_json = summary
    session.summary_status = SUMMARY_STATUS_READY
    return summary


def ensure_session_summaries(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    router: ModelRouter | None,
    dataset_id: int,
    *,
    regenerate: bool = False,
) -> list[TranscriptSession]:
    sessions = list_sessions(conn, dataset_id)
    if router is None:
        return sessions
    for session in sessions:
        if session.summary_status == SUMMARY_STATUS_READY and not regenerate:
            continue
        try:
            generate_session_summary(
                conn,
                logger,
                router,
                dataset_id=dataset_id,
                session=session,
            )
        except Exception as exc:
            update_session_summary(
                conn,
                dataset_id=dataset_id,
                session_id=session.session_id,
                summary_json=session.summary_json or empty_summary(),
                summary_status=SUMMARY_STATUS_FAILED,
            )
            logger.warning(
                component="search.session_summaries",
                operation="session_summary_failed",
                message=f"Failed to summarize session {session.session_id}",
                details={"session_id": session.session_id},
                exc=exc,
                dataset_id=dataset_id,
            )
    return list_sessions(conn, dataset_id)
