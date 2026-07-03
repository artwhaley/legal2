"""Shared helpers for router-backed tests."""

from __future__ import annotations

from dataclasses import replace

from message_evidence_workstation.config.settings import (
    AppSettings,
    ModelRoleConfig,
    ModelRoutingSettings,
    NimSettings,
    PROVIDER_NIM,
)
from message_evidence_workstation.llm.router import ModelRouter


def router_with_role_models(
    *,
    expansion: str = "test-model",
    research: str | None = None,
    writing: str | None = None,
    api_key: str = "key",
) -> ModelRouter:
    nim = NimSettings(api_base_url="https://integrate.api.nvidia.com/v1", api_key=api_key)
    base = ModelRoleConfig(provider=PROVIDER_NIM, model=expansion, api_key=api_key, api_base_url="https://integrate.api.nvidia.com/v1")
    routing = ModelRoutingSettings(
        expansion=base,
        research=replace(base, model=research or expansion),
        writing=replace(base, model=writing or expansion),
    )
    return ModelRouter(AppSettings(nim=nim, model_routing=routing))
