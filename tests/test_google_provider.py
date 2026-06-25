"""Google provider tests."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from message_evidence_workstation.config.settings import GOOGLE_API_KEY_ENV, ModelRoleConfig, PROVIDER_GOOGLE
from message_evidence_workstation.llm.errors import ModelError
from message_evidence_workstation.llm.providers.google_provider import GoogleModelProvider, _adapt_messages
from message_evidence_workstation.llm.types import ModelTaskRole


def _config(**overrides) -> ModelRoleConfig:
    base = ModelRoleConfig(
        provider=PROVIDER_GOOGLE,
        model="gemini-2.0-flash",
        api_key="stored-key",
        timeout_seconds=30.0,
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def test_adapt_messages_maps_system_instruction() -> None:
    system, contents = _adapt_messages(
        [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
        ]
    )
    assert system == {"parts": [{"text": "You are helpful."}]}
    assert contents == [{"role": "user", "parts": [{"text": "Hello"}]}]


def test_google_provider_success_returns_normalized_result() -> None:
    provider = GoogleModelProvider(_config())
    payload = {
        "candidates": [{"content": {"parts": [{"text": "ok"}]}, "finishReason": "STOP"}],
        "usageMetadata": {
            "promptTokenCount": 3,
            "candidatesTokenCount": 1,
            "totalTokenCount": 4,
        },
    }

    with patch("urllib.request.urlopen") as urlopen:
        response = MagicMock()
        response.read.return_value = json.dumps(payload).encode("utf-8")
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        urlopen.return_value = response
        result = provider.chat_completion(
            [{"role": "user", "content": "hi"}],
            model="gemini-2.0-flash",
            temperature=0.0,
            max_output_tokens=16,
            timeout_seconds=30.0,
            task_role=ModelTaskRole.SEARCH_EXPANSION,
        )

    assert result.content == "ok"
    assert result.provider.value == "google"
    assert result.usage is not None
    assert result.usage.total_tokens == 4
    request = urlopen.call_args.args[0]
    body = json.loads(request.data.decode("utf-8"))
    assert body["generationConfig"]["responseMimeType"] == "application/json"


def test_google_provider_ignores_thought_parts() -> None:
    provider = GoogleModelProvider(_config())
    payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": "I will reason about this first.", "thought": True},
                        {"text": '{"answer": "ok"}'},
                    ]
                },
                "finishReason": "STOP",
            }
        ],
    }

    with patch("urllib.request.urlopen") as urlopen:
        response = MagicMock()
        response.read.return_value = json.dumps(payload).encode("utf-8")
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        urlopen.return_value = response
        result = provider.chat_completion(
            [{"role": "user", "content": "hi"}],
            model="gemma-4-31b-it",
            temperature=0.0,
            max_output_tokens=16,
            timeout_seconds=30.0,
            task_role=ModelTaskRole.FULL_CONTEXT_ANSWER,
        )

    assert result.content == '{"answer": "ok"}'


def test_google_provider_raises_on_max_tokens_finish() -> None:
    provider = GoogleModelProvider(_config())
    payload = {
        "candidates": [
            {
                "content": {"parts": [{"text": '{"answer": "cut off"'}]},
                "finishReason": "MAX_TOKENS",
            }
        ],
        "usageMetadata": {"candidatesTokenCount": 16},
    }

    with patch("urllib.request.urlopen") as urlopen:
        response = MagicMock()
        response.read.return_value = json.dumps(payload).encode("utf-8")
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        urlopen.return_value = response
        with pytest.raises(ModelError) as exc_info:
            provider.chat_completion(
                [{"role": "user", "content": "hi"}],
                model="gemma-4-31b-it",
                temperature=0.0,
                max_output_tokens=16,
                timeout_seconds=30.0,
                task_role=ModelTaskRole.FULL_CONTEXT_ANSWER,
            )

    assert exc_info.value.error_type == "max_tokens"
    assert exc_info.value.details["max_output_tokens"] == 16


def test_google_provider_does_not_force_json_for_model_test() -> None:
    provider = GoogleModelProvider(_config())
    payload = {
        "candidates": [{"content": {"parts": [{"text": "ok"}]}, "finishReason": "STOP"}],
    }

    with patch("urllib.request.urlopen") as urlopen:
        response = MagicMock()
        response.read.return_value = json.dumps(payload).encode("utf-8")
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        urlopen.return_value = response
        provider.chat_completion(
            [{"role": "user", "content": "Reply with exactly: ok"}],
            model="gemini-2.0-flash",
            temperature=0.0,
            max_output_tokens=16,
            timeout_seconds=30.0,
            task_role=ModelTaskRole.MODEL_TEST,
        )

    request = urlopen.call_args.args[0]
    body = json.loads(request.data.decode("utf-8"))
    assert "responseMimeType" not in body["generationConfig"]


def test_google_provider_missing_api_key() -> None:
    provider = GoogleModelProvider(_config(api_key=""))
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ModelError) as exc_info:
            provider.chat_completion(
                [{"role": "user", "content": "hi"}],
                model="gemini-2.0-flash",
                temperature=0.0,
                max_output_tokens=16,
                timeout_seconds=30.0,
                task_role=ModelTaskRole.SEARCH_EXPANSION,
            )
    assert exc_info.value.error_type == "missing_api_key"


def test_google_env_key_overrides_stored_key(monkeypatch) -> None:
    monkeypatch.setenv(GOOGLE_API_KEY_ENV, "env-google-key")
    provider = GoogleModelProvider(_config(api_key="stored-key"))
    assert provider._api_key() == "env-google-key"


def test_google_provider_auth_failure() -> None:
    provider = GoogleModelProvider(_config())
    import urllib.error

    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.HTTPError(
            url="https://example.test",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=MagicMock(read=lambda: b'{"error":"bad key"}'),
        ),
    ):
        with pytest.raises(ModelError) as exc_info:
            provider.chat_completion(
                [{"role": "user", "content": "hi"}],
                model="gemini-2.0-flash",
                temperature=0.0,
                max_output_tokens=16,
                timeout_seconds=30.0,
                task_role=ModelTaskRole.SEARCH_EXPANSION,
            )
    assert exc_info.value.error_type == "auth_failure"


def test_google_provider_safety_block() -> None:
    provider = GoogleModelProvider(_config())
    payload = {
        "candidates": [{"finishReason": "SAFETY", "content": {"parts": [{"text": ""}]}}],
    }
    with patch("urllib.request.urlopen") as urlopen:
        response = MagicMock()
        response.read.return_value = json.dumps(payload).encode("utf-8")
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        urlopen.return_value = response
        with pytest.raises(ModelError) as exc_info:
            provider.chat_completion(
                [{"role": "user", "content": "hi"}],
                model="gemini-2.0-flash",
                temperature=0.0,
                max_output_tokens=16,
                timeout_seconds=30.0,
                task_role=ModelTaskRole.SEARCH_EXPANSION,
            )
    assert exc_info.value.error_type == "safety_block"
