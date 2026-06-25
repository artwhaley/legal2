"""Role-based model routing settings tests (T26)."""

from __future__ import annotations

import json
import os

import pytest

from message_evidence_workstation.config.settings import (
    GOOGLE_API_KEY_ENV,
    NIM_API_KEY_ENV,
    NimSettings,
    PROVIDER_GOOGLE,
    PROVIDER_NIM,
    apply_api_key_env_override,
    default_model_routing,
    load_settings,
    resolve_role_config,
    save_settings,
    settings_path,
    _fresh_app_settings,
)
from message_evidence_workstation.llm.types import UserFacingModelRole


@pytest.fixture
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "message_evidence_workstation.config.settings.workspace_dir",
        lambda: tmp_path,
    )
    return tmp_path


def test_fresh_settings_seed_three_nim_roles(isolated_settings) -> None:
    settings = load_settings()
    assert settings.model_routing is not None
    for role in (
        settings.model_routing.expansion,
        settings.model_routing.research,
        settings.model_routing.writing,
    ):
        assert role.provider == PROVIDER_NIM
        assert role.temperature == settings.nim.temperature
        assert role.model == ""


def test_old_nim_only_settings_migrate_model_routing(isolated_settings) -> None:
    path = settings_path()
    path.write_text(
        json.dumps(
            {
                "nim": {
                    "api_base_url": "https://integrate.api.nvidia.com/v1",
                    "api_key": "stored-key",
                    "model": "meta/llama-3.1-8b-instruct",
                    "temperature": 0.1,
                    "max_output_tokens": 2048,
                    "timeout_seconds": 300.0,
                    "streaming": False,
                    "manual_model_entry_enabled": False,
                }
            }
        ),
        encoding="utf-8",
    )
    settings = load_settings()
    assert settings.model_routing is not None
    assert settings.model_routing.research.model == "meta/llama-3.1-8b-instruct"
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert "model_routing" in saved
    assert "model" not in saved["nim"]


def test_env_var_overrides_stored_nim_key(isolated_settings, monkeypatch) -> None:
    monkeypatch.setenv(NIM_API_KEY_ENV, "env-nim-key")
    settings = _fresh_app_settings(NimSettings(api_key="stored"))
    settings.model_routing.expansion.model = "m"
    config = resolve_role_config(settings, UserFacingModelRole.EXPANSION)
    assert config.api_key == "env-nim-key"


def test_google_env_var_override(isolated_settings, monkeypatch) -> None:
    monkeypatch.setenv(GOOGLE_API_KEY_ENV, "env-google-key")
    settings = _fresh_app_settings(NimSettings())
    settings.model_routing.writing.provider = PROVIDER_GOOGLE
    settings.model_routing.writing.api_key = "stored-google"
    config = apply_api_key_env_override(settings.model_routing.writing)
    assert config.api_key == "env-google-key"


def test_settings_round_trip_preserves_role_models(isolated_settings) -> None:
    settings = load_settings()
    assert settings.model_routing is not None
    settings.model_routing.research.model = "google/gemini-2.0-flash"
    settings.model_routing.research.provider = PROVIDER_GOOGLE
    save_settings(settings)
    reloaded = load_settings()
    assert reloaded.model_routing is not None
    assert reloaded.model_routing.research.model == "google/gemini-2.0-flash"
    assert reloaded.model_routing.research.provider == PROVIDER_GOOGLE


def test_default_model_routing_copies_connection_defaults() -> None:
    nim = NimSettings(api_key="k", temperature=0.3)
    routing = default_model_routing(nim)
    assert routing.expansion.model == ""
    assert routing.writing.temperature == 0.3
    assert routing.expansion.api_base_url == nim.api_base_url
