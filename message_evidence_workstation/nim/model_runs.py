"""ModelRun audit records for NIM calls."""

from __future__ import annotations

import json
import sqlite3
import traceback
from typing import Any

from message_evidence_workstation.logging_ui.process_log import ProcessLogger, utc_now_iso
from message_evidence_workstation.nim.client import NimChatResult, NimClient, NimClientError
from message_evidence_workstation.nim.context_limits import (
    is_context_limit_error,
    parse_context_window_from_error,
    record_learned_model_context,
)
from message_evidence_workstation.nim.message_roles import MESSAGE_LAYOUT_FOLDED_USER, build_chat_messages
from message_evidence_workstation.nim.prompts import get_active_prompt


def record_model_run(
    conn: sqlite3.Connection,
    *,
    dataset_id: int | None,
    run_type: str,
    model: str,
    prompt_template_id: int | None,
    input_summary: str,
    raw_request_json: dict[str, Any],
    raw_response_json: dict[str, Any],
    latency_ms: int | None,
    error_type: str | None = None,
    error_message: str | None = None,
    stack_trace: str | None = None,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO model_run (
            dataset_id, run_type, provider, model, prompt_template_id, input_summary,
            raw_request_json, raw_response_json, created_at, latency_ms,
            error_type, error_message, stack_trace
        ) VALUES (?, ?, 'nvidia_nim', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            dataset_id,
            run_type,
            model,
            prompt_template_id,
            input_summary,
            json.dumps(raw_request_json),
            json.dumps(raw_response_json),
            utc_now_iso(),
            latency_ms,
            error_type,
            error_message,
            stack_trace,
        ),
    )
    conn.commit()
    return int(cursor.lastrowid)


def run_nim_chat(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    client: NimClient,
    *,
    run_type: str,
    user_content: str,
    dataset_id: int | None = None,
    max_tokens: int | None = None,
    timeout_seconds: float | None = None,
) -> NimChatResult:
    prompt = get_active_prompt(conn, run_type)
    if prompt is None:
        raise RuntimeError(f"No active prompt template for run_type={run_type}")
    include_system_role = True  # per-model folding handled in NimClient.chat_completion
    messages = build_chat_messages(
        prompt["body"],
        user_content,
        include_system_role=include_system_role,
    )
    request_payload = {
        "model": client.settings.model,
        "messages": messages,
        "temperature": client.settings.temperature,
        "max_tokens": max_tokens if max_tokens is not None else client.settings.max_output_tokens,
        "stream": client.settings.streaming,
        "timeout_seconds": timeout_seconds if timeout_seconds is not None else client.settings.timeout_seconds,
        "endpoint": "POST /chat/completions",
        "api_base_url": client.settings.api_base_url,
    }
    logger.info(
        component="nim.model_runs",
        operation="nim_call_start",
        message=f"Starting NIM call for {run_type}",
        details={
            "run_type": run_type,
            "prompt_version": prompt["version"],
            "model": client.settings.model,
            "method": "POST",
            "path": "/chat/completions",
            "url": client.settings.api_base_url.rstrip("/") + "/chat/completions",
        },
        dataset_id=dataset_id,
    )
    try:
        result = client.chat_completion(
            messages,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
        )
        record_model_run(
            conn,
            dataset_id=dataset_id,
            run_type=run_type,
            model=client.settings.model,
            prompt_template_id=int(prompt["prompt_template_id"]),
            input_summary=user_content[:500],
            raw_request_json=request_payload,
            raw_response_json=result.raw_response,
            latency_ms=result.latency_ms,
        )
        logger.info(
            component="nim.model_runs",
            operation="nim_call_success",
            message=f"NIM call succeeded for {run_type}",
            details={
                "latency_ms": result.latency_ms,
                "message_layout": result.message_layout,
            },
            dataset_id=dataset_id,
        )
        if result.message_layout == MESSAGE_LAYOUT_FOLDED_USER:
            logger.warning(
                component="nim.model_runs",
                operation="system_role_folded",
                message="Model rejected system role; folded prompt into user message",
                details={"run_type": run_type, "model": client.settings.model},
                dataset_id=dataset_id,
            )
        return result
    except NimClientError as exc:
        if is_context_limit_error(exc):
            learned = parse_context_window_from_error(str(exc.details.get("body", "")))
            if learned and client.settings.model:
                record_learned_model_context(client.settings.model, learned)
        record_model_run(
            conn,
            dataset_id=dataset_id,
            run_type=run_type,
            model=client.settings.model,
            prompt_template_id=int(prompt["prompt_template_id"]),
            input_summary=user_content[:500],
            raw_request_json=request_payload,
            raw_response_json={"error": str(exc), "details": exc.details},
            latency_ms=None,
            error_type=exc.error_type,
            error_message=str(exc),
            stack_trace="".join(traceback.format_exception(exc)),
        )
        logger.error(
            component="nim.model_runs",
            operation="nim_call_failed",
            message=str(exc),
            details={"run_type": run_type, "error_type": exc.error_type, **exc.details},
            exc=exc,
            dataset_id=dataset_id,
        )
        raise
