"""Token estimation helpers for context budgeting."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass


@dataclass(slots=True)
class TokenEstimate:
    estimated_tokens: int
    method: str  # model_native | tiktoken | heuristic


def effective_reserved_output_tokens(context_window_tokens: int, requested: int) -> int:
    context_window_tokens = max(512, context_window_tokens)
    minimum_input_headroom = max(512, context_window_tokens // 8)
    available_for_output = max(256, context_window_tokens - minimum_input_headroom)
    quarter_cap = max(256, context_window_tokens // 4)
    return min(requested, available_for_output, quarter_cap)


def compute_usable_input_tokens(
    *,
    context_window_tokens: int,
    safety_ratio: float,
    reserved_output_tokens: int,
    prompt_overhead_tokens: int,
) -> tuple[int, int]:
    """Return (usable_input_tokens, effective_reserved_output_tokens).

    Input budget is derived from the context window minus prompt template overhead,
    with a single safety margin. Output ``max_tokens`` is capped separately via
    ``effective_reserved_output_tokens`` and is not subtracted again from input budget.
    """
    reserved = effective_reserved_output_tokens(context_window_tokens, reserved_output_tokens)
    base = context_window_tokens - max(0, prompt_overhead_tokens)
    usable = math.floor(base * safety_ratio)
    return max(256, usable), reserved


def estimate_tokens(text: str, model_id: str | None = None) -> TokenEstimate:
    del model_id  # reserved for future model-native tokenizers
    if not text:
        return TokenEstimate(0, "heuristic")
    try:
        import tiktoken

        encoding = tiktoken.get_encoding("cl100k_base")
        return TokenEstimate(len(encoding.encode(text)), "tiktoken")
    except Exception:
        pass
    return TokenEstimate(max(1, math.ceil(len(text) / 4)), "heuristic")


def estimate_json_payload_tokens(payload: dict, model_id: str | None = None) -> TokenEstimate:
    serialized = json.dumps(payload, ensure_ascii=False)
    return estimate_tokens(serialized, model_id=model_id)
