"""Run the frozen six-window school-query prompt-packing A/B.

This is an explicit investigation utility. Both arms use the same provider,
model, prompts, plan, retrieval hints, windows, generation settings, and
synthesis packing. Only the extraction user-object field order changes.
Provider calls are sequential and are never retried or failed over.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import httpx

from server.config_store import ConfigStore
from server.contracts import AnalysisPlanningOutput, SCHEMA_REGISTRY
from server.conversation_unified import _record_payload
from server.evidence_ledger import (
    EvidenceRangeRecord,
    WindowLedgerInput,
    build_ledger,
    salvage_window_evidence,
)
from server.model_runtime import parse_model_output
from server.provider import _cache_usage
from server.result_validation import assemble_synthesis_result
from server.token_accounting import build_provider_payload, canonical_json, count_provider_payload


QUESTION = "When did we fight about school?"
CAPTURE = (
    Path.home()
    / ".message_evidence_server"
    / "debug-captures"
    / "20260730T010423Z-b75d5baec026.jsonl"
)
CAPTURED_REQUEST_ID = "f3c8cf84-e2bb-4a64-8e23-5f8743daf02b"
GOLD_PATH = (
    Path(".tmp")
    / "retrieval-hint-experiment"
    / "20260730T010423Z-audit"
    / "provisional-gold.json"
)
ARMS = ("current", "corpus_first")


def _hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _captured_windows() -> list[dict[str, Any]]:
    windows: dict[str, dict[str, Any]] = {}
    with CAPTURE.open("r", encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            data = record.get("data") or {}
            if (
                record.get("request_id") == CAPTURED_REQUEST_ID
                and record.get("kind") == "provider_request"
                and data.get("operation") == "window_evidence_extraction"
                and data.get("attempt") == 1
            ):
                raw_payload = data.get("payload")
                if not isinstance(raw_payload, dict):
                    raise RuntimeError("captured extraction payload is malformed")
                raw_user = json.loads(raw_payload["messages"][1]["content"])
                windows[str(raw_user["window_id"])] = raw_user
    expected = [f"w{index:06d}" for index in range(1, 7)]
    if sorted(windows) != expected:
        raise RuntimeError(f"expected six frozen windows; found {sorted(windows)}")
    return [windows[window_id] for window_id in expected]


def _post(
    client: httpx.Client,
    *,
    operation_name: str,
    operation: Any,
    api_key: str,
    user_object: dict[str, Any],
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    wire = [
        {"role": "system", "content": operation.system_prompt},
        {"role": "user", "content": canonical_json(user_object)},
    ]
    payload = build_provider_payload(
        operation,
        operation=operation_name,
        messages=wire,
        user_object=user_object,
        response_schema=SCHEMA_REGISTRY[operation_name]["model_output"],
    )
    accounting = count_provider_payload(payload, operation)
    if not accounting.fits:
        raise RuntimeError(f"{operation_name} payload exceeds its configured budget")
    started = time.perf_counter()
    response = client.post(
        operation.base_url.rstrip("/") + "/chat/completions",
        json=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    elapsed = time.perf_counter() - started
    try:
        body = response.json()
    except ValueError as exc:
        raise RuntimeError(f"{operation_name} returned non-JSON HTTP {response.status_code}") from exc
    if response.status_code != 200:
        raise RuntimeError(f"{operation_name} returned HTTP {response.status_code}: {body}")
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"{operation_name} returned an invalid response envelope") from exc
    if not isinstance(content, str):
        raise RuntimeError(f"{operation_name} returned non-text content")
    usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
    cache_read, cache_write, cache_miss, cache_reported = _cache_usage(usage)
    stats = {
        "elapsed_seconds": elapsed,
        "input_tokens": int(usage.get("prompt_tokens", accounting.input_tokens)),
        "output_tokens": int(usage.get("completion_tokens", 0)),
        "cache_read_input_tokens": cache_read,
        "cache_write_input_tokens": cache_write,
        "cache_miss_input_tokens": cache_miss,
        "cache_usage_reported": cache_reported,
        "provider_request_id": response.headers.get("x-request-id"),
        "payload_hash": _hash(payload),
    }
    return content, body, stats


def _extraction_user(
    arm: str,
    source: Mapping[str, Any],
    analysis_plan: Mapping[str, Any],
) -> dict[str, Any]:
    common = {
        "task": "window_evidence_extraction",
        "question": QUESTION,
        "analysis_plan": dict(analysis_plan),
        "retrieval_queries": copy.deepcopy(source["retrieval_queries"]),
        "suggestion_ranges": copy.deepcopy(source["suggestion_ranges"]),
        "window_id": source["window_id"],
        "messages": copy.deepcopy(source["messages"]),
    }
    if arm == "current":
        return common
    if arm == "corpus_first":
        return {
            "task": common["task"],
            "window_id": common["window_id"],
            "messages": common["messages"],
            "question": common["question"],
            "analysis_plan": common["analysis_plan"],
            "retrieval_queries": common["retrieval_queries"],
            "suggestion_ranges": common["suggestion_ranges"],
        }
    raise ValueError(f"unknown arm {arm}")


def _ledger_payload(ledger: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    metadata = [
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
    coverage = [
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
    return metadata, coverage


def _gold_recall(
    windows: Sequence[WindowLedgerInput],
    records: Sequence[EvidenceRangeRecord],
    gold: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    ordered = [message for window in windows for message in window.messages]
    positions = {str(message["message_id"]): index for index, message in enumerate(ordered)}
    found = []
    for expected in gold:
        gold_start = positions.get(str(expected["start_message_id"]))
        gold_end = positions.get(str(expected["end_message_id"]))
        overlaps = []
        if gold_start is not None and gold_end is not None:
            gold_low, gold_high = sorted((gold_start, gold_end))
            for record in records:
                if record.thread_id != expected["thread_id"]:
                    continue
                start = positions.get(record.start_message_id)
                end = positions.get(record.end_message_id)
                if start is None or end is None:
                    continue
                low, high = sorted((start, end))
                if low <= gold_high and high >= gold_low:
                    overlaps.append(record.range_id)
        if overlaps:
            found.append({"event_date": expected["event_date"], "range_ids": overlaps})
    dates = {item["event_date"] for item in found}
    return {
        "count": len(found),
        "total": len(gold),
        "found": found,
        "missing_dates": [item["event_date"] for item in gold if item["event_date"] not in dates],
    }


def _usage_total(calls: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    fields = (
        "input_tokens",
        "output_tokens",
        "cache_read_input_tokens",
        "cache_write_input_tokens",
        "cache_miss_input_tokens",
    )
    result = {field: sum(int(call.get(field, 0)) for call in calls) for field in fields}
    result["cache_reported_calls"] = sum(bool(call.get("cache_usage_reported")) for call in calls)
    result["call_count"] = len(calls)
    result["elapsed_seconds"] = sum(float(call.get("elapsed_seconds", 0)) for call in calls)
    return result


def _report(output: Mapping[str, Any]) -> str:
    lines = [
        "# School-query prompt-packing A/B",
        "",
        f"Run: `{output['run_id']}`  ",
        f"Model: `{output['model_id']}`  ",
        f"Question: {QUESTION}",
        "",
        "Only extraction JSON field order differed. The current arm put the question and plan before messages; the experimental arm put each frozen message window before the question and plan. Calls were sequential, with no retries or fallback.",
        "",
        "| Arm | Extraction gold | Final cited gold | Ledger ranges | High results | Lower results | Rejected | Normalized | Cache read | Cache miss | Cache reported |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for arm in ARMS:
        value = output["arms"][arm]
        usage = value["usage"]
        lines.append(
            f"| {arm} | {value['extraction_gold_recall']['count']}/7 | {value['final_gold_recall']['count']}/7 | {value['ledger_range_count']} | {value['high_result_count']} | {value['lower_result_count']} | {value['rejected_range_count']} | {value['normalized_range_count']} | {usage['cache_read_input_tokens']} | {usage['cache_miss_input_tokens']} | {usage['cache_reported_calls']}/{usage['call_count']} |"
        )
    for arm in ARMS:
        value = output["arms"][arm]
        lines.extend(["", f"## {arm}", "", f"Overview: {value['result'].get('overview') or '[unavailable]'}", ""])
        for index, item in enumerate(value["result"]["results"], start=1):
            lines.append(
                f"{index}. **{item.get('probability') or 'unclassified'}** — {item['statement']} "
                f"(ranges: {', '.join(item['verified_range_ids'])})"
            )
        lines.extend(
            [
                "",
                f"Extraction missing dates: {', '.join(value['extraction_gold_recall']['missing_dates']) or 'none'}",
                f"Final cited missing dates: {', '.join(value['final_gold_recall']['missing_dates']) or 'none'}",
                f"Unclassified ledger ranges: {len(value['result']['unclassified_evidence'])}",
                f"Unverified model statements: {len(value['result']['unverified_model_statements'])}",
                f"Synthesis validation: {value['result']['synthesis_validation']['status']}",
                f"Extraction warnings: {value['extraction_warning_count']}",
            ]
        )
    lines.extend(
        [
            "",
            "## Cache telemetry interpretation",
            "",
            "Cache counters above are reported by the provider, not inferred. Zero with zero reported calls means the endpoint omitted cache accounting; it does not prove a cache miss. This paired quality run is not itself a warm-cache benchmark because the two arms intentionally have different prefixes.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.resume and args.output_dir is None:
        raise RuntimeError("--resume requires --output-dir")
    run_id = (
        args.output_dir.name
        if args.resume and args.output_dir is not None
        else datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    )
    output_dir = (args.output_dir or Path(".tmp") / "prompt-packing-ab" / run_id).resolve()
    output_dir.mkdir(parents=True, exist_ok=args.resume)

    source_users = _captured_windows()
    gold = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
    store = ConfigStore()
    try:
        active = store.active()
        if active is None:
            raise RuntimeError("control store has no active configuration")
        operations = active.operations
        secrets = {name: operation.api_key for name, operation in operations.items()}
        config_version = active.config_version
    finally:
        store.close()

    output: dict[str, Any] = {
        "run_id": run_id,
        "question": QUESTION,
        "config_version": config_version,
        "model_id": operations["window_evidence_extraction"].model_id,
        "capture": str(CAPTURE),
        "captured_request_id": CAPTURED_REQUEST_ID,
        "arms": {},
    }
    timeout = httpx.Timeout(900.0, connect=20.0)
    with httpx.Client(timeout=timeout) as client:
        planning_path = output_dir / "planning-response.json"
        if args.resume and planning_path.is_file():
            plan_body = json.loads(planning_path.read_text(encoding="utf-8"))
            plan_content = plan_body["choices"][0]["message"]["content"]
            usage = plan_body.get("usage") if isinstance(plan_body.get("usage"), dict) else {}
            cache_read, cache_write, cache_miss, cache_reported = _cache_usage(usage)
            plan_usage = {
                "elapsed_seconds": 0.0,
                "input_tokens": int(usage.get("prompt_tokens", 0)),
                "output_tokens": int(usage.get("completion_tokens", 0)),
                "cache_read_input_tokens": cache_read,
                "cache_write_input_tokens": cache_write,
                "cache_miss_input_tokens": cache_miss,
                "cache_usage_reported": cache_reported,
                "provider_request_id": None,
                "payload_hash": None,
                "resumed_from_artifact": True,
            }
            print(json.dumps({"event": "planning_resumed_from_artifact"}), flush=True)
        else:
            planning_user = {"task": "analysis_planning", "question": QUESTION}
            print(json.dumps({"event": "planning_started"}), flush=True)
            plan_content, plan_body, plan_usage = _post(
                client,
                operation_name="analysis_planning",
                operation=operations["analysis_planning"],
                api_key=secrets["analysis_planning"],
                user_object=planning_user,
            )
        plan = parse_model_output(plan_content, AnalysisPlanningOutput)
        analysis_plan = plan.model_dump(exclude={"retrieval_queries"})
        planning_path.write_text(json.dumps(plan_body, ensure_ascii=False, indent=2), encoding="utf-8")
        output["analysis_plan"] = analysis_plan
        output["planning_usage"] = plan_usage
        print(json.dumps({"event": "planning_completed", "analysis_question": plan.analysis_question}), flush=True)

        arm_windows: dict[str, list[WindowLedgerInput]] = {arm: [] for arm in ARMS}
        arm_outputs: dict[str, list[Any]] = {arm: [] for arm in ARMS}
        arm_call_stats: dict[str, list[dict[str, Any]]] = {arm: [] for arm in ARMS}
        arm_window_details: dict[str, list[dict[str, Any]]] = {arm: [] for arm in ARMS}
        for window_index, source in enumerate(source_users):
            order = ARMS if window_index % 2 == 0 else tuple(reversed(ARMS))
            for arm in order:
                user_object = _extraction_user(arm, source, analysis_plan)
                window = WindowLedgerInput(
                    str(user_object["window_id"]),
                    tuple(dict(message) for message in user_object["messages"]),
                )
                artifact_path = output_dir / f"{arm}-{window.window_id}.json"
                if args.resume and artifact_path.is_file():
                    detail = json.loads(artifact_path.read_text(encoding="utf-8"))
                    body = detail["response"]
                    content = body["choices"][0]["message"]["content"]
                    stats = detail["stats"]
                    validated = salvage_window_evidence(window, json.loads(content.strip()))
                    print(json.dumps({"event": "window_resumed_from_artifact", "arm": arm, "window_id": window.window_id}), flush=True)
                else:
                    print(json.dumps({"event": "window_started", "arm": arm, "window_id": window.window_id}), flush=True)
                    try:
                        content, body, stats = _post(
                            client,
                            operation_name="window_evidence_extraction",
                            operation=operations["window_evidence_extraction"],
                            api_key=secrets["window_evidence_extraction"],
                            user_object=user_object,
                        )
                    except Exception as exc:
                        failure_path = output_dir / f"failure-{arm}-{window.window_id}-{int(time.time())}.json"
                        failure_path.write_text(json.dumps({"stage": "extraction", "arm": arm, "window_id": window.window_id, "error_type": type(exc).__name__, "error": str(exc)}, ensure_ascii=False, indent=2), encoding="utf-8")
                        raise
                    raw = json.loads(content.strip())
                    validated = salvage_window_evidence(window, raw)
                    detail = {
                        "window_id": window.window_id,
                        "accepted_range_count": validated.accepted_range_count,
                        "rejected_range_count": validated.rejected_range_count,
                        "normalized_range_count": validated.normalized_range_count,
                        "warning_count": len(validated.warnings),
                        "stats": stats,
                        "response": body,
                    }
                    artifact_path.write_text(json.dumps(detail, ensure_ascii=False, indent=2), encoding="utf-8")
                arm_windows[arm].append(window)
                arm_outputs[arm].append(validated)
                arm_call_stats[arm].append(stats)
                arm_window_details[arm].append(detail)
                print(json.dumps({"event": "window_completed", "arm": arm, "window_id": window.window_id, "accepted": validated.accepted_range_count, "rejected": validated.rejected_range_count}), flush=True)

        for arm in ARMS:
            pairs = sorted(zip(arm_windows[arm], arm_outputs[arm]), key=lambda pair: pair[0].window_id)
            windows = [pair[0] for pair in pairs]
            validated_outputs = [pair[1] for pair in pairs]
            ledger = build_ledger(windows, validated_outputs)
            metadata, coverage = _ledger_payload(ledger)
            synthesis_user = {
                "task": "ledger_synthesis",
                "question": QUESTION,
                "analysis_plan": analysis_plan,
                "coverage_report": coverage,
                "evidence_validation_summary": ledger.validation,
                "ledger_metadata": metadata,
                "records_or_highest_level_summaries": [_record_payload(record) for record in ledger.records],
            }
            synthesis_path = output_dir / f"{arm}-synthesis-response.json"
            if args.resume and synthesis_path.is_file():
                synthesis_artifact = json.loads(synthesis_path.read_text(encoding="utf-8"))
                synthesis_body = synthesis_artifact["response"]
                synthesis_stats = synthesis_artifact["stats"]
                synthesis_content = synthesis_body["choices"][0]["message"]["content"]
                print(json.dumps({"event": "synthesis_resumed_from_artifact", "arm": arm}), flush=True)
            else:
                print(json.dumps({"event": "synthesis_started", "arm": arm, "ranges": len(ledger.records)}), flush=True)
                synthesis_content, synthesis_body, synthesis_stats = _post(
                    client,
                    operation_name="ledger_synthesis",
                    operation=operations["ledger_synthesis"],
                    api_key=secrets["ledger_synthesis"],
                    user_object=synthesis_user,
                )
                synthesis_path.write_text(json.dumps({"stats": synthesis_stats, "response": synthesis_body}, ensure_ascii=False, indent=2), encoding="utf-8")
            all_stats = [*arm_call_stats[arm], synthesis_stats]
            suggestion_ranges = [item for source in source_users for item in source["suggestion_ranges"]]
            suggestion_hit_ids = {
                str(message_id)
                for suggestion in suggestion_ranges
                for message_id in suggestion.get("hit_message_ids", [])
            }
            diagnostics = {
                "mode": "semantic_ranges",
                "query_count": len(source_users[0]["retrieval_queries"]),
                "raw_hit_count": sum(len(item.get("hit_message_ids", [])) for item in suggestion_ranges),
                "unique_candidate_message_count": len(suggestion_hit_ids),
                "selected_suggestion_message_count": len(suggestion_hit_ids),
                "suggestion_range_count": len(suggestion_ranges),
                "final_ranges_overlapping_suggestions": 0,
                "final_ranges_outside_suggestions": len(ledger.records),
                "answer_relevant_ranges_overlapping_suggestions": 0,
                "answer_relevant_ranges_outside_suggestions": 0,
                "suggestions_without_final_evidence": len(suggestion_hit_ids),
            }
            synthesis_operation = operations["ledger_synthesis"]
            processing = {
                "direct_synthesis_input_tokens": synthesis_stats["input_tokens"],
                "synthesis_usable_input_tokens": synthesis_operation.context_window_tokens - synthesis_operation.max_output_tokens - synthesis_operation.safety_margin_tokens,
                "compaction_applied": False,
                "compaction_levels": 0,
                "compaction_group_calls": 0,
            }
            result, _ = assemble_synthesis_result(
                synthesis_content,
                records=ledger.records,
                evidence_validation=ledger.validation,
                strategy="multi_window_ledger",
                message_count=sum(len(window.messages) for window in windows),
                planned_window_count=len(windows),
                usable_window_count=len(windows),
                unavailable_window_count=0,
                retrieval_diagnostics=diagnostics,
                ledger_processing=processing,
                usage={"input_tokens": 0, "output_tokens": 0, "source": "provider_reported", "estimated_cost": None, "cost_complete": False, "currency": "USD"},
            )
            cited = {range_id for item in result["results"] for range_id in item["verified_range_ids"]}
            final_records = [record for record in ledger.records if record.range_id in cited]
            arm_result = {
                "window_details": sorted(arm_window_details[arm], key=lambda item: item["window_id"]),
                "ledger_range_count": len(ledger.records),
                "rejected_range_count": int(ledger.validation["rejected_range_count"]),
                "normalized_range_count": int(ledger.validation["normalized_range_count"]),
                "extraction_warning_count": len(ledger.validation["warnings"]),
                "extraction_gold_recall": _gold_recall(windows, ledger.records, gold),
                "final_gold_recall": _gold_recall(windows, final_records, gold),
                "high_result_count": sum(item["probability"] == "high_probability" for item in result["results"]),
                "lower_result_count": sum(item["probability"] == "lower_probability" for item in result["results"]),
                "usage": _usage_total(all_stats),
                "synthesis_stats": synthesis_stats,
                "result": result,
                "synthesis_response": synthesis_body,
            }
            output["arms"][arm] = arm_result
            (output_dir / f"{arm}-final.json").write_text(json.dumps(arm_result, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"event": "synthesis_completed", "arm": arm, "high": arm_result["high_result_count"], "lower": arm_result["lower_result_count"], "gold": arm_result["final_gold_recall"]["count"]}), flush=True)

    (output_dir / "results.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "report.md").write_text(_report(output), encoding="utf-8")
    print(json.dumps({"event": "completed", "output_dir": str(output_dir)}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
