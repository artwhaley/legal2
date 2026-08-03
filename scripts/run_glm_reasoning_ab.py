"""Run a controlled reasoning-off/on 100K extraction plus synthesis A/B.

Both arms use one frozen production-captured corpus request and the currently
active production prompts/configuration. The only wire-level difference is
that the reasoning-on arm adds chat_template_kwargs.enable_thinking=true.
There are no retries, fallbacks, server calls, configuration writes, or EVW
writes.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from server.conversation_unified import _input_target, _record_payload
from server.contracts import AnalysisPlanningOutput, FrozenAnalysisPlan
from server.evidence_ledger import (
    WindowLedgerInput,
    build_ledger,
    salvage_window_evidence,
)
from server.result_validation import assemble_synthesis_result, inspect_synthesis_content
from server.token_accounting import count_text_tokens, estimate_cost
try:
    from scripts.probe_glm_reasoning_stream import (
        TARGET_MODEL,
        StreamResult,
        _active_config,
        _build_payload,
        _captured_100k_user_object,
        _fenced,
        _stream_request,
        _write_markdown,
    )
except ModuleNotFoundError:  # direct ``python scripts/...`` execution
    from probe_glm_reasoning_stream import (
        TARGET_MODEL,
        StreamResult,
        _active_config,
        _build_payload,
        _captured_100k_user_object,
        _fenced,
        _stream_request,
        _write_markdown,
    )


@dataclass(slots=True)
class ArmResult:
    label: str
    thinking_enabled: bool
    extraction: StreamResult
    synthesis: StreamResult
    extraction_input_tokens: int
    synthesis_input_tokens: int
    accepted_range_count: int
    rejected_range_count: int
    assembled: dict[str, Any]
    metrics: dict[str, Any]


def _coverage(ledger) -> list[dict[str, Any]]:
    return [
        {
            "window_id": item.window_id,
            "first_message_id": item.first_message_id,
            "last_message_id": item.last_message_id,
            "message_count": item.message_count,
            "evidence_range_count": item.evidence_range_count,
            "uncertainties": list(item.uncertainties),
        }
        for item in ledger.coverage
    ]


def _metadata(ledger) -> list[dict[str, Any]]:
    return [
        {
            "range_id": record.range_id,
            "window_id": record.window_id,
            "source_range_index": record.source_range_index,
            "thread_id": record.thread_id,
            "start_message_id": record.start_message_id,
            "end_message_id": record.end_message_id,
            "summary": record.summary,
            "relevance": record.relevance,
            "normalizations": list(record.normalizations),
            "uncertainties": list(record.uncertainties),
            "warnings": list(record.warnings),
        }
        for record in ledger.records
    ]


def _provider_usage(result: StreamResult) -> tuple[int, int]:
    usage = result.usage or {}
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    if not isinstance(prompt, int) or not isinstance(completion, int):
        raise RuntimeError(f"{result.label} did not return provider token usage")
    return prompt, completion


def _freeze_current_plan(
    *,
    question: str,
    operations,
    output_dir: Path,
) -> tuple[dict[str, Any], list[dict[str, str]], StreamResult, dict[str, Any]]:
    operation = operations["analysis_planning"]
    user_object = {"task": "analysis_planning", "question": question}
    payload, input_tokens = _build_payload(
        "analysis_planning", operation, user_object
    )
    print("common planner: starting", flush=True)
    result = _stream_request(
        label="common_planner",
        operation_name="analysis_planning",
        operation=operation,
        base_payload=payload,
        enable_thinking=None,
    )
    _write_markdown(
        output_dir / "00_common_planner.md",
        title="Common frozen planner call",
        result=result,
        input_tokens=input_tokens,
        extra={
            "reasoning_enabled": False,
            "purpose": "one shared plan prevents planner variance between A/B arms",
        },
    )
    if result.http_status != 200 or not result.schema_valid:
        raise RuntimeError("common planner did not return a valid analysis plan")
    output = AnalysisPlanningOutput.model_validate(json.loads(result.content))
    plan = FrozenAnalysisPlan.model_validate(
        output.model_dump(exclude={"retrieval_queries"})
    )
    queries = [
        {"query_id": f"q{index:04d}", "text": text}
        for index, text in enumerate(output.retrieval_queries, start=1)
    ]
    return plan.model_dump(), queries, result, _stage_metrics(result, operation)


def _stage_metrics(result: StreamResult, operation) -> dict[str, Any]:
    prompt, completion = _provider_usage(result)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
        "reasoning_tokens_estimated_locally": count_text_tokens(
            result.reasoning, operation
        ),
        "final_content_tokens_estimated_locally": count_text_tokens(
            result.content, operation
        ),
        "reasoning_characters": len(result.reasoning),
        "final_content_characters": len(result.content),
        "first_reasoning_seconds": result.first_reasoning_seconds,
        "first_content_seconds": result.first_content_seconds,
        "elapsed_seconds": result.elapsed_seconds,
        "provider_reported_usage": True,
        "estimated_cost_usd": estimate_cost(operation, prompt, completion),
        "pricing_configured": (
            operation.input_price_per_million is not None
            and operation.output_price_per_million is not None
        ),
        "input_price_per_million": operation.input_price_per_million,
        "output_price_per_million": operation.output_price_per_million,
    }


def _run_arm(
    *,
    label: str,
    thinking_enabled: bool,
    user_object: dict[str, Any],
    operations,
    output_dir: Path,
) -> ArmResult:
    extraction_operation = operations["window_evidence_extraction"]
    extraction_payload, extraction_input_tokens = _build_payload(
        "window_evidence_extraction", extraction_operation, user_object
    )
    print(f"{label}: extraction starting", flush=True)
    extraction = _stream_request(
        label=f"{label}_extraction",
        operation_name="window_evidence_extraction",
        operation=extraction_operation,
        base_payload=extraction_payload,
        enable_thinking=True if thinking_enabled else None,
    )
    _write_markdown(
        output_dir / f"{label}_01_extraction.md",
        title=f"{label}: window extraction",
        result=extraction,
        input_tokens=extraction_input_tokens,
        extra={"reasoning_enabled": thinking_enabled},
    )
    if extraction.http_status != 200 or not extraction.content.strip():
        raise RuntimeError(f"{label} extraction failed with HTTP {extraction.http_status}")
    try:
        raw_extraction = json.loads(extraction.content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{label} extraction was not JSON") from exc

    window = WindowLedgerInput(
        window_id=str(user_object["window_id"]),
        messages=tuple(user_object["messages"]),
    )
    validated = salvage_window_evidence(window, raw_extraction)
    ledger = build_ledger([window], [validated])
    evidence_validation = dict(ledger.validation)
    coverage = _coverage(ledger)
    synthesis_user = {
        "task": "ledger_synthesis",
        "question": user_object["question"],
        "analysis_plan": user_object["analysis_plan"],
        "coverage_report": coverage,
        "evidence_validation_summary": evidence_validation,
        "ledger_metadata": _metadata(ledger),
        "records_or_highest_level_summaries": [
            _record_payload(record) for record in ledger.records
        ],
    }
    synthesis_operation = operations["ledger_synthesis"]
    synthesis_payload, synthesis_input_tokens = _build_payload(
        "ledger_synthesis", synthesis_operation, synthesis_user
    )
    if synthesis_input_tokens > _input_target(synthesis_operation):
        raise RuntimeError(
            f"{label} ledger requires compaction; the controlled direct-fit A/B cannot proceed"
        )
    print(
        f"{label}: synthesis starting with {len(ledger.records)} validated ledger ranges",
        flush=True,
    )
    synthesis = _stream_request(
        label=f"{label}_synthesis",
        operation_name="ledger_synthesis",
        operation=synthesis_operation,
        base_payload=synthesis_payload,
        enable_thinking=True if thinking_enabled else None,
    )
    _write_markdown(
        output_dir / f"{label}_02_synthesis.md",
        title=f"{label}: ledger synthesis",
        result=synthesis,
        input_tokens=synthesis_input_tokens,
        extra={
            "reasoning_enabled": thinking_enabled,
            "validated_ledger_ranges": len(ledger.records),
        },
    )
    if synthesis.http_status != 200 or not synthesis.content.strip():
        raise RuntimeError(f"{label} synthesis failed with HTTP {synthesis.http_status}")

    inspection = inspect_synthesis_content(synthesis.content)
    cited_ids = {
        range_id
        for item in inspection.results
        for range_id in item.get("range_ids", [])
        if range_id in {record.range_id for record in ledger.records}
    }
    extraction_metrics = _stage_metrics(extraction, extraction_operation)
    synthesis_metrics = _stage_metrics(synthesis, synthesis_operation)
    total_prompt = extraction_metrics["prompt_tokens"] + synthesis_metrics["prompt_tokens"]
    total_completion = (
        extraction_metrics["completion_tokens"]
        + synthesis_metrics["completion_tokens"]
    )
    total_cost = None
    if (
        extraction_metrics["estimated_cost_usd"] is not None
        and synthesis_metrics["estimated_cost_usd"] is not None
    ):
        total_cost = (
            extraction_metrics["estimated_cost_usd"]
            + synthesis_metrics["estimated_cost_usd"]
        )
    metrics = {
        "extraction": extraction_metrics,
        "synthesis": synthesis_metrics,
        "total": {
            "prompt_tokens": total_prompt,
            "completion_tokens": total_completion,
            "total_tokens": total_prompt + total_completion,
            "reasoning_tokens_estimated_locally": (
                extraction_metrics["reasoning_tokens_estimated_locally"]
                + synthesis_metrics["reasoning_tokens_estimated_locally"]
            ),
            "final_content_tokens_estimated_locally": (
                extraction_metrics["final_content_tokens_estimated_locally"]
                + synthesis_metrics["final_content_tokens_estimated_locally"]
            ),
            "elapsed_seconds": (
                extraction_metrics["elapsed_seconds"]
                + synthesis_metrics["elapsed_seconds"]
            ),
            "estimated_cost_usd": total_cost,
            "pricing_configured": total_cost is not None,
        },
    }
    diagnostics = {
        "mode": "none",
        "query_count": len(user_object.get("retrieval_queries") or []),
        "raw_hit_count": 0,
        "unique_candidate_message_count": 0,
        "selected_suggestion_message_count": 0,
        "suggestion_range_count": 0,
        "final_ranges_overlapping_suggestions": 0,
        "final_ranges_outside_suggestions": len(ledger.records),
        "answer_relevant_ranges_overlapping_suggestions": 0,
        "answer_relevant_ranges_outside_suggestions": len(cited_ids),
        "suggestions_without_final_evidence": 0,
    }
    processing = {
        "direct_synthesis_input_tokens": synthesis_input_tokens,
        "synthesis_usable_input_tokens": _input_target(synthesis_operation),
        "compaction_applied": False,
        "compaction_levels": 0,
        "compaction_group_calls": 0,
    }
    usage = {
        "input_tokens": total_prompt,
        "output_tokens": total_completion,
        "source": "provider_reported",
        "estimated_cost": total_cost,
        "cost_complete": total_cost is not None,
        "currency": "USD",
    }
    assembled, _ = assemble_synthesis_result(
        synthesis.content,
        records=ledger.records,
        evidence_validation=evidence_validation,
        strategy="single_window_ledger",
        message_count=len(window.messages),
        planned_window_count=1,
        usable_window_count=1,
        unavailable_window_count=0,
        retrieval_diagnostics=diagnostics,
        ledger_processing=processing,
        usage=usage,
    )
    return ArmResult(
        label=label,
        thinking_enabled=thinking_enabled,
        extraction=extraction,
        synthesis=synthesis,
        extraction_input_tokens=extraction_input_tokens,
        synthesis_input_tokens=synthesis_input_tokens,
        accepted_range_count=validated.accepted_range_count,
        rejected_range_count=validated.rejected_range_count,
        assembled=assembled,
        metrics=metrics,
    )


def _answer_markdown(arm: ArmResult) -> list[str]:
    answer = arm.assembled
    lines = [
        f"## {arm.label}: synthesized answer",
        "",
        f"Completion status: `{answer['completion_status']}`  ",
        f"Answer source: `{answer['answer_source']}`  ",
        f"Validated ledger ranges: `{len(answer['evidence_ledger'])}`",
        "",
        "### Overview",
        "",
        answer.get("overview") or "[No structured overview returned.]",
        "",
        "### High-probability results",
        "",
    ]
    high = [item for item in answer["results"] if item["probability"] == "high_probability"]
    lower = [item for item in answer["results"] if item["probability"] == "lower_probability"]
    for item in high:
        lines.append(f"- {item['statement']} — ranges `{', '.join(item['verified_range_ids'])}`")
    if not high:
        lines.append("- None returned.")
    lines.extend(["", "### Lower-probability results", ""])
    for item in lower:
        lines.append(f"- {item['statement']} — ranges `{', '.join(item['verified_range_ids'])}`")
    if not lower:
        lines.append("- None returned.")
    lines.extend(
        [
            "",
            "### Evidence ledger",
            "",
            _fenced(json.dumps(answer["evidence_ledger"], indent=2, ensure_ascii=False)),
            "",
            "### Exact raw synthesis",
            "",
            _fenced(arm.synthesis.content),
        ]
    )
    return lines


def _write_comparison(
    path: Path,
    *,
    config_version: int,
    source_metadata: dict[str, Any],
    common_planner_metrics: dict[str, Any],
    off: ArmResult,
    on: ArmResult,
) -> None:
    off_total = off.metrics["total"]
    on_total = on.metrics["total"]
    completion_delta = on_total["completion_tokens"] - off_total["completion_tokens"]
    elapsed_delta = on_total["elapsed_seconds"] - off_total["elapsed_seconds"]
    lines = [
        "# GLM 5.2 reasoning A/B: 100K extraction and synthesis",
        "",
        "The same frozen corpus, question, analysis plan, current prompts, model, temperature, and schemas were used in both arms. The only payload difference was explicit thinking in the reasoning-on arm. No retries or fallbacks were used.",
        "",
        "## Controlled input",
        "",
        f"- Active configuration: `{config_version}`",
        f"- Model: `{TARGET_MODEL}`",
        f"- Question: `{source_metadata['question']}`",
        f"- Messages: `{source_metadata['message_count']:,}`",
        f"- Retrieval suggestions: `{source_metadata['had_suggestion_ranges']}`",
        "- Reasoning-off control: current production payload (reasoning control omitted)",
        "- Reasoning-on treatment: `chat_template_kwargs.enable_thinking=true`",
        "",
        "## Provider token and latency comparison",
        "",
        "Provider totals are exact values reported by NVIDIA. Reasoning/final-content splits are local tokenizer estimates because NVIDIA reports only combined completion tokens.",
        "",
        f"The one common frozen planning call used `{common_planner_metrics['prompt_tokens']:,}` input and `{common_planner_metrics['completion_tokens']:,}` output tokens in `{common_planner_metrics['elapsed_seconds']:.1f}` seconds. It is held constant and excluded from the arm delta below. Add those tokens to either arm for a complete one-search total.",
        "",
        "| Arm | Extraction input | Extraction output | Synthesis input | Synthesis output | Total input | Total output | Total tokens | Est. reasoning tokens | Call time | Configured USD cost |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for arm in (off, on):
        e = arm.metrics["extraction"]
        s = arm.metrics["synthesis"]
        total = arm.metrics["total"]
        cost = "not configured" if total["estimated_cost_usd"] is None else f"${total['estimated_cost_usd']:.6f}"
        lines.append(
            f"| {arm.label} | {e['prompt_tokens']:,} | {e['completion_tokens']:,} | "
            f"{s['prompt_tokens']:,} | {s['completion_tokens']:,} | {total['prompt_tokens']:,} | "
            f"{total['completion_tokens']:,} | {total['total_tokens']:,} | "
            f"{total['reasoning_tokens_estimated_locally']:,} | {total['elapsed_seconds']:.1f}s | {cost} |"
        )
    lines.extend(
        [
            "",
            f"Reasoning-on used `{completion_delta:+,}` completion tokens and `{elapsed_delta:+.1f}` seconds compared with reasoning-off.",
            "",
            f"Including the shared planner, the complete reasoning-off search used `{off_total['prompt_tokens'] + common_planner_metrics['prompt_tokens']:,}` input plus `{off_total['completion_tokens'] + common_planner_metrics['completion_tokens']:,}` output tokens (`{off_total['total_tokens'] + common_planner_metrics['total_tokens']:,}` total).",
            "",
            f"Including the shared planner, the complete reasoning-on search used `{on_total['prompt_tokens'] + common_planner_metrics['prompt_tokens']:,}` input plus `{on_total['completion_tokens'] + common_planner_metrics['completion_tokens']:,}` output tokens (`{on_total['total_tokens'] + common_planner_metrics['total_tokens']:,}` total).",
            "",
            "The active NVIDIA trial profile has no input/output prices configured, so the server cannot honestly report a dollar amount. Token counts are provided so a chosen commercial provider's rates can be applied directly.",
            "",
            *_answer_markdown(off),
            "",
            "---",
            "",
            *_answer_markdown(on),
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(".tmp")
        / "glm-reasoning-ab"
        / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    config_version, operations = _active_config()
    user_object, source_metadata = _captured_100k_user_object()
    analysis_plan, retrieval_queries, common_planner, common_planner_metrics = (
        _freeze_current_plan(
            question=str(user_object["question"]),
            operations=operations,
            output_dir=args.output_dir,
        )
    )
    user_object = {
        "task": "window_evidence_extraction",
        "question": user_object["question"],
        "analysis_plan": analysis_plan,
        "retrieval_queries": retrieval_queries,
        "suggestion_ranges": [],
        "window_id": user_object["window_id"],
        "messages": user_object["messages"],
    }

    off = _run_arm(
        label="reasoning_off",
        thinking_enabled=False,
        user_object=user_object,
        operations=operations,
        output_dir=args.output_dir,
    )
    on = _run_arm(
        label="reasoning_on",
        thinking_enabled=True,
        user_object=user_object,
        operations=operations,
        output_dir=args.output_dir,
    )
    _write_comparison(
        args.output_dir / "comparison.md",
        config_version=config_version,
        source_metadata=source_metadata,
        common_planner_metrics=common_planner_metrics,
        off=off,
        on=on,
    )
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "active_config_version": config_version,
        "model": TARGET_MODEL,
        "source": source_metadata,
        "controlled_variables": [
            "corpus messages",
            "question",
            "frozen analysis plan",
            "active extraction prompt",
            "active synthesis prompt",
            "model",
            "temperature",
            "structured output schemas",
        ],
        "only_payload_difference": "reasoning-on adds chat_template_kwargs.enable_thinking=true",
        "no_retry_or_fallback": True,
        "common_frozen_planner": {
            "metrics": common_planner_metrics,
            "output": json.loads(common_planner.content),
        },
        "reasoning_off": {
            "accepted_range_count": off.accepted_range_count,
            "rejected_range_count": off.rejected_range_count,
            "metrics": off.metrics,
            "assembled_result": off.assembled,
        },
        "reasoning_on": {
            "accepted_range_count": on.accepted_range_count,
            "rejected_range_count": on.rejected_range_count,
            "metrics": on.metrics,
            "assembled_result": on.assembled,
        },
    }
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"comparison: {(args.output_dir / 'comparison.md').resolve()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
