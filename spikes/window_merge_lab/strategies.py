"""Merge strategy implementations for window merge lab."""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from spikes.window_merge_lab.budget_planner import (
    SynthesisBudgetPlan,
    SynthesisBudgetRequest,
    plan_synthesis_budget,
)
from spikes.window_merge_lab.data_loader import load_compact_windows
from spikes.window_merge_lab.prompts import (
    build_evidence_table_messages,
    build_hierarchical_batch_messages,
    build_one_shot_messages,
    build_rolling_synthesis_messages,
)

ModelCallFn = Callable[[list[dict[str, str]]], tuple[str, int]]


@dataclass
class StrategyResult:
    strategy_name: str
    messages_per_call: list[list[dict[str, str]]]
    responses: list[str]
    latency_ms: int
    call_count: int
    output_dir: Path | None = None
    last_parsed: dict | None = None
    error: str | None = None
    planner_plans: list[dict] | None = None


def _noop_model_call(messages: list[dict[str, str]]) -> tuple[str, int]:
    payload = json.dumps(messages, indent=2, ensure_ascii=False)
    return payload, 0


def _parse_fenced_json(text: str) -> dict | None:
    if not text:
        return None
    cleaned = text.strip()
    for prefix in ("```json\n", "```json\r\n", "```\n", "```"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :]
    for suffix in ("\n```", "\r\n```"):
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)]
    cleaned = cleaned.strip()
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
        return None
    except (json.JSONDecodeError, ValueError):
        return None


def _save_outputs(
    output_dir: Path,
    strategy_name: str,
    messages_per_call: list[list[dict[str, str]]],
    responses: list[str],
    latency_ms: int,
    call_count: int,
    last_parsed: dict | None,
    error: str | None,
    planner_plans: list[dict] | None = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "prompt_payload.json").write_text(
        json.dumps(messages_per_call, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    preview_lines = []
    for i, msgs in enumerate(messages_per_call):
        preview_lines.append(f"=== Call {i + 1} ===")
        for m in msgs:
            role = m.get("role", "")
            content = m.get("content", "")
            preview_lines.append(f"[{role}] {content[:200]}...")
            preview_lines.append("")
    (output_dir / "prompt_preview.md").write_text("\n".join(preview_lines), encoding="utf-8")
    raw_text = "\n\n---\n\n".join(responses) if responses else "(no responses)"
    (output_dir / "result_raw.txt").write_text(raw_text, encoding="utf-8")
    (output_dir / "result_parsed.json").write_text(
        json.dumps(last_parsed or {}, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    readable = _parsed_to_readable(last_parsed) if last_parsed else "(no parsed result)"
    (output_dir / "result_readable.md").write_text(readable, encoding="utf-8")
    metrics = {
        "strategy": strategy_name,
        "call_count": call_count,
        "latency_ms": latency_ms,
        "has_error": error is not None,
        "error": error,
        "range_count": len(last_parsed.get("answer_ranges", [])) if last_parsed else 0,
    }
    if planner_plans:
        modes = [p.get("mode") for p in planner_plans]
        metrics["planner_mode"] = modes[-1] if modes else None
        metrics["planner_modes"] = modes
        metrics["planner_calls"] = planner_plans
    (output_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _parsed_to_readable(parsed: dict) -> str:
    lines = []
    lines.append(f"# {parsed.get('answer_summary', 'Merge Result')}")
    lines.append("")
    lines.append(f"**Format:** {parsed.get('answer_format', 'detailed')}")
    lines.append("")
    answer = parsed.get("answer", "")
    if answer:
        lines.append(answer)
        lines.append("")
    ranges = parsed.get("answer_ranges", [])
    if ranges:
        lines.append(f"## Answer Ranges ({len(ranges)})")
        lines.append("")
        for i, r in enumerate(ranges, 1):
            if isinstance(r, dict):
                lines.append(f"### {i}. {r.get('title', 'Untitled')}")
                lines.append(f"- **Summary:** {r.get('summary', '')}")
                lines.append(f"- **Date:** {r.get('date_description', '')}")
                lines.append(f"- **Hit:** `{r.get('hit_message_id', '')}`")
                lines.append(f"- **Range:** `{r.get('start_message_id', '')}` → `{r.get('end_message_id', '')}`")
                lines.append("")
    uncertainties = parsed.get("uncertainties", [])
    if uncertainties:
        lines.append("## Uncertainties")
        for u in uncertainties:
            lines.append(f"- {u}")
        lines.append("")
    coverage = parsed.get("coverage_summary")
    if coverage and isinstance(coverage, dict):
        lines.append("## Coverage")
        for k, v in coverage.items():
            lines.append(f"- **{k}:** {v}")
    return "\n".join(lines)


# --- Strategy Implementations ---


def run_one_shot_compact(
    user_query: str,
    windows: list[dict],
    *,
    model_call: ModelCallFn = _noop_model_call,
    include_raw_scan: bool = False,
    max_ranges_per_window: int = 0,
    model_context_tokens: int = 32768,
    max_output_tokens: int = 4096,
) -> StrategyResult:
    plans_list: list[dict] = []
    plan = plan_synthesis_budget(SynthesisBudgetRequest(
        evidence_records=windows,
        user_query=user_query,
        strategy_name="one_shot_compact",
        call_label="final",
        model_context_tokens=model_context_tokens,
        max_output_tokens=max_output_tokens,
    ))
    plans_list.append({
        "call_label": "final",
        "mode": plan.mode,
        "answer_format": plan.answer_format,
        "estimated_input_tokens": plan.estimated_input_tokens,
        "estimated_output_tokens": plan.estimated_output_tokens,
        "available_input_tokens": plan.available_input_tokens,
        "available_output_tokens": plan.available_output_tokens,
        "fallback_reason": plan.fallback_reason,
    })
    messages = build_one_shot_messages(
        user_query, windows, include_raw_scan=include_raw_scan,
        max_ranges_per_window=max_ranges_per_window, plan=plan,
    )
    start = time.monotonic()
    try:
        response, _ = model_call(messages)
        elapsed = int((time.monotonic() - start) * 1000)
        parsed = _parse_fenced_json(response)
        return StrategyResult(
            strategy_name="one_shot_compact",
            messages_per_call=[messages],
            responses=[response],
            latency_ms=elapsed,
            call_count=1,
            last_parsed=parsed,
            planner_plans=plans_list,
        )
    except Exception as e:
        elapsed = int((time.monotonic() - start) * 1000)
        return StrategyResult(
            strategy_name="one_shot_compact",
            messages_per_call=[messages],
            responses=[],
            latency_ms=elapsed,
            call_count=0,
            error=str(e),
            planner_plans=plans_list,
        )


def run_hierarchical_balanced(
    user_query: str,
    windows: list[dict],
    *,
    model_call: ModelCallFn = _noop_model_call,
    max_ranges_per_window: int = 0,
    model_context_tokens: int = 32768,
    max_output_tokens: int = 4096,
) -> StrategyResult:
    messages_list: list[list[dict]] = []
    responses: list[str] = []
    start = time.monotonic()
    plans_list: list[dict] = []

    def _call_planner(batch, label):
        p = plan_synthesis_budget(SynthesisBudgetRequest(
            evidence_records=batch,
            user_query=user_query,
            strategy_name="hierarchical_balanced",
            call_label=label,
            model_context_tokens=model_context_tokens,
            max_output_tokens=max_output_tokens,
        ))
        plans_list.append({
            "call_label": label,
            "mode": p.mode,
            "answer_format": p.answer_format,
            "estimated_input_tokens": p.estimated_input_tokens,
            "estimated_output_tokens": p.estimated_output_tokens,
            "available_input_tokens": p.available_input_tokens,
            "available_output_tokens": p.available_output_tokens,
            "fallback_reason": p.fallback_reason,
        })
        return p

    try:
        # Merge windows 1-3
        batch1 = windows[:3]
        plan1 = _call_planner(batch1, "batch_1")
        msgs1 = build_hierarchical_batch_messages(
            user_query, batch1, depth=0, max_ranges_per_window=max_ranges_per_window, plan=plan1,
        )
        messages_list.append(msgs1)
        resp1, _ = model_call(msgs1)
        responses.append(resp1)
        parsed1 = _parse_fenced_json(resp1) or {}

        # Merge windows 4-6
        batch2 = windows[3:]
        plan2 = _call_planner(batch2, "batch_2")
        msgs2 = build_hierarchical_batch_messages(
            user_query, batch2, depth=0, max_ranges_per_window=max_ranges_per_window, plan=plan2,
        )
        messages_list.append(msgs2)
        resp2, _ = model_call(msgs2)
        responses.append(resp2)
        parsed2 = _parse_fenced_json(resp2) or {}

        # Merge the two partial syntheses
        interim_windows = [
            _interim_from_parsed(parsed1, "merged_left"),
            _interim_from_parsed(parsed2, "merged_right"),
        ]
        plan3 = _call_planner(interim_windows, "final")
        msgs3 = build_hierarchical_batch_messages(
            user_query, interim_windows, depth=1, max_ranges_per_window=0, plan=plan3,
        )
        messages_list.append(msgs3)
        resp3, _ = model_call(msgs3)
        responses.append(resp3)
        parsed3 = _parse_fenced_json(resp3)

        elapsed = int((time.monotonic() - start) * 1000)
        return StrategyResult(
            strategy_name="hierarchical_balanced",
            messages_per_call=messages_list,
            responses=responses,
            latency_ms=elapsed,
            call_count=3,
            last_parsed=parsed3,
            planner_plans=plans_list,
        )
    except Exception as e:
        elapsed = int((time.monotonic() - start) * 1000)
        return StrategyResult(
            strategy_name="hierarchical_balanced",
            messages_per_call=messages_list,
            responses=responses,
            latency_ms=elapsed,
            call_count=len(responses),
            error=str(e),
            planner_plans=plans_list,
        )


def run_rolling_synthesis(
    user_query: str,
    windows: list[dict],
    *,
    model_call: ModelCallFn = _noop_model_call,
    max_ranges_per_window: int = 0,
    model_context_tokens: int = 32768,
    max_output_tokens: int = 4096,
) -> StrategyResult:
    messages_list: list[list[dict]] = []
    responses: list[str] = []
    start = time.monotonic()
    plans_list: list[dict] = []

    try:
        current_synthesis: dict | None = None
        for i, w in enumerate(windows):
            records = [w]
            if current_synthesis:
                records.insert(0, current_synthesis)
            plan = plan_synthesis_budget(SynthesisBudgetRequest(
                evidence_records=records,
                user_query=user_query,
                strategy_name="rolling_synthesis",
                call_label=f"step_{i + 1}",
                model_context_tokens=model_context_tokens,
                max_output_tokens=max_output_tokens,
            ))
            plans_list.append({
                "call_label": f"step_{i + 1}",
                "mode": plan.mode,
                "answer_format": plan.answer_format,
                "estimated_input_tokens": plan.estimated_input_tokens,
                "estimated_output_tokens": plan.estimated_output_tokens,
                "available_input_tokens": plan.available_input_tokens,
                "available_output_tokens": plan.available_output_tokens,
                "fallback_reason": plan.fallback_reason,
            })
            msgs = build_rolling_synthesis_messages(
                user_query, current_synthesis, w,
                max_ranges_per_window=max_ranges_per_window, plan=plan,
            )
            messages_list.append(msgs)
            resp, _ = model_call(msgs)
            responses.append(resp)
            current_synthesis = _parse_fenced_json(resp) or {}

        elapsed = int((time.monotonic() - start) * 1000)
        return StrategyResult(
            strategy_name="rolling_synthesis",
            messages_per_call=messages_list,
            responses=responses,
            latency_ms=elapsed,
            call_count=len(windows),
            last_parsed=current_synthesis,
            planner_plans=plans_list,
        )
    except Exception as e:
        elapsed = int((time.monotonic() - start) * 1000)
        return StrategyResult(
            strategy_name="rolling_synthesis",
            messages_per_call=messages_list,
            responses=responses,
            latency_ms=elapsed,
            call_count=len(responses),
            error=str(e),
            planner_plans=plans_list,
        )


def run_evidence_table_then_synthesis(
    user_query: str,
    windows: list[dict],
    *,
    model_call: ModelCallFn = _noop_model_call,
    max_ranges_per_window: int = 0,
    model_context_tokens: int = 32768,
    max_output_tokens: int = 4096,
) -> StrategyResult:
    plans_list: list[dict] = []
    plan = plan_synthesis_budget(SynthesisBudgetRequest(
        evidence_records=windows,
        user_query=user_query,
        strategy_name="evidence_table_then_synthesis",
        call_label="final",
        model_context_tokens=model_context_tokens,
        max_output_tokens=max_output_tokens,
    ))
    plans_list.append({
        "call_label": "final",
        "mode": plan.mode,
        "answer_format": plan.answer_format,
        "estimated_input_tokens": plan.estimated_input_tokens,
        "estimated_output_tokens": plan.estimated_output_tokens,
        "available_input_tokens": plan.available_input_tokens,
        "available_output_tokens": plan.available_output_tokens,
        "fallback_reason": plan.fallback_reason,
    })
    messages = build_evidence_table_messages(
        user_query, windows, max_ranges_per_window=max_ranges_per_window, plan=plan,
    )
    start = time.monotonic()
    try:
        response, _ = model_call(messages)
        elapsed = int((time.monotonic() - start) * 1000)
        parsed = _parse_fenced_json(response)
        return StrategyResult(
            strategy_name="evidence_table_then_synthesis",
            messages_per_call=[messages],
            responses=[response],
            latency_ms=elapsed,
            call_count=1,
            last_parsed=parsed,
            planner_plans=plans_list,
        )
    except Exception as e:
        elapsed = int((time.monotonic() - start) * 1000)
        return StrategyResult(
            strategy_name="evidence_table_then_synthesis",
            messages_per_call=[messages],
            responses=[],
            latency_ms=elapsed,
            call_count=0,
            error=str(e),
            planner_plans=plans_list,
        )


def run_deterministic_baseline(
    user_query: str,
    windows: list[dict],
    *,
    model_call: ModelCallFn = _noop_model_call,
    **kwargs,
) -> StrategyResult:
    all_ranges: list[dict] = []
    all_cited: set[str] = set()
    window_coverage: set[str] = set()
    for w in windows:
        wid = w.get("window_id", "")
        window_coverage.add(wid)
        all_ranges.extend(w.get("answer_ranges", []))
        all_cited.update(w.get("cited_message_ids", []))
    seen_titles: set[str] = set()
    deduped: list[dict] = []
    for r in all_ranges:
        if isinstance(r, dict):
            t = r.get("title", "")
            if t not in seen_titles:
                seen_titles.add(t)
                deduped.append(r)
    parsed: dict[str, Any] = {
        "answer_summary": f"Deterministic baseline: {len(all_ranges)} raw ranges, "
        f"{len(deduped)} deduplicated, {len(all_cited)} cited IDs, "
        f"{len(window_coverage)}/{len(windows)} windows covered.",
        "answer_format": "detailed",
        "answer": (
            f"This is a deterministic baseline (no LLM call). "
            f"Raw ranges from all windows: {len(all_ranges)}. "
            f"After deduplication by title: {len(deduped)}. "
            f"Distinct cited message IDs: {len(all_cited)}. "
            f"Windows represented: {len(window_coverage)}/{len(windows)}."
        ),
        "answer_ranges": deduped,
        "uncertainties": [
            "Deterministic baseline: no LLM synthesis was performed.",
            "Ranges are concatenated and deduplicated by title only.",
            "No semantic merging, no prioritization, no grouping.",
        ],
        "coverage_summary": {
            "mode": "deterministic_baseline",
            "windows_total": len(windows),
            "windows_represented": len(window_coverage),
            "raw_range_count": len(all_ranges),
            "deduped_range_count": len(deduped),
            "cited_message_ids_count": len(all_cited),
        },
    }
    return StrategyResult(
        strategy_name="deterministic_baseline",
        messages_per_call=[],
        responses=[],
        latency_ms=0,
        call_count=0,
        last_parsed=parsed,
    )


def _interim_from_parsed(parsed: dict, window_id: str) -> dict:
    return {
        "window_id": window_id,
        "source_thread_id": "",
        "answer_summary": parsed.get("answer_summary", ""),
        "answer": parsed.get("answer", ""),
        "cited_message_ids": list(parsed.get("cited_message_ids", [])),
        "answer_ranges": list(parsed.get("answer_ranges", [])),
        "uncertainties": list(parsed.get("uncertainties", [])),
    }


STRATEGY_REGISTRY: dict[str, Callable] = {
    "one_shot_compact": run_one_shot_compact,
    "hierarchical_balanced": run_hierarchical_balanced,
    "rolling_synthesis": run_rolling_synthesis,
    "evidence_table_then_synthesis": run_evidence_table_then_synthesis,
    "deterministic_baseline": run_deterministic_baseline,
}

STRATEGY_DESCRIPTIONS: dict[str, str] = {
    "one_shot_compact": "Single LLM call over all six compact window findings",
    "hierarchical_balanced": "Three LLM calls: merge 1-3, merge 4-6, then merge interim syntheses",
    "rolling_synthesis": "Six sequential LLM calls, merging one window at a time",
    "evidence_table_then_synthesis": "Two-phase: normalize ranges into table, then synthesize",
    "deterministic_baseline": "No LLM call: raw concatenation, deduplication, and counting",
}

EXPECTED_CALL_COUNTS: dict[str, int] = {
    "one_shot_compact": 1,
    "hierarchical_balanced": 3,
    "rolling_synthesis": 6,
    "evidence_table_then_synthesis": 1,
    "deterministic_baseline": 0,
}
