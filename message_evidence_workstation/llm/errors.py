"""Normalized model router errors."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from message_evidence_workstation.nim.client import NimClientError, nim_error_user_message


@dataclass(slots=True)
class ModelError(Exception):
    message: str
    error_type: str
    provider: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.message


RETRYABLE_HTTP_STATUSES = frozenset({408, 429, 500, 502, 503, 504})
NON_RETRYABLE_ERROR_TYPES = frozenset(
    {
        "missing_api_key",
        "missing_model",
        "auth_failure",
        "invalid_request",
        "safety_block",
        "context_limit",
    }
)


def model_error_from_nim(exc: NimClientError, *, provider: str = "nim") -> ModelError:
    return ModelError(
        message=nim_error_user_message(exc),
        error_type=exc.error_type,
        provider=provider,
        details=dict(exc.details),
    )


def is_retryable_model_error(exc: ModelError) -> bool:
    if exc.error_type in NON_RETRYABLE_ERROR_TYPES:
        return False
    if exc.error_type == "http_error":
        status = exc.details.get("status_code")
        if isinstance(status, int):
            return status in RETRYABLE_HTTP_STATUSES
        return False
    if exc.error_type in {"timeout", "connection_error"}:
        return True
    return False


def model_error_user_message(exc: ModelError) -> str:
    if exc.provider == "nim" and exc.error_type in {
        "timeout",
        "http_error",
        "connection_error",
        "missing_api_key",
        "missing_model",
    }:
        nim_exc = NimClientError(exc.message, error_type=exc.error_type, details=exc.details)
        return nim_error_user_message(nim_exc)
    if exc.error_type == "missing_api_key":
        return f"{exc.provider} API key is missing. Add a key in Setup / Settings or set the env var."
    if exc.error_type == "missing_model":
        return f"{exc.provider} model is not configured."
    if exc.error_type == "auth_failure":
        return f"{exc.provider} authentication failed: {exc.message}"
    if exc.error_type == "quota_exceeded":
        return f"{exc.provider} quota exceeded: {exc.message}"
    if exc.error_type == "safety_block":
        return f"{exc.provider} blocked the response for safety or policy reasons."
    if exc.error_type == "timeout":
        seconds = exc.details.get("timeout_seconds", "?")
        return f"{exc.provider} request timed out after {seconds}s."
    return exc.message
