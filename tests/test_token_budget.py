"""Token budget estimation tests."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from message_evidence_workstation.search.token_budget import (
    estimate_json_payload_tokens,
    estimate_tokens,
)


def test_estimate_tokens_heuristic_chars_divided_by_four(monkeypatch) -> None:
    import builtins

    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "tiktoken":
            raise ImportError("forced heuristic path")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    result = estimate_tokens("x" * 200_000)
    assert result.method == "heuristic"
    assert result.estimated_tokens == 50_000


def test_estimate_json_payload_tokens_uses_serialized_json() -> None:
    payload = {"message": "café"}
    with patch(
        "message_evidence_workstation.search.token_budget.estimate_tokens",
        return_value=MagicMock(estimated_tokens=42, method="heuristic"),
    ) as mocked:
        result = estimate_json_payload_tokens(payload)
    serialized = json.dumps(payload, ensure_ascii=False)
    mocked.assert_called_once_with(serialized, model_id=None)
    assert result.estimated_tokens == 42


def test_estimate_tokens_uses_mocked_tiktoken_when_available() -> None:
    fake_module = MagicMock()
    fake_encoding = MagicMock()
    fake_encoding.encode.return_value = [1, 2, 3]
    fake_module.get_encoding.return_value = fake_encoding
    with patch.dict("sys.modules", {"tiktoken": fake_module}):
        result = estimate_tokens("hello")
    assert result.method == "tiktoken"
    assert result.estimated_tokens == 3


def test_estimate_tokens_empty_string_is_zero_or_one_consistently() -> None:
    result = estimate_tokens("")
    assert result.estimated_tokens == 0
    assert result.method == "heuristic"
