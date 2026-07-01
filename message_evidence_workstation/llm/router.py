"""Central model router facade."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Protocol

from message_evidence_workstation.config.settings import (
    AppSettings,
    ModelRoleConfig,
    PROVIDER_GOOGLE,
    PROVIDER_NIM,
    apply_api_key_env_override,
    default_model_routing,
    load_settings,
    resolve_role_config,
)
from message_evidence_workstation.llm.errors import (
    ModelError,
    model_error_from_nim,
)
from message_evidence_workstation.llm.providers.google_provider import GoogleModelProvider
from message_evidence_workstation.llm.providers.nim_provider import NimModelProvider
from message_evidence_workstation.llm.task_roles import (
    task_role_for_run_type,
    user_facing_role_for_task_role,
)
from message_evidence_workstation.llm.types import (
    ModelChatResult,
    ModelInfo,
    ModelTaskRole,
    ModelTestResult,
    UserFacingModelRole,
)
from message_evidence_workstation.nim.client import NimClientError


class ModelRouterError(RuntimeError):
    pass


class _ChatProvider(Protocol):
    def chat_completion(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        temperature: float,
        max_output_tokens: int,
        timeout_seconds: float,
        task_role: ModelTaskRole,
    ) -> ModelChatResult: ...


class ModelRouter:
    def __init__(self, settings: AppSettings | None = None) -> None:
        self._settings = settings or load_settings()

    @classmethod
    def from_settings(cls, settings: AppSettings | None = None) -> ModelRouter:
        return cls(settings or load_settings())

    @property
    def settings(self) -> AppSettings:
        return self._settings

    def _role_config_for_task(self, task_role: ModelTaskRole) -> ModelRoleConfig:
        if task_role in (ModelTaskRole.MODEL_TEST, ModelTaskRole.MODEL_LIST):
            return resolve_role_config(self._settings, UserFacingModelRole.EXPANSION)
        user_facing = user_facing_role_for_task_role(task_role)
        if user_facing is None:
            raise ModelRouterError(f"No user-facing role mapped for task_role={task_role.value}")
        return resolve_role_config(self._settings, user_facing)

    def _provider_for_config(self, config: ModelRoleConfig) -> _ChatProvider:
        if config.provider == PROVIDER_NIM:
            return NimModelProvider(config)
        if config.provider == PROVIDER_GOOGLE:
            return GoogleModelProvider(config)
        raise ModelRouterError(f"Provider {config.provider!r} is not implemented.")

    def _chat_once(
        self,
        *,
        config: ModelRoleConfig,
        task_role: ModelTaskRole,
        messages: list[dict[str, str]],
        max_output_tokens: int,
        timeout_seconds: float,
        temperature: float,
    ) -> ModelChatResult:
        provider = self._provider_for_config(config)
        try:
            result = provider.chat_completion(
                messages,
                model=config.model,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                timeout_seconds=timeout_seconds,
                task_role=task_role,
            )
        except NimClientError as exc:
            raise model_error_from_nim(exc, provider=config.provider) from exc
        return replace(
            result,
            max_output_tokens=max_output_tokens,
            timeout_seconds=timeout_seconds,
        )

    def chat(
        self,
        *,
        task_role: ModelTaskRole,
        messages: list[dict[str, str]],
        max_output_tokens: int | None = None,
        timeout_seconds: float | None = None,
        temperature: float | None = None,
    ) -> ModelChatResult:
        config = self._role_config_for_task(task_role)
        selected_max_tokens = (
            max_output_tokens if max_output_tokens is not None else config.max_output_tokens
        )
        selected_timeout = (
            timeout_seconds if timeout_seconds is not None else config.timeout_seconds
        )
        selected_temperature = temperature if temperature is not None else config.temperature

        def operation() -> ModelChatResult:
            return self._chat_once(
                config=config,
                task_role=task_role,
                messages=messages,
                max_output_tokens=selected_max_tokens,
                timeout_seconds=selected_timeout,
                temperature=selected_temperature,
            )

        return operation()

    def chat_for_run_type(
        self,
        *,
        run_type: str,
        messages: list[dict[str, str]],
        max_output_tokens: int | None = None,
        timeout_seconds: float | None = None,
    ) -> ModelChatResult:
        return self.chat(
            task_role=task_role_for_run_type(run_type),
            messages=messages,
            max_output_tokens=max_output_tokens,
            timeout_seconds=timeout_seconds,
        )

    def list_models(self, *, task_role: ModelTaskRole = ModelTaskRole.MODEL_LIST) -> list[ModelInfo]:
        config = self._role_config_for_task(task_role)
        return self._list_models_for_config(config)

    def list_models_for_provider(self, provider: str) -> list[ModelInfo]:
        config = self._list_config_for_provider(provider)
        return self._list_models_for_config(config)

    def _list_config_for_provider(self, provider: str) -> ModelRoleConfig:
        nim = self._settings.nim
        if provider == PROVIDER_NIM:
            expansion = resolve_role_config(self._settings, UserFacingModelRole.EXPANSION)
            return apply_api_key_env_override(
                ModelRoleConfig(
                    provider=PROVIDER_NIM,
                    model=expansion.model,
                    api_base_url=expansion.api_base_url or nim.api_base_url,
                    api_key=expansion.api_key or nim.api_key,
                    temperature=expansion.temperature,
                    max_output_tokens=expansion.max_output_tokens,
                    timeout_seconds=expansion.timeout_seconds,
                )
            )
        if provider == PROVIDER_GOOGLE:
            routing = self._settings.model_routing or default_model_routing(nim)
            google_key = ""
            google_model = ""
            for role_config in (routing.expansion, routing.research, routing.writing):
                if role_config.api_key and not google_key:
                    google_key = role_config.api_key
                if role_config.provider == PROVIDER_GOOGLE and role_config.model:
                    google_model = role_config.model
            return apply_api_key_env_override(
                ModelRoleConfig(
                    provider=PROVIDER_GOOGLE,
                    model=google_model or "gemini-2.0-flash",
                    api_key=google_key,
                    timeout_seconds=nim.timeout_seconds,
                )
            )
        raise ModelRouterError(f"Provider {provider!r} is not implemented.")

    def _list_models_for_config(self, config: ModelRoleConfig) -> list[ModelInfo]:
        provider = self._provider_for_config(config)
        try:
            return provider.list_models()
        except NimClientError as exc:
            raise model_error_from_nim(exc, provider=config.provider) from exc

    def test_model(self, *, user_facing_role: UserFacingModelRole) -> ModelTestResult:
        config = resolve_role_config(self._settings, user_facing_role)
        provider = self._provider_for_config(config)
        try:
            if isinstance(provider, NimModelProvider):
                nim_result = provider.test_model()
                return ModelTestResult(
                    success=nim_result.success,
                    provider=config.provider,
                    model=nim_result.model,
                    latency_ms=nim_result.latency_ms,
                    response_preview=nim_result.response_preview,
                    error_type=nim_result.error_type,
                    error_message=nim_result.error_message,
                    method=nim_result.method,
                    path=nim_result.path,
                    url=nim_result.url,
                    status_code=nim_result.status_code,
                    response_body=nim_result.response_body,
                )
            if isinstance(provider, GoogleModelProvider):
                return provider.test_model()
        except NimClientError as exc:
            raise model_error_from_nim(exc, provider=config.provider) from exc
        raise ModelRouterError(f"Model test is not implemented for provider={config.provider!r}")

    def writing_model_id(self) -> str:
        return resolve_role_config(self._settings, UserFacingModelRole.WRITING).model

    def research_model_id(self) -> str:
        return resolve_role_config(self._settings, UserFacingModelRole.RESEARCH).model

    def expansion_model_id(self) -> str:
        return resolve_role_config(self._settings, UserFacingModelRole.EXPANSION).model

    def request_metadata(
        self,
        *,
        task_role: ModelTaskRole,
        messages: list[dict[str, str]],
        max_output_tokens: int | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        config = self._role_config_for_task(task_role)
        return {
            "model": config.model,
            "messages": messages,
            "temperature": config.temperature,
            "max_tokens": max_output_tokens if max_output_tokens is not None else config.max_output_tokens,
            "timeout_seconds": timeout_seconds if timeout_seconds is not None else config.timeout_seconds,
            "provider": config.provider,
            "task_role": task_role.value,
            "api_base_url": config.api_base_url,
        }
