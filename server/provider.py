"""Shared async OpenAI-compatible provider transport."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any

import httpx

from server.config import OperationConfig
from server.token_accounting import build_provider_payload, count_provider_payload, count_text_tokens


class ProviderError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
        provider_request_id: str | None = None,
        response_body: Any = None,
    ):
        self.code = code
        self.status_code = status_code
        self.retryable = retryable
        self.provider_request_id = provider_request_id
        self.response_body = response_body
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class ProviderResult:
    content: str
    input_tokens: int
    output_tokens: int
    usage_source: str
    cache_read_input_tokens: int
    cache_write_input_tokens: int
    cache_miss_input_tokens: int
    cache_usage_reported: bool
    provider_request_id: str | None
    latency_ms: float
    raw_response: Any


def _cache_usage(usage: dict[str, Any]) -> tuple[int, int, int, bool]:
    """Normalize cache accounting fields used by OpenAI-compatible providers."""
    details = usage.get("prompt_tokens_details")
    details = details if isinstance(details, dict) else {}
    candidates = (
        details.get("cached_tokens"),
        usage.get("prompt_cache_hit_tokens"),
        usage.get("cache_read_input_tokens"),
        usage.get("cached_content_token_count"),
    )
    read_value = next(
        (value for value in candidates if isinstance(value, int) and value >= 0),
        None,
    )
    write_candidates = (
        details.get("cache_write_tokens"),
        usage.get("cache_write_tokens"),
        usage.get("cache_creation_input_tokens"),
    )
    write_value = next(
        (value for value in write_candidates if isinstance(value, int) and value >= 0),
        None,
    )
    miss_value = usage.get("prompt_cache_miss_tokens")
    if not isinstance(miss_value, int) or miss_value < 0:
        prompt_tokens = usage.get("prompt_tokens")
        miss_value = (
            max(0, prompt_tokens - read_value)
            if isinstance(prompt_tokens, int) and read_value is not None
            else None
        )
    reported = read_value is not None or write_value is not None or miss_value is not None
    return read_value or 0, write_value or 0, miss_value or 0, reported


class AsyncProvider:
    def __init__(self, client: httpx.AsyncClient | None = None):
        self.client = client
        self._owned = client is None

    async def start(self, config) -> None:
        if self.client is None:
            limits = httpx.Limits(max_connections=config.global_config.provider_http_max_connections, max_keepalive_connections=config.global_config.provider_http_max_keepalive_connections, keepalive_expiry=config.global_config.provider_http_keepalive_expiry_seconds)
            self.client = httpx.AsyncClient(limits=limits)

    async def close(self) -> None:
        if self.client is not None and self._owned:
            await self.client.aclose()
            self.client = None

    async def chat(self, operation: str, config: OperationConfig, *, messages: list[dict[str, str]], user_object: dict[str, Any], response_schema: dict[str, Any] | None, api_key: str | None = None) -> ProviderResult:
        if self.client is None:
            raise RuntimeError("provider client is not started")
        payload = build_provider_payload(config, operation=operation, messages=messages, user_object=user_object, response_schema=response_schema)
        started = time.perf_counter()
        try:
            secret = api_key if api_key is not None else config.api_key
            if not secret:
                raise ProviderError("CONFIGURATION_ERROR", "provider credential is unavailable", retryable=False)
            response = await self.client.post(f"{config.base_url}/chat/completions", json=payload, headers={"Content-Type": "application/json", "Authorization": f"Bearer {secret}"}, timeout=httpx.Timeout(config.read_timeout_seconds, connect=config.connect_timeout_seconds, write=config.write_timeout_seconds, pool=config.pool_timeout_seconds))
        except asyncio.CancelledError:
            raise
        except httpx.TimeoutException as exc:
            raise ProviderError("PROVIDER_TIMEOUT", "provider request timed out", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("PROVIDER_UNAVAILABLE", "provider connection failed", retryable=True) from exc
        latency = (time.perf_counter() - started) * 1000
        request_id = response.headers.get("x-request-id")
        if response.status_code >= 400:
            code, retryable = self._status_code(response.status_code)
            try:
                error_body: Any = response.json()
            except ValueError:
                error_body = response.text
            raise ProviderError(
                code,
                f"provider returned HTTP {response.status_code}",
                status_code=response.status_code,
                retryable=retryable,
                provider_request_id=request_id,
                response_body=error_body,
            )
        try:
            body = response.json()
            choices = body["choices"]
            content = choices[0]["message"]["content"]
            if not isinstance(content, str):
                raise TypeError("content is not a string")
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            try:
                invalid_body: Any = response.json()
            except ValueError:
                invalid_body = response.text
            raise ProviderError(
                "PROVIDER_REJECTED",
                "provider returned an invalid response envelope",
                provider_request_id=request_id,
                response_body=invalid_body,
            ) from exc
        usage = body.get("usage")
        if isinstance(usage, dict) and isinstance(usage.get("prompt_tokens"), int) and isinstance(usage.get("completion_tokens"), int):
            input_tokens, output_tokens, source = usage["prompt_tokens"], usage["completion_tokens"], "provider_reported"
        else:
            input_tokens = count_provider_payload(payload, config).input_tokens
            output_tokens = count_text_tokens(content, config)
            source = "estimated"
        cache_read, cache_write, cache_miss, cache_reported = (
            _cache_usage(usage) if isinstance(usage, dict) else (0, 0, 0, False)
        )
        return ProviderResult(
            content,
            input_tokens,
            output_tokens,
            source,
            cache_read,
            cache_write,
            cache_miss,
            cache_reported,
            request_id,
            latency,
            body,
        )

    @staticmethod
    def _status_code(status: int) -> tuple[str, bool]:
        if status == 429:
            return "PROVIDER_RATE_LIMITED", True
        if status in {408, 409, 500, 502, 503, 504}:
            return "PROVIDER_UNAVAILABLE", True
        if status in {401, 403, 404, 422}:
            return "PROVIDER_REJECTED", False
        return "PROVIDER_REJECTED", False
