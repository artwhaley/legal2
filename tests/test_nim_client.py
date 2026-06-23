"""NIM client tests with mocked HTTP."""

import json
from unittest.mock import patch

import pytest

from message_evidence_workstation.config.settings import NimSettings
from message_evidence_workstation.nim.client import NimClient, NimClientError


def test_chat_completion_success() -> None:
    settings = NimSettings(api_key="test-key", model="meta/llama3-8b-instruct")
    client = NimClient(settings)
    payload = {
        "choices": [{"message": {"content": "hello from nim"}}],
    }

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(payload).encode("utf-8")

    with patch("urllib.request.urlopen", return_value=FakeResponse()):
        result = client.chat_completion([{"role": "user", "content": "hi"}])
    assert result.content == "hello from nim"


def test_model_list_http_error() -> None:
    import urllib.error

    settings = NimSettings(api_key="bad-key", model="")
    client = NimClient(settings)

    def raise_http(*_args, **_kwargs):
        raise urllib.error.HTTPError(
            url="http://example",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=None,
        )

    with patch("urllib.request.urlopen", side_effect=raise_http):
        with pytest.raises(NimClientError) as exc_info:
            client.list_models()
    assert exc_info.value.error_type == "http_error"


def test_missing_api_key_fails_loudly() -> None:
    client = NimClient(NimSettings(api_key=""))
    with pytest.raises(NimClientError) as exc_info:
        client.list_models()
    assert exc_info.value.error_type == "missing_api_key"


def test_timeout_user_message() -> None:
    from message_evidence_workstation.nim.client import nim_error_user_message

    exc = NimClientError("NIM request timed out", error_type="timeout", details={"timeout_seconds": 60.0})
    message = nim_error_user_message(exc)
    assert "60" in message
    assert "Setup / Settings" in message


def test_url_error_timeout_maps_to_timeout_type() -> None:
    import urllib.error

    settings = NimSettings(api_key="test-key", model="meta/llama3-8b-instruct", timeout_seconds=5.0)
    client = NimClient(settings)

    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.URLError(TimeoutError("timed out")),
    ):
        with pytest.raises(NimClientError) as exc_info:
            client.chat_completion([{"role": "user", "content": "hi"}])
    assert exc_info.value.error_type == "timeout"


def test_list_models_preserves_metadata() -> None:
    settings = NimSettings(api_key="test-key", model="")
    client = NimClient(settings)
    payload = {
        "data": [
            {
                "id": "vendor/model-a",
                "context_length": 128000,
                "object": "model",
            }
        ]
    }

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(payload).encode("utf-8")

    with patch("urllib.request.urlopen", return_value=FakeResponse()):
        models = client.list_models()
    assert len(models) == 1
    assert models[0].id == "vendor/model-a"
    assert models[0].metadata["context_length"] == 128000


def test_list_models_supports_name_or_id() -> None:
    settings = NimSettings(api_key="test-key", model="")
    client = NimClient(settings)
    payload = {"models": [{"name": "legacy/name-model", "max_model_len": 4096}]}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(payload).encode("utf-8")

    with patch("urllib.request.urlopen", return_value=FakeResponse()):
        models = client.list_models()
    assert models[0].id == "legacy/name-model"
    assert models[0].metadata["max_model_len"] == 4096
