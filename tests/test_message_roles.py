"""Chat message role compatibility tests."""

import json
from unittest.mock import patch

import pytest

from message_evidence_workstation.config.settings import AppSettings, NimSettings, save_settings
from message_evidence_workstation.nim.client import NimClient, NimClientError
from message_evidence_workstation.nim.message_roles import (
    fold_system_into_user,
    is_system_role_unsupported_error,
    record_system_role_support,
)


def test_fold_system_into_user_merges_prompt() -> None:
    folded = fold_system_into_user(
        [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
        ]
    )
    assert folded == [{"role": "user", "content": "You are helpful.\n\n---\n\nHello"}]


def test_is_system_role_unsupported_error() -> None:
    exc = NimClientError(
        "NIM HTTP error 500",
        error_type="http_error",
        details={"status_code": 500, "body": '{"error":"System role not supported"}'},
    )
    assert is_system_role_unsupported_error(exc)


def test_chat_completion_retries_without_system_role(tmp_path) -> None:
    settings_path = tmp_path / "settings.json"
    with patch("message_evidence_workstation.config.settings.settings_path", return_value=settings_path):
        save_settings(AppSettings(nim=NimSettings(api_key="key", model="google/gemma-2-2b-it")))
        client = NimClient(NimSettings(api_key="key", model="google/gemma-2-2b-it"))
        calls: list[list[dict[str, str]]] = []

        def fake_urlopen(request, timeout=0):
            payload = json.loads(request.data.decode("utf-8"))
            calls.append(payload["messages"])
            if any(message.get("role") == "system" for message in payload["messages"]):
                raise _http_error(
                    500,
                    '{"error":"System role not supported"}',
                    request.full_url,
                )

            class FakeResponse:
                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

                def read(self):
                    return json.dumps(
                        {"choices": [{"message": {"content": "ok"}}]}
                    ).encode("utf-8")

            return FakeResponse()

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            result = client.chat_completion(
                [
                    {"role": "system", "content": "System prompt"},
                    {"role": "user", "content": "User prompt"},
                ]
            )
        assert result.content == "ok"
        assert result.message_layout == "folded_user"
        assert len(calls) == 2
        assert calls[0][0]["role"] == "system"
        assert calls[1] == [{"role": "user", "content": "System prompt\n\n---\n\nUser prompt"}]
        assert record_system_role_support("google/gemma-2-2b-it", False)["supports_system_role"] is False


def _http_error(code: int, body: str, url: str):
    import urllib.error

    return urllib.error.HTTPError(url=url, code=code, msg="error", hdrs=None, fp=type(
        "Body",
        (),
        {"read": lambda self: body.encode("utf-8")},
    )())
