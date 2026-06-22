"""Workspace settings persistence."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
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
    max_output_tokens: int = 1024
    timeout_seconds: float = 180.0
    streaming: bool = False
    manual_model_entry_enabled: bool = False


@dataclass
class AppSettings:
    nim: NimSettings
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"


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
    if nim.timeout_seconds <= 60.0:
        nim.timeout_seconds = 180.0
        bumped_timeout = True
    settings = AppSettings(
        nim=nim,
        embedding_model=data.get("embedding_model", "sentence-transformers/all-MiniLM-L6-v2"),
    )
    if bumped_timeout:
        save_settings(settings)
    return settings


def save_settings(settings: AppSettings) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"nim": asdict(settings.nim), "embedding_model": settings.embedding_model}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def nim_settings_for_client(settings: AppSettings | None = None) -> NimSettings:
    """Return NIM settings with env-var API key override applied."""
    nim = (settings or load_settings()).nim
    env_key = os.environ.get(NIM_API_KEY_ENV, "")
    if env_key:
        nim.api_key = env_key
    return nim
