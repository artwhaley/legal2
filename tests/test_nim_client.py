"""NIM client tests with mocked HTTP."""

import json
from unittest.mock import patch

import pytest

from message_evidence_workstation.config.settings import NimSettings
from message_evidence_workstation.nim.client import NimClient, NimClientError, nim_error_user_message

TEST_MODEL = "meta/llama3-8b-instruct"
GEMMA_MODEL = "google/gemma-2-2b-it"


_TEST_NIM_URL = "https://integrate.api.nvidia.com/v1"


def test_chat_completion_success() -> None:
    client = NimClient(NimSettings(api_base_url=_TEST_NIM_URL, api_key="test-key"))
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
        result = client.chat_completion(
            [{"role": "user", "content": "hi"}],
            model=TEST_MODEL,
        )
    assert result.content == "hello from nim"


def test_model_list_http_error() -> None:
    import urllib.error

    client = NimClient(NimSettings(api_base_url=_TEST_NIM_URL, api_key="bad-key"))

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
    client = NimClient(NimSettings(api_base_url=_TEST_NIM_URL, api_key=""))
    with pytest.raises(NimClientError) as exc_info:
        client.list_models()
    assert exc_info.value.error_type == "missing_api_key"


def test_timeout_user_message() -> None:
    exc = NimClientError("NIM request timed out", error_type="timeout", details={"timeout_seconds": 60.0})
    message = nim_error_user_message(exc)
    assert "60" in message
    assert "Setup / Settings" in message


def test_url_error_timeout_maps_to_timeout_type() -> None:
    import urllib.error

    client = NimClient(NimSettings(api_base_url=_TEST_NIM_URL, api_key="test-key", timeout_seconds=5.0))

    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.URLError(TimeoutError("timed out")),
    ):
        with pytest.raises(NimClientError) as exc_info:
            client.chat_completion(
                [{"role": "user", "content": "hi"}],
                model=TEST_MODEL,
            )
    assert exc_info.value.error_type == "timeout"


def test_list_models_preserves_metadata() -> None:
    client = NimClient(NimSettings(api_base_url=_TEST_NIM_URL, api_key="test-key"))
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
    client = NimClient(NimSettings(api_base_url=_TEST_NIM_URL, api_key="test-key"))
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


def test_http_error_includes_request_metadata() -> None:
    import urllib.error

    client = NimClient(NimSettings(api_base_url=_TEST_NIM_URL, api_key="test-key"))

    def raise_http(*_args, **_kwargs):
        raise urllib.error.HTTPError(
            url="https://integrate.api.nvidia.com/v1/chat/completions",
            code=404,
            msg="Not Found",
            hdrs=None,
            fp=type("Body", (), {"read": lambda self: b"404 page not found\n"})(),
        )

    with patch("urllib.request.urlopen", side_effect=raise_http):
        with pytest.raises(NimClientError) as exc_info:
            client.chat_completion(
                [{"role": "user", "content": "hi"}],
                model=GEMMA_MODEL,
            )
    exc = exc_info.value
    assert exc.error_type == "http_error"
    assert exc.details["status_code"] == 404
    assert exc.details["method"] == "POST"
    assert exc.details["path"] == "/chat/completions"
    assert exc.details["model"] == GEMMA_MODEL
    assert "integrate.api.nvidia.com" in exc.details["url"]


def test_nim_error_user_message_http_404() -> None:
    exc = NimClientError(
        "NIM HTTP error 404",
        error_type="http_error",
        details={
            "status_code": 404,
            "method": "POST",
            "url": "https://integrate.api.nvidia.com/v1/chat/completions",
            "model": GEMMA_MODEL,
            "body": "404 page not found\n",
        },
    )
    message = nim_error_user_message(exc)
    assert "POST" in message
    assert "chat/completions" in message
    assert GEMMA_MODEL in message
    assert "404 page not found" in message


def test_test_model_success() -> None:
    client = NimClient(NimSettings(api_base_url=_TEST_NIM_URL, api_key="test-key"))
    payload = {"choices": [{"message": {"content": "ok"}}]}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(payload).encode("utf-8")

    with patch("urllib.request.urlopen", return_value=FakeResponse()):
        result = client.test_model(model=GEMMA_MODEL)
    assert result.success is True
    assert result.model == GEMMA_MODEL
    assert result.method == "POST"
    assert result.path == "/chat/completions"
    assert result.response_preview == "ok"


def test_test_model_failure_returns_details() -> None:
    import urllib.error

    client = NimClient(NimSettings(api_base_url=_TEST_NIM_URL, api_key="test-key"))

    def raise_http(*_args, **_kwargs):
        raise urllib.error.HTTPError(
            url="https://integrate.api.nvidia.com/v1/chat/completions",
            code=404,
            msg="Not Found",
            hdrs=None,
            fp=type("Body", (), {"read": lambda self: b'{"detail":"Function not found"}'})(),
        )

    with patch("urllib.request.urlopen", side_effect=raise_http):
        result = client.test_model(model=GEMMA_MODEL)
    assert result.success is False
    assert result.status_code == 404
    assert result.error_type == "http_error"
    assert "chat/completions" in (result.error_message or "")
