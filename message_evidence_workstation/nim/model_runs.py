"""ModelRun audit records for routed model calls."""

from __future__ import annotations

import json
import sqlite3
import traceback
from typing import Any

from message_evidence_workstation.config.settings import load_settings
from message_evidence_workstation.llm.errors import ModelError, model_error_user_message
from message_evidence_workstation.llm.router import ModelRouter
from message_evidence_workstation.llm.task_roles import (
    task_role_for_run_type,
    user_facing_role_for_task_role,
)
from message_evidence_workstation.llm.types import ModelChatResult
from message_evidence_workstation.logging_ui.process_log import ProcessLogger, utc_now_iso
from message_evidence_workstation.nim.client import NimChatResult, NimClientError
from message_evidence_workstation.nim.message_roles import (
    MESSAGE_LAYOUT_FOLDED_USER,
    build_chat_messages,
    build_whole_transcript_cache_messages,
)
from message_evidence_workstation.nim.prompts import get_active_prompt


def record_model_run(
    conn: sqlite3.Connection,
    *,
    dataset_id: int | None,
    run_type: str,
    provider: str,
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
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            dataset_id,
            run_type,
            provider,
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


def _messages_input_summary(messages: list[dict[str, str]] | None) -> str:
    if not messages:
        return ""
    return "\n\n".join(str(message.get("content", "")) for message in messages)


def _cache_usage_details(raw_response: dict) -> dict[str, int]:
    usage = raw_response.get("usage")
    if not isinstance(usage, dict):
        return {}
    details: dict[str, int] = {}
    for key in ("prompt_cache_hit_tokens", "prompt_cache_miss_tokens"):
        value = usage.get(key)
        if isinstance(value, int):
            details[key] = value
    return details


def _usage_audit_payload(result: ModelChatResult) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "provider": result.provider.value,
        "task_role": result.task_role.value,
        "model": result.model,
        "latency_ms": result.latency_ms,
        "message_layout": result.message_layout,
    }
    if result.max_output_tokens is not None:
        payload["max_output_tokens"] = result.max_output_tokens
    if result.timeout_seconds is not None:
        payload["timeout_seconds"] = result.timeout_seconds
    if result.usage is not None:
        payload["usage"] = {
            "input_tokens": result.usage.input_tokens,
            "output_tokens": result.usage.output_tokens,
            "total_tokens": result.usage.total_tokens,
        }
    return payload


def _to_nim_chat_result(result: ModelChatResult) -> NimChatResult:
    return NimChatResult(
        content=result.content,
        raw_response=result.raw_response,
        latency_ms=result.latency_ms,
        message_layout=result.message_layout,
    )


def _resolve_router(router: ModelRouter) -> ModelRouter:
    return router


def _model_error_as_nim(exc: ModelError) -> NimClientError:
    return NimClientError(
        model_error_user_message(exc),
        error_type=exc.error_type,
        details=exc.details,
    )


def run_nim_chat(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    router: ModelRouter,
    *,
    run_type: str,
    user_content: str | None = None,
    messages: list[dict[str, str]] | None = None,
    dataset_id: int | None = None,
    max_tokens: int | None = None,
    timeout_seconds: float | None = None,
) -> NimChatResult:
    prompt = get_active_prompt(conn, run_type)
    if prompt is None:
        raise RuntimeError(f"No active prompt template for run_type={run_type}")
    task_role = task_role_for_run_type(run_type)
    user_facing_role = user_facing_role_for_task_role(task_role)
    include_system_role = True
    if messages is None:
        if user_content is None:
            raise ValueError("run_nim_chat requires user_content or messages")
        messages = build_chat_messages(
            prompt["body"],
            user_content,
            include_system_role=include_system_role,
        )
    input_summary = user_content if user_content is not None else _messages_input_summary(messages)
    resolved_router = _resolve_router(router)
    role_config = resolved_router._role_config_for_task(task_role)
    request_payload = resolved_router.request_metadata(
        task_role=task_role,
        messages=messages,
        max_output_tokens=max_tokens,
        timeout_seconds=timeout_seconds,
    )
    request_payload["prompt_version"] = prompt["version"]
    request_payload["run_type"] = run_type
    if role_config.provider == "nim":
        request_payload["stream"] = resolved_router.settings.nim.streaming
        request_payload["endpoint"] = "POST /chat/completions"
    logger.info(
        component="nim.model_runs",
        operation="model_call_start",
        message=f"Starting routed model call for {run_type}",
        details={
            "run_type": run_type,
            "task_role": task_role.value,
            "user_facing_role": user_facing_role.value if user_facing_role else None,
            "prompt_version": prompt["version"],
            "model": role_config.model,
            "provider": role_config.provider,
        },
        dataset_id=dataset_id,
    )
    try:
        routed = resolved_router.chat_for_run_type(
            run_type=run_type,
            messages=messages,
            max_output_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
        )
        result = _to_nim_chat_result(routed)
        response_payload = dict(result.raw_response)
        response_payload["_router_audit"] = _usage_audit_payload(routed)
        record_model_run(
            conn,
            dataset_id=dataset_id,
            run_type=run_type,
            provider=role_config.provider,
            model=routed.model,
            prompt_template_id=int(prompt["prompt_template_id"]),
            input_summary=input_summary[:500],
            raw_request_json=request_payload,
            raw_response_json=response_payload,
            latency_ms=result.latency_ms,
        )
        logger.info(
            component="nim.model_runs",
            operation="model_call_success",
            message=f"Model call succeeded for {run_type}",
            details={
                "latency_ms": result.latency_ms,
                "message_layout": result.message_layout,
                "provider": role_config.provider,
                **_cache_usage_details(result.raw_response),
            },
            dataset_id=dataset_id,
        )
        if result.message_layout == MESSAGE_LAYOUT_FOLDED_USER:
            logger.warning(
                component="nim.model_runs",
                operation="system_role_folded",
                message="Model rejected system role; folded prompt into user message",
                details={"run_type": run_type, "model": routed.model},
                dataset_id=dataset_id,
            )
        return result
    except ModelError as exc:
        record_model_run(
            conn,
            dataset_id=dataset_id,
            run_type=run_type,
            provider=role_config.provider,
            model=role_config.model,
            prompt_template_id=int(prompt["prompt_template_id"]),
            input_summary=input_summary[:500],
            raw_request_json=request_payload,
            raw_response_json={"error": exc.message, "details": exc.details},
            latency_ms=None,
            error_type=exc.error_type,
            error_message=exc.message,
            stack_trace="".join(traceback.format_exception(exc)),
        )
        logger.error(
            component="nim.model_runs",
            operation="model_call_failed",
            message=exc.message,
            details={"run_type": run_type, "error_type": exc.error_type, **exc.details},
            exc=exc,
            dataset_id=dataset_id,
        )
        raise _model_error_as_nim(exc) from exc
    except NimClientError as exc:
        record_model_run(
            conn,
            dataset_id=dataset_id,
            run_type=run_type,
            provider=role_config.provider,
            model=role_config.model,
            prompt_template_id=int(prompt["prompt_template_id"]),
            input_summary=input_summary[:500],
            raw_request_json=request_payload,
            raw_response_json={"error": str(exc), "details": exc.details},
            latency_ms=None,
            error_type=exc.error_type,
            error_message=str(exc),
            stack_trace="".join(traceback.format_exception(exc)),
        )
        logger.error(
            component="nim.model_runs",
            operation="model_call_failed",
            message=str(exc),
            details={"run_type": run_type, "error_type": exc.error_type, **exc.details},
            exc=exc,
            dataset_id=dataset_id,
        )
        raise
