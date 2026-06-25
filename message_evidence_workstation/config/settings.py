"""Workspace settings persistence."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from message_evidence_workstation.config.paths import workspace_dir
from message_evidence_workstation.llm.types import UserFacingModelRole

SETTINGS_FILE = "settings.json"
NIM_API_KEY_ENV = "MEW_NIM_API_KEY"
GOOGLE_API_KEY_ENV = "MEW_GOOGLE_API_KEY"
PROVIDER_NIM = "nim"
PROVIDER_GOOGLE = "google"

LEGACY_ANSWER_STRATEGIES = frozenset({"auto", "retrieval_fallback"})
DEFAULT_ANSWER_STRATEGY = "whole_transcript"

_LEGACY_NIM_KEYS = frozenset({"model", "manual_model_entry_enabled"})


@dataclass
class NimSettings:
    """Shared provider connection defaults and token budgets for routed model calls."""

    api_base_url: str = "https://integrate.api.nvidia.com/v1"
    api_key: str = ""
    temperature: float = 0.2
    max_output_tokens: int = 4096
    context_window_tokens: int = 0
    context_safety_ratio: float = 0.70
    prompt_overhead_tokens: int = 1500
    timeout_seconds: float = 600.0
    streaming: bool = False


@dataclass
class TranscriptSettings:
    speaker_tints: list[str] = field(default_factory=list)


@dataclass
class AnswerSettings:
    answer_strategy: str = DEFAULT_ANSWER_STRATEGY
    whole_transcript_max_chars: int = 200_000
    session_gap_minutes: int = 120
    max_inspected_sessions: int = 12
    transcript_window_padding: int = 2
    window_target_tokens: int = 12000
    window_overlap_messages: int = 2


_LEGACY_ANSWER_TOKEN_KEYS = frozenset(
    {
        "context_window_override_tokens",
        "context_safety_ratio",
        "reserved_output_tokens",
        "prompt_overhead_tokens",
    }
)


@dataclass
class ModelRoleConfig:
    provider: str = PROVIDER_NIM
    model: str = ""
    api_base_url: str = ""
    api_key: str = ""
    temperature: float = 0.2
    max_output_tokens: int = 4096
    timeout_seconds: float = 600.0
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ModelRoutingSettings:
    expansion: ModelRoleConfig
    research: ModelRoleConfig
    writing: ModelRoleConfig


@dataclass
class AppSettings:
    nim: NimSettings
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    chunking: dict = field(default_factory=dict)
    answer: AnswerSettings = field(default_factory=AnswerSettings)
    transcript: TranscriptSettings = field(default_factory=TranscriptSettings)
    model_metadata: dict[str, dict] = field(default_factory=dict)
    model_routing: ModelRoutingSettings | None = None


def settings_path() -> Path:
    return workspace_dir() / SETTINGS_FILE


def _migrate_answer_token_fields_to_nim(nim: NimSettings, answer_data: dict) -> tuple[NimSettings, bool]:
    changed = False
    override = int(answer_data.get("context_window_override_tokens", 0) or 0)
    if override > 0 and nim.context_window_tokens <= 0:
        nim = replace(nim, context_window_tokens=override)
        changed = True
    if "context_safety_ratio" in answer_data:
        nim = replace(nim, context_safety_ratio=float(answer_data["context_safety_ratio"]))
        changed = True
    if "prompt_overhead_tokens" in answer_data:
        nim = replace(nim, prompt_overhead_tokens=int(answer_data["prompt_overhead_tokens"]))
        changed = True
    reserved = int(answer_data.get("reserved_output_tokens", 0) or 0)
    if reserved > nim.max_output_tokens:
        nim = replace(nim, max_output_tokens=reserved)
        changed = True
    return nim, changed


def _normalize_answer_settings(data: dict) -> AnswerSettings:
    merged = {**asdict(AnswerSettings()), **data}
    for key in _LEGACY_ANSWER_TOKEN_KEYS:
        merged.pop(key, None)
    strategy = str(merged.get("answer_strategy", DEFAULT_ANSWER_STRATEGY))
    if strategy in LEGACY_ANSWER_STRATEGIES:
        merged["answer_strategy"] = DEFAULT_ANSWER_STRATEGY
    return AnswerSettings(**merged)


def _nim_role_template(nim: NimSettings) -> ModelRoleConfig:
    return ModelRoleConfig(
        provider=PROVIDER_NIM,
        model="",
        api_base_url=nim.api_base_url,
        api_key=nim.api_key,
        temperature=nim.temperature,
        max_output_tokens=nim.max_output_tokens,
        timeout_seconds=nim.timeout_seconds,
    )


def default_model_routing(nim: NimSettings) -> ModelRoutingSettings:
    role = _nim_role_template(nim)
    return ModelRoutingSettings(expansion=role, research=replace(role), writing=replace(role))


def _migrate_legacy_nim_model(routing: ModelRoutingSettings, legacy_model: str) -> ModelRoutingSettings:
    if not legacy_model.strip():
        return routing

    def fill(role: ModelRoleConfig) -> ModelRoleConfig:
        if role.model.strip():
            return role
        return replace(role, model=legacy_model.strip())

    return ModelRoutingSettings(
        expansion=fill(routing.expansion),
        research=fill(routing.research),
        writing=fill(routing.writing),
    )


def sync_nim_connection_to_routing(settings: AppSettings) -> ModelRoutingSettings:
    """Apply shared NIM connection defaults to every NIM-backed role."""
    nim = settings.nim
    routing = settings.model_routing or default_model_routing(nim)

    def sync_role(role: ModelRoleConfig) -> ModelRoleConfig:
        if role.provider != PROVIDER_NIM:
            return role
        return replace(
            role,
            api_base_url=nim.api_base_url,
            api_key=nim.api_key,
            temperature=nim.temperature,
            max_output_tokens=nim.max_output_tokens,
            timeout_seconds=nim.timeout_seconds,
        )

    return ModelRoutingSettings(
        expansion=sync_role(routing.expansion),
        research=sync_role(routing.research),
        writing=sync_role(routing.writing),
    )


def _model_role_config_from_dict(data: dict) -> ModelRoleConfig:
    defaults = asdict(ModelRoleConfig())
    merged = {**defaults, **data}
    extra = merged.get("extra")
    if not isinstance(extra, dict):
        merged["extra"] = {}
    return ModelRoleConfig(**merged)


def _model_routing_from_dict(data: dict, *, nim: NimSettings) -> ModelRoutingSettings:
    if not data:
        return default_model_routing(nim)
    return ModelRoutingSettings(
        expansion=_model_role_config_from_dict(data.get("expansion", {})),
        research=_model_role_config_from_dict(data.get("research", {})),
        writing=_model_role_config_from_dict(data.get("writing", {})),
    )


def apply_api_key_env_override(config: ModelRoleConfig) -> ModelRoleConfig:
    if config.provider == PROVIDER_NIM:
        env_key = os.environ.get(NIM_API_KEY_ENV, "")
    elif config.provider == PROVIDER_GOOGLE:
        env_key = os.environ.get(GOOGLE_API_KEY_ENV, "")
    else:
        env_key = ""
    if env_key:
        return replace(config, api_key=env_key)
    return config


def resolve_role_config(
    settings: AppSettings,
    role: UserFacingModelRole,
) -> ModelRoleConfig:
    routing = settings.model_routing or default_model_routing(settings.nim)
    if role == UserFacingModelRole.EXPANSION:
        config = routing.expansion
    elif role == UserFacingModelRole.RESEARCH:
        config = routing.research
    else:
        config = routing.writing
    return apply_api_key_env_override(config)


def resolve_role_model(settings: AppSettings, role: UserFacingModelRole) -> str:
    return resolve_role_config(settings, role).model.strip()


def is_role_configured(settings: AppSettings, role: UserFacingModelRole) -> bool:
    return bool(resolve_role_model(settings, role))


def _fresh_app_settings(nim: NimSettings) -> AppSettings:
    routing = default_model_routing(nim)
    return AppSettings(nim=nim, model_routing=routing)


def _nim_settings_from_dict(data: dict) -> NimSettings:
    cleaned = {key: value for key, value in data.items() if key not in _LEGACY_NIM_KEYS}
    return NimSettings(**{**asdict(NimSettings()), **cleaned})


def load_settings() -> AppSettings:
    path = settings_path()
    if not path.is_file():
        nim = NimSettings()
        env_key = os.environ.get(NIM_API_KEY_ENV, "")
        if env_key:
            nim.api_key = env_key
        return _fresh_app_settings(nim)
    data = json.loads(path.read_text(encoding="utf-8"))
    nim_data = data.get("nim", {})
    legacy_nim_model = str(nim_data.get("model", "")).strip()
    nim = _nim_settings_from_dict(nim_data)
    env_key = os.environ.get(NIM_API_KEY_ENV, "")
    if env_key:
        nim.api_key = env_key
    bumped_timeout = False
    bumped_output_tokens = False
    if nim.timeout_seconds <= 180.0:
        nim.timeout_seconds = 600.0
        bumped_timeout = True
    if nim.max_output_tokens <= 1024:
        nim.max_output_tokens = 4096
        bumped_output_tokens = True
    answer_data = data.get("answer", {})
    nim, migrated_tokens = _migrate_answer_token_fields_to_nim(nim, answer_data)
    routing = _model_routing_from_dict(data.get("model_routing", {}), nim=nim)
    routing = _migrate_legacy_nim_model(routing, legacy_nim_model)
    model_metadata = dict(data.get("model_metadata", data.get("nim_model_metadata", {})))
    settings = AppSettings(
        nim=nim,
        embedding_model=data.get("embedding_model", "sentence-transformers/all-MiniLM-L6-v2"),
        chunking=data.get("chunking", {}),
        answer=_normalize_answer_settings(data.get("answer", {})),
        transcript=TranscriptSettings(**{**asdict(TranscriptSettings()), **data.get("transcript", {})}),
        model_metadata=model_metadata,
        model_routing=routing,
    )
    should_save = bumped_timeout or bumped_output_tokens or migrated_tokens
    if any(key in answer_data for key in _LEGACY_ANSWER_TOKEN_KEYS):
        should_save = True
    if str(answer_data.get("answer_strategy", "")) in LEGACY_ANSWER_STRATEGIES:
        should_save = True
    if "model_routing" not in data or legacy_nim_model:
        should_save = True
    if "model" in nim_data or "manual_model_entry_enabled" in nim_data:
        should_save = True
    if "nim_model_metadata" in data and "model_metadata" not in data:
        should_save = True
    if should_save:
        save_settings(settings)
    return settings


def save_settings(settings: AppSettings) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    routing = sync_nim_connection_to_routing(settings)
    payload = {
        "nim": asdict(settings.nim),
        "embedding_model": settings.embedding_model,
        "chunking": settings.chunking or {},
        "answer": asdict(settings.answer),
        "transcript": asdict(settings.transcript),
        "model_metadata": settings.model_metadata or {},
        "model_routing": {
            "expansion": asdict(routing.expansion),
            "research": asdict(routing.research),
            "writing": asdict(routing.writing),
        },
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


# Backward-compatible aliases for internal migration; do not use in new code.
seed_model_routing_from_nim = default_model_routing
_role_config_from_nim = _nim_role_template
