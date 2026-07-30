import json

import pytest

from message_evidence_workstation.config import settings as settings_module
from message_evidence_workstation.config.settings import AppSettings, TranscriptSettings


def test_client_settings_reject_server_owned_or_unknown_policy(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    monkeypatch.setattr(settings_module, "settings_path", lambda: path)
    path.write_text(
        json.dumps(
            {
                "server_url": "http://127.0.0.1:8710",
                "answer": {"answer_mode": "whole_transcript"},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unsupported fields"):
        settings_module.load_settings()


def test_client_settings_round_trip_only_client_owned_fields(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    monkeypatch.setattr(settings_module, "settings_path", lambda: path)
    expected = AppSettings(
        server_url="http://127.0.0.1:8710",
        transcript=TranscriptSettings(speaker_tints=["#112233"]),
    )
    settings_module.save_settings(expected)
    assert settings_module.load_settings() == expected
    assert set(json.loads(path.read_text(encoding="utf-8"))) == {
        "server_url",
        "transcript",
    }
