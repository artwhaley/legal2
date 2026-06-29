"""Model context window resolver tests."""

import pytest

from message_evidence_workstation.nim.model_context import (
    CONTEXT_WINDOW_NOT_CONFIGURED,
    ModelConfigurationError,
    resolve_model_context,
)


def test_user_setting_wins() -> None:
    resolved = resolve_model_context(
        "any-model",
        context_window_tokens=128000,
        provider_metadata={"context_length": 99999},
    )
    assert resolved.context_window_tokens == 128000
    assert resolved.source == "user_setting"


def test_provider_metadata_is_ignored_without_user_setting() -> None:
    with pytest.raises(ModelConfigurationError, match=CONTEXT_WINDOW_NOT_CONFIGURED):
        resolve_model_context(
            "vendor/some-model",
            context_window_tokens=0,
            provider_metadata={"max_context_length": 64000},
        )


def test_zero_tokens_raises_never_8192() -> None:
    with pytest.raises(ModelConfigurationError, match=CONTEXT_WINDOW_NOT_CONFIGURED):
        resolve_model_context("vendor/unknown-model", context_window_tokens=0)
    with pytest.raises(ModelConfigurationError):
        resolve_model_context("vendor/unknown-model", context_window_tokens=-1)
