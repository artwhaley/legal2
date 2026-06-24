"""Model context window resolver tests."""

from message_evidence_workstation.nim.model_context import (
    DEFAULT_CONTEXT_WINDOW_TOKENS,
    resolve_model_context,
)


def test_user_setting_wins() -> None:
    resolved = resolve_model_context(
        "any-model",
        provider_metadata={"context_length": 99999},
        user_override_tokens=12345,
    )
    assert resolved.context_window_tokens == 12345
    assert resolved.source == "user_setting"


def test_provider_metadata_is_ignored_without_user_setting() -> None:
    resolved = resolve_model_context(
        "vendor/some-model",
        provider_metadata={"max_context_length": 64000},
    )
    assert resolved.context_window_tokens == DEFAULT_CONTEXT_WINDOW_TOKENS
    assert resolved.source == "default"


def test_unknown_model_uses_conservative_default() -> None:
    resolved = resolve_model_context("vendor/unknown-model")
    assert resolved.context_window_tokens == DEFAULT_CONTEXT_WINDOW_TOKENS
    assert resolved.context_window_tokens == 8192
    assert resolved.source == "default"
