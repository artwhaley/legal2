"""NIM provider adapter."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from message_evidence_workstation.config.settings import ModelRoleConfig, PROVIDER_NIM, NimSettings
from message_evidence_workstation.llm.types import ModelChatResult, ModelInfo, ModelProvider, ModelTaskRole
from message_evidence_workstation.nim.client import NimChatResult, NimClient


def _nim_settings_from_role(config: ModelRoleConfig) -> NimSettings:
    return NimSettings(
        api_base_url=config.api_base_url,
        api_key=config.api_key,
        temperature=config.temperature,
        max_output_tokens=config.max_output_tokens,
        timeout_seconds=config.timeout_seconds,
    )


def _to_model_chat_result(
    result: NimChatResult,
    *,
    model: str,
    task_role: ModelTaskRole,
) -> ModelChatResult:
    return ModelChatResult(
        content=result.content,
        provider=ModelProvider.NIM,
        model=model,
        task_role=task_role,
        raw_response=result.raw_response,
        latency_ms=result.latency_ms,
        message_layout=result.message_layout,
    )


class NimModelProvider:
    def __init__(
        self,
        config: ModelRoleConfig,
        *,
        log_warning: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        if config.provider != PROVIDER_NIM:
            raise ValueError(f"NimModelProvider requires provider={PROVIDER_NIM!r}")
        self._config = config
        self._client = NimClient(
            _nim_settings_from_role(config),
            log_warning=log_warning,
        )

    @property
    def client(self) -> NimClient:
        return self._client

    def list_models(self) -> list[ModelInfo]:
        return [
            ModelInfo(id=item.id, metadata=dict(item.metadata))
            for item in self._client.list_models()
        ]

    def chat_completion(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
        timeout_seconds: float | None = None,
        task_role: ModelTaskRole,
    ) -> ModelChatResult:
        selected_model = model or self._config.model
        result = self._client.chat_completion(
            messages,
            model=selected_model,
            max_tokens=max_output_tokens,
            timeout_seconds=timeout_seconds,
        )
        return _to_model_chat_result(result, model=selected_model, task_role=task_role)

    def test_model(self) -> NimChatResult:
        return self._client.test_model(model=self._config.model)
