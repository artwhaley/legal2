"""Model context window resolution for token-aware budgeting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DEFAULT_CONTEXT_WINDOW_TOKENS = 8192
DEFAULT_CONTEXT_SAFETY_RATIO = 0.70
DEFAULT_RESERVED_OUTPUT_TOKENS = 4096
DEFAULT_PROMPT_OVERHEAD_TOKENS = 1500
DEFAULT_WINDOW_TARGET_TOKENS = 12000
DEFAULT_WINDOW_OVERLAP_MESSAGES = 2


@dataclass(slots=True)
class ModelContextWindow:
    model_id: str
    context_window_tokens: int
    source: str  # user_setting | default
    default_output_tokens: int = DEFAULT_RESERVED_OUTPUT_TOKENS


def resolve_model_context(
    model_id: str,
    provider_metadata: dict | None = None,
    user_override_tokens: int | None = None,
) -> ModelContextWindow:
    del provider_metadata  # not used for budgeting; set context window in answer settings
    if user_override_tokens is not None and user_override_tokens > 0:
        return ModelContextWindow(
            model_id=model_id,
            context_window_tokens=int(user_override_tokens),
            source="user_setting",
        )
    return ModelContextWindow(
        model_id=model_id,
        context_window_tokens=DEFAULT_CONTEXT_WINDOW_TOKENS,
        source="default",
    )
