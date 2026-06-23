"""Completeness audit before session-coverage synthesis."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.nim.client import NimClient
from message_evidence_workstation.nim.model_runs import run_nim_chat
from message_evidence_workstation.nim.prompts import RUN_TYPE_COVERAGE_AUDIT
from message_evidence_workstation.search.session_map import TranscriptSession
from message_evidence_workstation.search.tool_runner import _extract_json_object


@dataclass(slots=True)
class CoverageAuditResult:
    additional_session_ids: list[str]
    residual_uncertainties: list[str]
    audit_notes: str


class CoverageAuditParseError(ValueError):
    pass


def build_coverage_audit_user_content(
    *,
    user_query: str,
    sessions: list[TranscriptSession],
    classifications: dict[str, str],
    inspected_session_ids: list[str],
    skipped_sessions: list[TranscriptSession],
    retrieval_assists: list[dict[str, Any]],
) -> str:
    skipped_payload = [
        {
            "session_id": session.session_id,
            "title": session.title,
            "summary": session.summary_json or {},
            "classification": classifications.get(session.session_id),
        }
        for session in skipped_sessions
    ]
    return json.dumps(
        {
            "user_query": user_query,
            "classifications": classifications,
            "inspected_session_ids": inspected_session_ids,
            "skipped_session_summaries": skipped_payload,
            "retrieval_assists": retrieval_assists,
        },
        ensure_ascii=False,
    )


def parse_coverage_audit_response(
    content: str,
    *,
    valid_session_ids: set[str],
) -> CoverageAuditResult:
    try:
        payload = _extract_json_object(content)
    except Exception as exc:
        raise CoverageAuditParseError(f"Audit response is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise CoverageAuditParseError("Audit response must be a JSON object")
    additional_raw = payload.get("additional_session_ids") or []
    if not isinstance(additional_raw, list):
        additional_raw = []
    additional = [
        str(item).strip()
        for item in additional_raw
        if str(item).strip() in valid_session_ids
    ]
    uncertainties_raw = payload.get("residual_uncertainties") or []
    if not isinstance(uncertainties_raw, list):
        uncertainties_raw = []
    uncertainties = [str(item).strip() for item in uncertainties_raw if str(item).strip()]
    audit_notes = str(payload.get("audit_notes", "")).strip()
    return CoverageAuditResult(
        additional_session_ids=additional,
        residual_uncertainties=uncertainties,
        audit_notes=audit_notes,
    )


def run_coverage_audit(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    client: NimClient,
    *,
    user_query: str,
    dataset_id: int,
    sessions: list[TranscriptSession],
    classifications: dict[str, str],
    inspected_session_ids: list[str],
    skipped_sessions: list[TranscriptSession],
    retrieval_assists: list[dict[str, Any]],
) -> CoverageAuditResult:
    user_content = build_coverage_audit_user_content(
        user_query=user_query,
        sessions=sessions,
        classifications=classifications,
        inspected_session_ids=inspected_session_ids,
        skipped_sessions=skipped_sessions,
        retrieval_assists=retrieval_assists,
    )
    result = run_nim_chat(
        conn,
        logger,
        client,
        run_type=RUN_TYPE_COVERAGE_AUDIT,
        user_content=user_content,
        dataset_id=dataset_id,
    )
    valid_ids = {session.session_id for session in sessions}
    return parse_coverage_audit_response(result.content, valid_session_ids=valid_ids)
