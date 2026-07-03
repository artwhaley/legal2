"""Token estimation helpers for context budgeting."""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass

_log = logging.getLogger(__name__)


@dataclass(slots=True)
class TokenEstimate:
    estimated_tokens: int
    method: str  # model_native | tiktoken | heuristic
    fallback_reason: str | None = None


def compute_usable_input_tokens(
    *,
    context_window_tokens: int,
    safety_ratio: float,
    prompt_overhead_tokens: int,
    max_output_tokens: int = 0,
) -> int:
    """Return usable input tokens for transcript budgeting."""
    base = context_window_tokens - max(0, prompt_overhead_tokens) - max(0, max_output_tokens)
    usable = math.floor(base * safety_ratio)
    return max(256, usable)


def estimate_tokens(text: str, model_id: str | None = None) -> TokenEstimate:
    del model_id  # reserved for future model-native tokenizers
    if not text:
        return TokenEstimate(0, "heuristic")
    try:
        import tiktoken

        encoding = tiktoken.get_encoding("cl100k_base")
        return TokenEstimate(len(encoding.encode(text)), "tiktoken")
    except Exception as exc:
        reason = f"tiktoken cl100k_base failed: {exc}"
        _log.warning("Token estimation fallback: %s", reason)
        return TokenEstimate(
            max(1, math.ceil(len(text) / 4)),
            "heuristic",
            fallback_reason=reason,
        )


def estimate_json_payload_tokens(payload: dict, model_id: str | None = None) -> TokenEstimate:
    serialized = json.dumps(payload, ensure_ascii=False)
    return estimate_tokens(serialized, model_id=model_id)
