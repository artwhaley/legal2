"""Google AI Studio (Gemini) provider adapter."""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from typing import Any

from message_evidence_workstation.config.settings import GOOGLE_API_KEY_ENV, ModelRoleConfig, PROVIDER_GOOGLE
from message_evidence_workstation.llm.errors import ModelError, model_error_user_message
from message_evidence_workstation.llm.types import (
    ModelChatResult,
    ModelInfo,
    ModelProvider,
    ModelTaskRole,
    ModelTestResult,
    ModelUsage,
)

GOOGLE_API_BASE = "https://generativelanguage.googleapis.com/v1beta"

JSON_MODE_TASK_ROLES = {
    ModelTaskRole.SEARCH_EXPANSION,
    ModelTaskRole.FULL_CONTEXT_SEARCH,
    ModelTaskRole.WINDOWED_CONTEXT_SEARCH,
    ModelTaskRole.WINDOWED_RESULT_MERGE,
    ModelTaskRole.FULL_CONTEXT_ANSWER,
    ModelTaskRole.CONVERSATIONAL_CANDIDATE,
}


def _adapt_messages(messages: list[dict[str, str]]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    system_parts: list[str] = []
    contents: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role", "user")
        text = str(message.get("content", ""))
        if not text:
            continue
        if role == "system":
            system_parts.append(text)
            continue
        gemini_role = "user" if role == "user" else "model"
        contents.append({"role": gemini_role, "parts": [{"text": text}]})
    system_instruction = None
    if system_parts:
        system_instruction = {"parts": [{"text": "\n\n".join(system_parts)}]}
    return system_instruction, contents


def _usage_from_response(payload: dict[str, Any]) -> ModelUsage | None:
    meta = payload.get("usageMetadata")
    if not isinstance(meta, dict):
        return None
    return ModelUsage(
        input_tokens=meta.get("promptTokenCount"),
        output_tokens=meta.get("candidatesTokenCount"),
        total_tokens=meta.get("totalTokenCount"),
        raw=dict(meta),
    )


def _text_from_response_parts(parts: list[Any]) -> str:
    text_parts = [
        str(part.get("text", ""))
        for part in parts
        if isinstance(part, dict) and not part.get("thought")
    ]
    return "".join(text_parts).strip()


class GoogleModelProvider:
    def __init__(self, config: ModelRoleConfig) -> None:
        if config.provider != PROVIDER_GOOGLE:
            raise ValueError(f"GoogleModelProvider requires provider={PROVIDER_GOOGLE!r}")
        self._config = config

    def _api_key(self) -> str:
        import os

        return os.environ.get(GOOGLE_API_KEY_ENV, "") or self._config.api_key

    def _request(
        self,
        method: str,
        url: str,
        *,
        payload: dict[str, Any] | None = None,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        api_key = self._api_key()
        if not api_key:
            raise ModelError(
                "Google API key is missing",
                error_type="missing_api_key",
                provider=PROVIDER_GOOGLE,
            )
        separator = "&" if "?" in url else "?"
        full_url = f"{url}{separator}key={api_key}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            full_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            error_type = "http_error"
            if exc.code in {401, 403}:
                error_type = "auth_failure"
            elif exc.code == 429:
                error_type = "quota_exceeded"
            elif exc.code == 404:
                error_type = "missing_model"
            raise ModelError(
                f"Google HTTP error {exc.code}",
                error_type=error_type,
                provider=PROVIDER_GOOGLE,
                details={"status_code": exc.code, "body": error_body, "url": url},
            ) from exc
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, (TimeoutError, socket.timeout)) or "timed out" in str(reason).lower():
                raise ModelError(
                    "Google request timed out",
                    error_type="timeout",
                    provider=PROVIDER_GOOGLE,
                    details={"timeout_seconds": timeout_seconds, "url": url},
                ) from exc
            raise ModelError(
                f"Google connection error: {exc.reason}",
                error_type="connection_error",
                provider=PROVIDER_GOOGLE,
                details={"url": url, "reason": str(exc.reason)},
            ) from exc
        except TimeoutError as exc:
            raise ModelError(
                "Google request timed out",
                error_type="timeout",
                provider=PROVIDER_GOOGLE,
                details={"timeout_seconds": timeout_seconds, "url": url},
            ) from exc

    def list_models(self) -> list[ModelInfo]:
        payload = self._request(
            "GET",
            f"{GOOGLE_API_BASE}/models",
            timeout_seconds=self._config.timeout_seconds,
        )
        models = payload.get("models", [])
        results: list[ModelInfo] = []
        for item in models:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).removeprefix("models/")
            if name and "generateContent" in item.get("supportedGenerationMethods", []):
                results.append(ModelInfo(id=name, metadata=dict(item)))
        return results

    def chat_completion(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        temperature: float,
        max_output_tokens: int,
        timeout_seconds: float,
        task_role: ModelTaskRole,
    ) -> ModelChatResult:
        if not model:
            raise ModelError(
                "Google model is not configured",
                error_type="missing_model",
                provider=PROVIDER_GOOGLE,
            )
        system_instruction, contents = _adapt_messages(messages)
        if not contents:
            raise ModelError(
                "Google request has no user/model content",
                error_type="invalid_request",
                provider=PROVIDER_GOOGLE,
            )
        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_output_tokens,
            },
        }
        if task_role in JSON_MODE_TASK_ROLES:
            body["generationConfig"]["responseMimeType"] = "application/json"
        if system_instruction is not None:
            body["systemInstruction"] = system_instruction
        url = f"{GOOGLE_API_BASE}/models/{model}:generateContent"
        started = time.perf_counter()
        payload = self._request("POST", url, payload=body, timeout_seconds=timeout_seconds)
        latency_ms = int((time.perf_counter() - started) * 1000)
        if payload.get("promptFeedback", {}).get("blockReason"):
            raise ModelError(
                "Google blocked the response",
                error_type="safety_block",
                provider=PROVIDER_GOOGLE,
                details={"prompt_feedback": payload.get("promptFeedback")},
            )
        candidates = payload.get("candidates") or []
        if not candidates:
            raise ModelError(
                "Google returned no candidates",
                error_type="invalid_response",
                provider=PROVIDER_GOOGLE,
                details={"payload": payload},
            )
        candidate = candidates[0]
        if candidate.get("finishReason") in {"SAFETY", "RECITATION"}:
            raise ModelError(
                f"Google finish reason: {candidate.get('finishReason')}",
                error_type="safety_block",
                provider=PROVIDER_GOOGLE,
                details={"candidate": candidate},
            )
        if candidate.get("finishReason") == "MAX_TOKENS":
            raise ModelError(
                "Google response hit the max output token limit before completing",
                error_type="max_tokens",
                provider=PROVIDER_GOOGLE,
                details={
                    "finish_reason": candidate.get("finishReason"),
                    "model": model,
                    "max_output_tokens": max_output_tokens,
                    "usage": payload.get("usageMetadata", {}),
                },
            )
        parts = candidate.get("content", {}).get("parts", [])
        content = _text_from_response_parts(parts)
        if not content:
            raise ModelError(
                "Google returned empty content",
                error_type="invalid_response",
                provider=PROVIDER_GOOGLE,
                details={"candidate": candidate},
            )
        return ModelChatResult(
            content=content,
            provider=ModelProvider.GOOGLE,
            model=model,
            task_role=task_role,
            raw_response=payload,
            latency_ms=latency_ms,
            usage=_usage_from_response(payload),
            message_layout="google_generate_content",
        )

    def test_model(self) -> ModelTestResult:
        model = self._config.model
        if not model:
            raise ModelError(
                "Google model is not configured",
                error_type="missing_model",
                provider=PROVIDER_GOOGLE,
            )
        started = time.perf_counter()
        try:
            result = self.chat_completion(
                [{"role": "user", "content": "Reply with exactly: ok"}],
                model=model,
                temperature=0.0,
                max_output_tokens=16,
                timeout_seconds=self._config.timeout_seconds,
                task_role=ModelTaskRole.MODEL_TEST,
            )
            latency_ms = int((time.perf_counter() - started) * 1000)
            return ModelTestResult(
                success=True,
                provider=PROVIDER_GOOGLE,
                model=model,
                latency_ms=latency_ms,
                response_preview=result.content[:200],
            )
        except ModelError as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            return ModelTestResult(
                success=False,
                provider=PROVIDER_GOOGLE,
                model=model,
                latency_ms=latency_ms,
                error_type=exc.error_type,
                error_message=model_error_user_message(exc),
            )
