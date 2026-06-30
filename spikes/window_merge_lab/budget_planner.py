"""Synthesis budget planner — chooses between full and compact profiles.

Supports a provisional-build flow: callers may supply pre-built candidate
messages (evidence_messages) whose serialized size is used for a tight
input-token estimate instead of a coarse estimate from records alone.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class SynthesisBudgetRequest:
    evidence_records: list[dict]
    user_query: str
    strategy_name: str
    call_label: str
    model_context_tokens: int
    max_output_tokens: int
    reserved_margin_tokens: int = 2_000
    target_input_margin_ratio: float = 0.85
    evidence_messages: list[dict[str, str]] | None = None


@dataclass
class SynthesisBudgetPlan:
    mode: Literal["full", "compact"]
    strategy_name: str
    call_label: str
    range_count: int
    estimated_input_tokens: int
    estimated_output_tokens: int
    available_input_tokens: int
    available_output_tokens: int
    prompt_profile: str
    answer_format: Literal["detailed", "brief"]
    max_answer_chars: int
    max_range_summary_chars: int
    fallback_reason: str | None = None


def _estimate_messages_tokens(messages: list[dict[str, str]]) -> int:
    total = 0
    for msg in messages:
        content = msg.get("content") or ""
        role = msg.get("role") or ""
        total += math.ceil((len(content) + len(role)) / 3.5)
    return total


def estimate_json_tokens(value: object) -> int:
    serialized = json.dumps(value, ensure_ascii=False)
    return math.ceil(len(serialized) / 3.5)


def estimate_full_output_tokens(range_count: int) -> int:
    return 1_500 + range_count * 190


def estimate_compact_output_tokens(range_count: int) -> int:
    return 700 + range_count * 110


def _count_ranges(records: list[dict]) -> int:
    total = 0
    for r in records:
        ranges = (
            r.get("answer_ranges")
            or r.get("hit_ranges")
            or r.get("ledger_ranges")
            or []
        )
        if isinstance(ranges, list):
            total += len(ranges)
        elif r.get("hit_message_id"):
            total += 1
    return total


def plan_synthesis_budget(request: SynthesisBudgetRequest) -> SynthesisBudgetPlan:
    range_count = _count_ranges(request.evidence_records)
    full_output = estimate_full_output_tokens(range_count)
    compact_output = estimate_compact_output_tokens(range_count)

    if request.evidence_messages:
        estimated_input = _estimate_messages_tokens(request.evidence_messages)
    else:
        estimated_input = estimate_json_tokens(request.evidence_records)

    available_input = int(
        request.model_context_tokens * request.target_input_margin_ratio
    ) - request.reserved_margin_tokens
    available_output = request.max_output_tokens - request.reserved_margin_tokens

    input_fits = estimated_input <= available_input
    full_output_fits = full_output <= available_output

    if input_fits and full_output_fits:
        return SynthesisBudgetPlan(
            mode="full",
            strategy_name=request.strategy_name,
            call_label=request.call_label,
            range_count=range_count,
            estimated_input_tokens=estimated_input,
            estimated_output_tokens=full_output,
            available_input_tokens=available_input,
            available_output_tokens=available_output,
            prompt_profile="full",
            answer_format="detailed",
            max_answer_chars=2000,
            max_range_summary_chars=200,
            fallback_reason=None,
        )

    reasons = []
    if not input_fits:
        reasons.append(f"input ~{estimated_input} > available ~{available_input}")
    if not full_output_fits:
        reasons.append(f"full output ~{full_output} > available ~{available_output}")

    return SynthesisBudgetPlan(
        mode="compact",
        strategy_name=request.strategy_name,
        call_label=request.call_label,
        range_count=range_count,
        estimated_input_tokens=estimated_input,
        estimated_output_tokens=compact_output,
        available_input_tokens=available_input,
        available_output_tokens=available_output,
        prompt_profile="compact",
        answer_format="brief",
        max_answer_chars=500,
        max_range_summary_chars=60,
        fallback_reason="; ".join(reasons) if reasons else "compact fallback",
    )
