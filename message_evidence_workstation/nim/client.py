"""NVIDIA NIM HTTP client."""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from message_evidence_workstation.config.settings import NimSettings
from message_evidence_workstation.nim.message_roles import (
    MESSAGE_LAYOUT_FOLDED_USER,
    fold_system_into_user,
    is_system_role_unsupported_error,
    messages_include_system_role,
    prepare_chat_messages,
    record_system_role_support,
)


@dataclass(slots=True)
class NimModelInfo:
    id: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class NimChatResult:
    content: str
    raw_response: dict[str, Any]
    latency_ms: int
    message_layout: str = "system_user"


@dataclass(slots=True)
class NimTestResult:
    success: bool
    model: str
    method: str
    path: str
    url: str
    latency_ms: int | None = None
    response_preview: str = ""
    error_type: str | None = None
    error_message: str | None = None
    response_body: str | None = None
    status_code: int | None = None


class NimClientError(Exception):
    def __init__(self, message: str, *, error_type: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.error_type = error_type
        self.details = details or {}


def nim_error_user_message(exc: NimClientError) -> str:
    if exc.error_type == "timeout":
        seconds = exc.details.get("timeout_seconds", "?")
        return (
            f"NIM timed out after {seconds}s. "
            "Increase Timeout (s) in Setup / Settings or try a faster model."
        )
    if exc.error_type == "http_error":
        status = exc.details.get("status_code", "?")
        method = exc.details.get("method", "POST")
        url = exc.details.get("url", "?")
        model = exc.details.get("model")
        body = str(exc.details.get("body", "")).strip()
        parts = [f"NIM HTTP {status}: {method} {url}"]
        if model:
            parts.append(f"model={model}")
        if body:
            parts.append(f"response: {body[:400]}")
        if status == 404 and body == "404 page not found":
            parts.append(
                "Hint: plain '404 page not found' usually means the API base URL is wrong "
                "(expected https://integrate.api.nvidia.com/v1)."
            )
        return " | ".join(parts)
    if exc.error_type == "connection_error":
        url = exc.details.get("url", "?")
        return f"NIM connection error for {url}: {exc.details.get('reason', exc)}"
    return str(exc)


def nim_error_log_details(exc: NimClientError) -> dict[str, Any]:
    return {"error_type": exc.error_type, **exc.details}


class NimClient:
    def __init__(
        self,
        settings: NimSettings,
        *,
        log_warning: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self.settings = settings
        self._log_warning = log_warning

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        if not self.settings.api_key:
            raise NimClientError(
                "NIM API key is missing",
                error_type="missing_api_key",
            )
        url = self.settings.api_base_url.rstrip("/") + path
        data = None
        headers = {
            "Authorization": f"Bearer {self.settings.api_key}",
            "Content-Type": "application/json",
        }
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        timeout = timeout_seconds if timeout_seconds is not None else self.settings.timeout_seconds
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            details: dict[str, Any] = {
                "status_code": exc.code,
                "body": error_body,
                "url": url,
                "method": method,
                "path": path,
            }
            if payload is not None and "model" in payload:
                details["model"] = payload["model"]
            raise NimClientError(
                f"NIM HTTP error {exc.code}",
                error_type="http_error",
                details=details,
            ) from exc
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, (TimeoutError, socket.timeout)) or "timed out" in str(reason).lower():
                raise NimClientError(
                    "NIM request timed out",
                    error_type="timeout",
                    details={
                        "url": url,
                        "method": method,
                        "path": path,
                        "timeout_seconds": timeout,
                    },
                ) from exc
            raise NimClientError(
                f"NIM connection error: {exc.reason}",
                error_type="connection_error",
                details={
                    "url": url,
                    "method": method,
                    "path": path,
                    "reason": str(exc.reason),
                },
            ) from exc
        except TimeoutError as exc:
            raise NimClientError(
                "NIM request timed out",
                error_type="timeout",
                details={
                    "url": url,
                    "method": method,
                    "path": path,
                    "timeout_seconds": timeout,
                },
            ) from exc

    def list_models(self) -> list[NimModelInfo]:
        payload = self._request("GET", "/models")
        models = payload.get("data", payload.get("models", []))
        results: list[NimModelInfo] = []
        for item in models:
            model_id = item.get("id") or item.get("name")
            if model_id:
                metadata = dict(item) if isinstance(item, dict) else {}
                results.append(NimModelInfo(id=str(model_id), metadata=metadata))
        return results

    def chat_completion(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        timeout_seconds: float | None = None,
    ) -> NimChatResult:
        selected_model = model
        if not selected_model:
            raise NimClientError("NIM model is not configured", error_type="missing_model")
        prepared_messages, message_layout = prepare_chat_messages(selected_model, messages)
        try:
            return self._chat_completion_with_messages(
                prepared_messages,
                model=selected_model,
                max_tokens=max_tokens,
                timeout_seconds=timeout_seconds,
                message_layout=message_layout,
            )
        except NimClientError as exc:
            if (
                is_system_role_unsupported_error(exc)
                and message_layout != MESSAGE_LAYOUT_FOLDED_USER
                and messages_include_system_role(messages)
            ):
                record_system_role_support(selected_model, False)
                folded_messages = fold_system_into_user(messages)
                if self._log_warning is not None:
                    self._log_warning(
                        "Model rejected system role; folded prompt into user message",
                        {
                            "model": selected_model,
                            "message_count_before": len(messages),
                            "message_count_after": len(folded_messages),
                            "original_error": str(exc),
                        },
                    )
                return self._chat_completion_with_messages(
                    folded_messages,
                    model=selected_model,
                    max_tokens=max_tokens,
                    timeout_seconds=timeout_seconds,
                    message_layout=MESSAGE_LAYOUT_FOLDED_USER,
                )
            raise

    def _chat_completion_with_messages(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        max_tokens: int | None,
        timeout_seconds: float | None,
        message_layout: str,
    ) -> NimChatResult:
        body = {
            "model": model,
            "messages": messages,
            "temperature": self.settings.temperature,
            "max_tokens": max_tokens if max_tokens is not None else self.settings.max_output_tokens,
            "stream": self.settings.streaming,
        }
        started = time.perf_counter()
        payload = self._request("POST", "/chat/completions", payload=body, timeout_seconds=timeout_seconds)
        latency_ms = int((time.perf_counter() - started) * 1000)
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise NimClientError(
                "Unexpected NIM chat completion response shape",
                error_type="invalid_response",
                details={"payload": payload},
            ) from exc
        return NimChatResult(
            content=str(content),
            raw_response=payload,
            latency_ms=latency_ms,
            message_layout=message_layout,
        )

    def test_model(
        self,
        *,
        model: str | None = None,
        timeout_seconds: float | None = None,
    ) -> NimTestResult:
        """Minimal chat completion ping for connectivity / model entitlement checks."""
        selected_model = model
        if not selected_model:
            raise NimClientError("NIM model is not configured", error_type="missing_model")
        path = "/chat/completions"
        url = self.settings.api_base_url.rstrip("/") + path
        messages = [{"role": "user", "content": "Reply with exactly: ok"}]
        max_tokens = 16
        started = time.perf_counter()
        try:
            result = self.chat_completion(
                messages,
                model=selected_model,
                max_tokens=max_tokens,
                timeout_seconds=timeout_seconds,
            )
            latency_ms = int((time.perf_counter() - started) * 1000)
            return NimTestResult(
                success=True,
                model=selected_model,
                method="POST",
                path=path,
                url=url,
                latency_ms=latency_ms,
                response_preview=result.content.strip()[:200],
            )
        except NimClientError as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            return NimTestResult(
                success=False,
                model=selected_model,
                method=str(exc.details.get("method", "POST")),
                path=str(exc.details.get("path", path)),
                url=str(exc.details.get("url", url)),
                latency_ms=latency_ms,
                error_type=exc.error_type,
                error_message=nim_error_user_message(exc),
                response_body=str(exc.details.get("body", "")).strip() or None,
                status_code=int(exc.details["status_code"])
                if exc.details.get("status_code") is not None
                else None,
            )
