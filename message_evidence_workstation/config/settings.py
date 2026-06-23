"""Workspace settings persistence."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from message_evidence_workstation.config.paths import workspace_dir

SETTINGS_FILE = "settings.json"
NIM_API_KEY_ENV = "MEW_NIM_API_KEY"


@dataclass
class NimSettings:
    api_base_url: str = "https://integrate.api.nvidia.com/v1"
    api_key: str = ""
    model: str = ""
    temperature: float = 0.2
    max_output_tokens: int = 4096
    timeout_seconds: float = 180.0
    streaming: bool = False
    manual_model_entry_enabled: bool = False


@dataclass
class AnswerSettings:
    answer_strategy: str = "auto"
    whole_transcript_max_chars: int = 200_000
    session_gap_minutes: int = 120
    max_inspected_sessions: int = 12
    transcript_window_padding: int = 2
    context_window_override_tokens: int = 0
    context_safety_ratio: float = 0.70
    reserved_output_tokens: int = 4096
    prompt_overhead_tokens: int = 1500
    window_target_tokens: int = 12000
    window_overlap_messages: int = 2


@dataclass
class AppSettings:
    nim: NimSettings
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    chunking: dict = field(default_factory=dict)
    answer: AnswerSettings = field(default_factory=AnswerSettings)
    nim_model_metadata: dict[str, dict] = field(default_factory=dict)


def settings_path() -> Path:
    return workspace_dir() / SETTINGS_FILE


def load_settings() -> AppSettings:
    path = settings_path()
    if not path.is_file():
        nim = NimSettings()
        env_key = os.environ.get(NIM_API_KEY_ENV, "")
        if env_key:
            nim.api_key = env_key
        return AppSettings(nim=nim)
    data = json.loads(path.read_text(encoding="utf-8"))
    nim_data = data.get("nim", {})
    nim = NimSettings(**{**asdict(NimSettings()), **nim_data})
    env_key = os.environ.get(NIM_API_KEY_ENV, "")
    if env_key:
        nim.api_key = env_key
    bumped_timeout = False
    bumped_output_tokens = False
    if nim.timeout_seconds <= 60.0:
        nim.timeout_seconds = 180.0
        bumped_timeout = True
    if nim.max_output_tokens <= 1024:
        nim.max_output_tokens = 4096
        bumped_output_tokens = True
    settings = AppSettings(
        nim=nim,
        embedding_model=data.get("embedding_model", "sentence-transformers/all-MiniLM-L6-v2"),
        chunking=data.get("chunking", {}),
        answer=AnswerSettings(**{**asdict(AnswerSettings()), **data.get("answer", {})}),
        nim_model_metadata=dict(data.get("nim_model_metadata", {})),
    )
    if bumped_timeout or bumped_output_tokens:
        save_settings(settings)
    return settings


def save_settings(settings: AppSettings) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "nim": asdict(settings.nim),
        "embedding_model": settings.embedding_model,
        "chunking": settings.chunking or {},
        "answer": asdict(settings.answer),
        "nim_model_metadata": settings.nim_model_metadata or {},
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def nim_settings_for_client(settings: AppSettings | None = None) -> NimSettings:
    """Return NIM settings with env-var API key override applied."""
    nim = (settings or load_settings()).nim
    env_key = os.environ.get(NIM_API_KEY_ENV, "")
    if env_key:
        nim.api_key = env_key
    return nim
