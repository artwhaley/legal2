"""Model context window resolution for token-aware budgeting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DEFAULT_CONTEXT_WINDOW_TOKENS = 32768
DEFAULT_CONTEXT_SAFETY_RATIO = 0.70
DEFAULT_RESERVED_OUTPUT_TOKENS = 4096
DEFAULT_PROMPT_OVERHEAD_TOKENS = 1500
DEFAULT_WINDOW_TARGET_TOKENS = 12000
DEFAULT_WINDOW_OVERLAP_MESSAGES = 2

_CONTEXT_METADATA_KEYS = (
    "context_length",
    "context_window",
    "max_context_length",
    "max_model_len",
    "max_sequence_length",
    "input_token_limit",
    "max_input_tokens",
)


@dataclass(slots=True)
class ModelContextWindow:
    model_id: str
    context_window_tokens: int
    source: str  # user_override | provider | registry | default
    default_output_tokens: int = DEFAULT_RESERVED_OUTPUT_TOKENS


def _registry_entry(model_id: str) -> ModelContextWindow | None:
    return MODEL_CONTEXT_REGISTRY.get(model_id)


MODEL_CONTEXT_REGISTRY: dict[str, ModelContextWindow] = {
    "minimaxai/minimax-m3": ModelContextWindow(
        model_id="minimaxai/minimax-m3",
        context_window_tokens=1_000_000,
        source="registry",
    ),
}


def _positive_int_from_metadata(metadata: dict[str, Any] | None) -> int | None:
    if not metadata:
        return None
    for key in _CONTEXT_METADATA_KEYS:
        value = metadata.get(key)
        if value is None:
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    return None


def resolve_model_context(
    model_id: str,
    provider_metadata: dict | None = None,
    user_override_tokens: int | None = None,
) -> ModelContextWindow:
    if user_override_tokens is not None and user_override_tokens > 0:
        return ModelContextWindow(
            model_id=model_id,
            context_window_tokens=int(user_override_tokens),
            source="user_override",
        )
    provider_tokens = _positive_int_from_metadata(provider_metadata)
    if provider_tokens is not None:
        return ModelContextWindow(
            model_id=model_id,
            context_window_tokens=provider_tokens,
            source="provider",
        )
    registry_entry = _registry_entry(model_id)
    if registry_entry is not None:
        return ModelContextWindow(
            model_id=model_id,
            context_window_tokens=registry_entry.context_window_tokens,
            source="registry",
            default_output_tokens=registry_entry.default_output_tokens,
        )
    return ModelContextWindow(
        model_id=model_id,
        context_window_tokens=DEFAULT_CONTEXT_WINDOW_TOKENS,
        source="default",
    )
