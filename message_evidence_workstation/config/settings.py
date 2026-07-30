"""Client-owned non-secret settings.

Provider credentials, provider model IDs, prompt policy, and retry policy are
server concerns.  This file intentionally has no fields for them.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from message_evidence_workstation.config.paths import workspace_dir

SETTINGS_FILE = "settings.json"
DEFAULT_SERVER_URL = "http://127.0.0.1:8710"


@dataclass(slots=True)
class TranscriptSettings:
    speaker_tints: list[str] = field(default_factory=list)


@dataclass(slots=True)
class AppSettings:
    server_url: str = DEFAULT_SERVER_URL
    transcript: TranscriptSettings = field(default_factory=TranscriptSettings)


def settings_path() -> Path:
    return workspace_dir() / SETTINGS_FILE


def load_settings() -> AppSettings:
    path = settings_path()
    if not path.is_file():
        return AppSettings()
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("settings.json must contain an object")
    unknown = set(data) - {"server_url", "transcript"}
    if unknown:
        raise ValueError(f"settings.json contains unsupported fields: {sorted(unknown)}")
    transcript_data = data.get("transcript", {})
    if not isinstance(transcript_data, dict) or set(transcript_data) - {"speaker_tints"}:
        raise ValueError("settings.json transcript settings have an invalid shape")
    server_url_value = data.get("server_url", DEFAULT_SERVER_URL)
    if not isinstance(server_url_value, str):
        raise ValueError("settings.json server_url must be a string")
    server_url = server_url_value.strip()
    if not server_url:
        raise ValueError("settings.json server_url must not be blank")
    if not server_url.startswith(("http://", "https://")):
        raise ValueError("settings.json server_url must begin with http:// or https://")
    speaker_tints = transcript_data.get("speaker_tints", [])
    if not isinstance(speaker_tints, list) or any(not isinstance(value, str) for value in speaker_tints):
        raise ValueError("settings.json speaker_tints must be a list of strings")
    settings = AppSettings(
        server_url=server_url,
        transcript=TranscriptSettings(speaker_tints=list(speaker_tints)),
    )
    return settings


def save_settings(settings: AppSettings) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
