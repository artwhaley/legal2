"""NVIDIA NIM HTTP client."""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from message_evidence_workstation.config.settings import NimSettings


@dataclass(slots=True)
class NimModelInfo:
    id: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class NimChatResult:
    content: str
    raw_response: dict[str, Any]
    latency_ms: int


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
            "Increase Timeout (s) in Setup / Settings (up to 600) or try a faster model."
        )
    return str(exc)


class NimClient:
    def __init__(self, settings: NimSettings) -> None:
        self.settings = settings

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
            raise NimClientError(
                f"NIM HTTP error {exc.code}",
                error_type="http_error",
                details={"status_code": exc.code, "body": error_body, "url": url},
            ) from exc
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, (TimeoutError, socket.timeout)) or "timed out" in str(reason).lower():
                raise NimClientError(
                    "NIM request timed out",
                    error_type="timeout",
                    details={"url": url, "timeout_seconds": timeout},
                ) from exc
            raise NimClientError(
                f"NIM connection error: {exc.reason}",
                error_type="connection_error",
                details={"url": url, "reason": str(exc.reason)},
            ) from exc
        except TimeoutError as exc:
            raise NimClientError(
                "NIM request timed out",
                error_type="timeout",
                details={"url": url, "timeout_seconds": timeout},
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
        selected_model = model or self.settings.model
        if not selected_model:
            raise NimClientError("NIM model is not configured", error_type="missing_model")
        body = {
            "model": selected_model,
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
        return NimChatResult(content=str(content), raw_response=payload, latency_ms=latency_ms)
