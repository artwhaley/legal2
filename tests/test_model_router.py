"""Model router tests (T27/T28)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from message_evidence_workstation.config.settings import (
    AppSettings,
    ModelRoleConfig,
    ModelRoutingSettings,
    NimSettings,
    PROVIDER_NIM,
)
from message_evidence_workstation.llm.router import ModelRouter
from message_evidence_workstation.llm.types import ModelTaskRole, ModelTestResult, UserFacingModelRole
from message_evidence_workstation.nim.client import NimClient


def _app_settings(**nim_overrides) -> AppSettings:
    nim = NimSettings(api_base_url="https://integrate.api.nvidia.com/v1", api_key="key", **nim_overrides)
    base_url = "https://integrate.api.nvidia.com/v1"
    routing = ModelRoutingSettings(
        expansion=ModelRoleConfig(provider=PROVIDER_NIM, model="expansion-model", api_key="key", api_base_url=base_url),
        research=ModelRoleConfig(provider=PROVIDER_NIM, model="research-model", api_key="key", api_base_url=base_url),
        writing=ModelRoleConfig(provider=PROVIDER_NIM, model="writing-model", api_key="key", api_base_url=base_url),
    )
    return AppSettings(nim=nim, model_routing=routing)


def test_router_resolves_search_expansion_role() -> None:
    router = ModelRouter(_app_settings())
    config = router._role_config_for_task(ModelTaskRole.SEARCH_EXPANSION)
    assert config.model == "expansion-model"


def test_router_resolves_research_and_writing_roles() -> None:
    router = ModelRouter(_app_settings())
    assert router._role_config_for_task(ModelTaskRole.FULL_CONTEXT_SEARCH).model == "research-model"
    assert router._role_config_for_task(ModelTaskRole.FULL_CONTEXT_ANSWER).model == "writing-model"


def test_router_dispatches_nim_provider_chat() -> None:
    router = ModelRouter(_app_settings())
    payload = {"choices": [{"message": {"content": "ok"}}]}
    with patch("urllib.request.urlopen") as urlopen:
        response = MagicMock()
        response.read.return_value = __import__("json").dumps(payload).encode("utf-8")
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        urlopen.return_value = response
        result = router.chat(
            task_role=ModelTaskRole.SEARCH_EXPANSION,
            messages=[{"role": "user", "content": "hi"}],
        )
    assert result.content == "ok"
    assert result.provider.value == "nim"
    assert result.task_role == ModelTaskRole.SEARCH_EXPANSION
    assert result.latency_ms >= 0


def test_router_from_settings_uses_routed_models() -> None:
    router = ModelRouter.from_settings(_app_settings())
    config = router._role_config_for_task(ModelTaskRole.SEARCH_EXPANSION)
    assert config.model == "expansion-model"


def test_router_test_model_uses_expansion_role_by_default() -> None:
    router = ModelRouter(_app_settings())
    with patch.object(NimClient, "test_model", return_value=MagicMock(success=True, model="expansion-model")) as test_mock:
        result = router.test_model(user_facing_role=UserFacingModelRole.EXPANSION)
    test_mock.assert_called_once()
    assert isinstance(result, ModelTestResult)
    assert result.provider == PROVIDER_NIM
