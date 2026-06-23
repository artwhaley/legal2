"""Model context window resolver tests."""

from message_evidence_workstation.nim.model_context import (
    DEFAULT_CONTEXT_WINDOW_TOKENS,
    resolve_model_context,
)


def test_user_override_wins() -> None:
    resolved = resolve_model_context("any-model", provider_metadata={"context_length": 99999}, user_override_tokens=12345)
    assert resolved.context_window_tokens == 12345
    assert resolved.source == "user_override"


def test_provider_metadata_wins_over_registry() -> None:
    resolved = resolve_model_context(
        "minimaxai/minimax-m3",
        provider_metadata={"max_context_length": 64000},
    )
    assert resolved.context_window_tokens == 64000
    assert resolved.source == "provider"


def test_registry_used_for_known_model() -> None:
    resolved = resolve_model_context("minimaxai/minimax-m3")
    assert resolved.source == "registry"
    assert resolved.context_window_tokens == 1_000_000


def test_unknown_model_uses_conservative_default() -> None:
    resolved = resolve_model_context("vendor/unknown-model")
    assert resolved.context_window_tokens == DEFAULT_CONTEXT_WINDOW_TOKENS
    assert resolved.context_window_tokens == 8192
    assert resolved.source == "default"


def test_invalid_provider_metadata_ignored() -> None:
    resolved = resolve_model_context(
        "vendor/unknown-model",
        provider_metadata={"context_length": "not-a-number"},
    )
    assert resolved.source == "default"
