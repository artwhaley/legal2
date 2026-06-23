"""Context limit parsing and token budget math tests."""

from message_evidence_workstation.nim.client import NimClientError
from message_evidence_workstation.nim.context_limits import (
    is_context_limit_error,
    parse_context_window_from_error,
)
from message_evidence_workstation.nim.model_context import DEFAULT_CONTEXT_WINDOW_TOKENS, resolve_model_context
from message_evidence_workstation.search.token_budget import (
    compute_usable_input_tokens,
    effective_reserved_output_tokens,
)


def test_parse_context_window_from_error_openai_style() -> None:
    body = (
        '{"error":"This model\'s maximum context length is 4096 tokens. '
        'However, you requested 9491 tokens (5395 in the messages, 4096 in the completion)."}'
    )
    assert parse_context_window_from_error(body) == 4096


def test_is_context_limit_error_detects_400() -> None:
    exc = NimClientError(
        "NIM HTTP error 400",
        error_type="http_error",
        details={
            "status_code": 400,
            "body": '{"error":"maximum context length is 4096 tokens"}',
        },
    )
    assert is_context_limit_error(exc)


def test_unknown_model_default_context_is_conservative() -> None:
    assert DEFAULT_CONTEXT_WINDOW_TOKENS == 8192


def test_effective_reserved_output_caps_small_models() -> None:
    assert effective_reserved_output_tokens(4096, 4096) == 1024


def test_compute_usable_input_tokens_for_small_model() -> None:
    usable, effective = compute_usable_input_tokens(
        context_window_tokens=4096,
        safety_ratio=0.70,
        reserved_output_tokens=4096,
        prompt_overhead_tokens=1500,
    )
    assert effective == 1024
    assert usable < 5395


def test_parse_context_window_from_gemma_prompt_limit() -> None:
    body = '{"error":"Input value error: prompt is [[16192]] long while only 4096 is supported"}'
    assert parse_context_window_from_error(body) == 4096


def test_is_context_limit_error_detects_500_prompt_too_long() -> None:
    exc = NimClientError(
        "NIM HTTP error 500",
        error_type="http_error",
        details={
            "status_code": 500,
            "body": '{"error":"Input value error: prompt is [[16192]] long while only 4096 is supported"}',
        },
    )
    assert is_context_limit_error(exc)


def test_learned_context_preferred_over_provider_metadata() -> None:
    resolved = resolve_model_context(
        "google/gemma-2-2b-it",
        provider_metadata={
            "context_length": 8192,
            "context_source": "learned_from_api_error",
        },
    )
    assert resolved.context_window_tokens == 8192  # learned stored value

    resolved_learned = resolve_model_context(
        "google/gemma-2-2b-it",
        provider_metadata={
            "context_length": 4096,
            "context_source": "learned_from_api_error",
        },
    )
    assert resolved_learned.context_window_tokens == 4096
    assert resolved_learned.source == "learned_from_api_error"
