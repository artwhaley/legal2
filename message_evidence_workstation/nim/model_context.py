"""Model context window resolution for token-aware budgeting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DEFAULT_CONTEXT_SAFETY_RATIO = 0.70
DEFAULT_RESERVED_OUTPUT_TOKENS = 4096
DEFAULT_PROMPT_OVERHEAD_TOKENS = 1500
DEFAULT_WINDOW_OVERLAP_MESSAGES = 2

CONTEXT_WINDOW_NOT_CONFIGURED = (
    "Model context window must be set before using conversational features."
)


class ModelConfigurationError(ValueError):
    """Raised when required model settings are missing or invalid."""


@dataclass(slots=True)
class ModelContextWindow:
    model_id: str
    context_window_tokens: int
    source: str  # user_setting
    default_output_tokens: int = DEFAULT_RESERVED_OUTPUT_TOKENS


def resolve_model_context(
    model_id: str,
    *,
    context_window_tokens: int,
    provider_metadata: dict[str, Any] | None = None,
) -> ModelContextWindow:
    del provider_metadata  # reserved for future per-model table; does not affect budgeting
    if context_window_tokens <= 0:
        raise ModelConfigurationError(CONTEXT_WINDOW_NOT_CONFIGURED)
    return ModelContextWindow(
        model_id=model_id,
        context_window_tokens=int(context_window_tokens),
        source="user_setting",
    )
