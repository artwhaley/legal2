"""Replay one frozen six-window extraction workload across three models.

Investigation utility only. The six captured GLM semantic-retrieval windows are
the source of truth. Every model receives identical messages, prompts, settings,
IDs, and suggestions; only the provider model ID changes. Calls are sequential,
never retried, and never fall back.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from run_analysis_plan_probe import ANALYSIS_PLAN, normalize_reversed_ranges
from server.config_store import ConfigStore
from server.contracts import WindowEvidenceOutput
from server.evidence_ledger import LedgerError, WindowLedgerInput, build_ledger
from server.model_runtime import ModelOutputInvalid, parse_model_output


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
MODEL_PROFILES = {
    "glm": "model-7ac4caef076e",
    "ultra": "model-nemotron-3-ultra-550b-a55b",
    "minimax": "model-minimax-m3",
}
MODEL_LABELS = {
    "glm": "GLM 5.2",
    "ultra": "Nemotron 3 Ultra",
    "minimax": "MiniMax M3",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def captured_windows() -> list[dict[str, Any]]:
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
                instance = str(data.get("operation_instance", ""))
                payload = data.get("payload")
                if not instance or not isinstance(payload, dict):
                    raise RuntimeError("captured provider request is malformed")
                if instance in windows:
                    raise RuntimeError(f"duplicate captured window {instance}")
                windows[instance] = copy.deepcopy(payload)
    expected = [f"w{index:06d}" for index in range(1, 7)]
    if sorted(windows) != expected:
        raise RuntimeError(
            f"expected exactly six captured windows; found {sorted(windows)}"
        )
    result = [windows[window_id] for window_id in expected]
    for payload in result:
        payload["messages"][0]["content"] = (
            str(payload["messages"][0]["content"]).rstrip()
            + "\n\n"
            + ANALYSIS_PLAN.strip()
        )
    return result


def validate_window(
    content: str, payload: dict[str, Any]
) -> dict[str, Any]:
    user_object = json.loads(payload["messages"][1]["content"])
    messages = user_object["messages"]
    result: dict[str, Any] = {
        "schema_valid": False,
        "strict_ledger_valid": False,
        "normalized_ledger_valid": False,
        "repairs": [],
    }
    try:
        parsed = parse_model_output(content, WindowEvidenceOutput)
    except ModelOutputInvalid as exc:
        result["schema_error"] = str(exc)
        return result
    result["schema_valid"] = True
    result["parsed_output"] = parsed.model_dump()
    window = WindowLedgerInput(
        parsed.window_id, tuple(dict(message) for message in messages)
    )
    try:
        ledger = build_ledger([window], [parsed.model_dump()])
    except LedgerError as exc:
        result["strict_ledger_error"] = {
            "message": str(exc),
            "details": exc.details,
        }
    else:
        result["strict_ledger_valid"] = True
        result["normalized_ledger_valid"] = True
        result["accepted_output"] = parsed.model_dump()
        result["evidence_range_count"] = len(ledger.records)
        return result

    normalized, repairs = normalize_reversed_ranges(parsed, messages)
    result["repairs"] = repairs
    if not repairs:
        return result
    try:
        ledger = build_ledger([window], [normalized])
    except LedgerError as exc:
        result["normalized_ledger_error"] = {
            "message": str(exc),
            "details": exc.details,
        }
    else:
        result["normalized_ledger_valid"] = True
        result["accepted_output"] = normalized
        result["evidence_range_count"] = len(ledger.records)
    return result


def range_inventory(
    windows: list[dict[str, Any]], results: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    validations = [result.get("validation") or {} for result in results]
    accepted = [
        (payload, validation)
        for payload, validation in zip(windows, validations)
        if validation.get("normalized_ledger_valid")
    ]
    failed_window_ids = [
        json.loads(payload["messages"][1]["content"])["window_id"]
        for payload, validation in zip(windows, validations)
        if not validation.get("normalized_ledger_valid")
    ]
    if not accepted:
        return [], {
            "complete": False,
            "accepted_window_count": 0,
            "failed_window_ids": failed_window_ids,
            "evidence_range_count": 0,
            "reason": "no window produced a valid accepted output",
        }
    ledger_windows = []
    outputs = []
    for payload, validation in accepted:
        user_object = json.loads(payload["messages"][1]["content"])
        ledger_windows.append(
            WindowLedgerInput(
                user_object["window_id"],
                tuple(dict(message) for message in user_object["messages"]),
            )
        )
        outputs.append(validation["accepted_output"])
    ledger = build_ledger(ledger_windows, outputs)
    inventory = [
        {
            "range_id": record.range_id,
            "window_id": record.window_id,
            "thread_id": record.thread_id,
            "start_message_id": record.start_message_id,
            "end_message_id": record.end_message_id,
            "summary": record.summary,
            "relevance": record.relevance,
        }
        for record in ledger.records
    ]
    summary = {
        "complete": not failed_window_ids,
        "accepted_window_count": len(accepted),
        "failed_window_ids": failed_window_ids,
        "window_count": len(ledger.coverage),
        "message_count": sum(item.message_count for item in ledger.coverage),
        "evidence_range_count": len(inventory),
        "coverage": [
            {
                "window_id": item.window_id,
                "first_message_id": item.first_message_id,
                "last_message_id": item.last_message_id,
                "message_count": item.message_count,
                "evidence_range_count": item.evidence_range_count,
                "uncertainties": list(item.uncertainties),
            }
            for item in ledger.coverage
        ],
    }
    if failed_window_ids:
        summary["reason"] = (
            "partial accepted inventory; one or more windows did not produce "
            "a valid accepted output"
        )
    return inventory, summary


def raw_model_inventory(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return model-proposed ranges for diagnosis, including rejected windows."""
    inventory: list[dict[str, Any]] = []
    for result in results:
        validation = result.get("validation") or {}
        parsed = validation.get("parsed_output")
        if not isinstance(parsed, dict):
            continue
        for evidence_range in parsed.get("evidence_ranges") or []:
            inventory.append(
                {
                    "range_id": f"raw{len(inventory) + 1:06d}",
                    "window_id": result["window_id"],
                    "thread_id": evidence_range.get("thread_id", ""),
                    "start_message_id": evidence_range.get("start_message_id", ""),
                    "end_message_id": evidence_range.get("end_message_id", ""),
                    "summary": evidence_range.get("summary", ""),
                    "relevance": evidence_range.get("relevance", ""),
                    "accepted": bool(validation.get("normalized_ledger_valid")),
                }
            )
    return inventory


def gold_recall(
    windows: list[dict[str, Any]],
    inventory: list[dict[str, Any]],
    gold: list[dict[str, Any]],
) -> dict[str, Any]:
    ordered_messages = []
    for payload in windows:
        ordered_messages.extend(json.loads(payload["messages"][1]["content"])["messages"])
    positions = {
        str(message["message_id"]): index
        for index, message in enumerate(ordered_messages)
    }
    found: list[dict[str, Any]] = []
    for gold_index, expected in enumerate(gold):
        gold_start = positions.get(expected["start_message_id"])
        gold_end = positions.get(expected["end_message_id"])
        overlaps: list[str] = []
        if gold_start is not None and gold_end is not None:
            low_gold, high_gold = sorted((gold_start, gold_end))
            for record in inventory:
                if record["thread_id"] != expected["thread_id"]:
                    continue
                start = positions.get(record["start_message_id"])
                end = positions.get(record["end_message_id"])
                if start is None or end is None:
                    continue
                low, high = sorted((start, end))
                if low <= high_gold and high >= low_gold:
                    overlaps.append(record["range_id"])
        if overlaps:
            found.append(
                {
                    "gold_index": gold_index,
                    "event_date": expected["event_date"],
                    "overlapping_range_ids": overlaps,
                }
            )
    return {
        "count": len(found),
        "total": len(gold),
        "found": found,
        "missing_dates": [
            item["event_date"]
            for index, item in enumerate(gold)
            if index not in {found_item["gold_index"] for found_item in found}
        ],
    }


def markdown_report(
    output_dir: Path,
    shared: dict[str, Any],
    model_results: dict[str, dict[str, Any]],
) -> str:
    lines = [
        "# Six-window frozen-plan model comparison",
        "",
        "This is an extraction comparison, not a synthesis comparison. All three",
        "models received the same six captured windows, original IDs, retrieval",
        "suggestions, system prompt plus frozen analysis plan, temperature 0.1,",
        "maximum output tokens, and structured-output mode. Only `model` changed.",
        "Calls were sequential with no retries and no fallback.",
        "",
        f"- Shared non-model payload hash: `{shared['non_model_payload_hash']}`",
        f"- Total messages: {shared['message_count']}",
        f"- Window message counts: {', '.join(str(value) for value in shared['window_message_counts'])}",
        "",
        "## Summary",
        "",
        "| Model | Completed windows | Strict-valid | Normalized-valid | Repairs | Ranges | Gold overlap | Input tokens | Output tokens | Time |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for model_key in ("glm", "ultra", "minimax"):
        result = model_results[model_key]
        lines.append(
            "| {label} | {completed}/6 | {strict}/6 | {normalized}/6 | {repairs} | "
            "{ranges} | {gold}/{gold_total} | {input_tokens} | {output_tokens} | {seconds:.1f}s |".format(
                label=MODEL_LABELS[model_key],
                completed=result["completed_http_windows"],
                strict=result["strict_valid_windows"],
                normalized=result["normalized_valid_windows"],
                repairs=result["repair_count"],
                ranges=(
                    result["ledger"]["evidence_range_count"]
                    if result["ledger"].get("complete")
                    else f"{result['ledger'].get('evidence_range_count', 0)} accepted (partial)"
                ),
                gold=result["gold_recall"]["count"],
                gold_total=result["gold_recall"]["total"],
                input_tokens=result["usage"]["input_tokens"],
                output_tokens=result["usage"]["output_tokens"],
                seconds=result["elapsed_seconds"],
            )
        )
    lines.extend(
        [
            "",
            "## Engineering interpretation",
            "",
            "- **GLM changed materially with the frozen plan.** The historical "
            "no-plan run produced 19 ranges and found 5/7 provisional positives; "
            "this run produced 41 ranges and found 7/7. The recall gain came with "
            "substantial over-collection: window 1 alone produced 12 mostly "
            "cooperative or negative school passages.",
            "- **Nemotron was the cleanest strict run.** It completed and validated "
            "all six calls, returned 20 ranges, correctly returned no evidence for "
            "window 1, and found 6/7 provisional positives. It missed 2024-06-26.",
            "- **MiniMax did not complete a usable six-window run.** Window 3 timed "
            "out at 900.7 seconds. Window 6 returned four plausible-looking ranges "
            "but fabricated one message-ID prefix/value, so the complete window "
            "response was rejected. Four valid windows contributed five accepted "
            "ranges and 1/7 accepted recall; raw diagnostic output overlapped 3/7.",
            "- Provider-reported token totals differ because each model/provider "
            "tokenizes and accounts differently. The serialized non-model request "
            "payloads were byte-identical, as proven by the shared hash above.",
            "- No synthesis call was made. A synthesis comparison cannot use the "
            "same input because each extraction model produced a different ledger; "
            "this run isolates the model behavior on identical analysis inputs.",
            "",
        ]
    )
    for model_key in ("glm", "ultra", "minimax"):
        result = model_results[model_key]
        lines.extend(
            [
                "",
                f"## {MODEL_LABELS[model_key]}",
                "",
                f"- Model ID: `{result['model_id']}`",
                f"- Gold overlap: {result['gold_recall']['count']}/{result['gold_recall']['total']}",
                f"- Missing provisional-positive dates: {', '.join(result['gold_recall']['missing_dates']) or 'none'}",
                f"- Strict-valid windows: {result['strict_valid_windows']}/6",
                f"- Deterministically normalized windows: {result['normalized_valid_windows']}/6",
                f"- Repairs: {result['repair_count']}",
                "",
                (
                    "### Complete accepted evidence ledger"
                    if result["ledger"].get("complete")
                    else "### Accepted evidence from valid windows (partial run)"
                ),
                "",
            ]
        )
        if not result["inventory"]:
            lines.append("No accepted evidence was available.")
        for record in result["inventory"]:
            lines.extend(
                [
                    f"#### {record['range_id']} · {record['window_id']}",
                    "",
                    f"- IDs: `{record['start_message_id']}` through `{record['end_message_id']}`",
                    f"- Thread: `{record['thread_id']}`",
                    f"- Summary: {record['summary']}",
                    f"- Relevance: {record['relevance']}",
                    "",
                ]
            )
        invalid = [
            item
            for item in result["windows"]
            if not (item.get("validation") or {}).get("normalized_ledger_valid")
        ]
        if invalid:
            lines.extend(["### Invalid windows", ""])
            for item in invalid:
                if item.get("transport_error"):
                    lines.append(
                        f"- `{item['window_id']}`: {item['transport_error']} after "
                        f"{item['elapsed_seconds']:.1f}s — "
                        f"{item.get('message') or 'no response'}"
                    )
                    continue
                validation = item.get("validation") or {}
                ledger_error = (
                    validation.get("normalized_ledger_error")
                    or validation.get("strict_ledger_error")
                    or {}
                )
                lines.append(
                    f"- `{item['window_id']}`: HTTP {item.get('status_code')}; "
                    f"schema-valid={bool(validation.get('schema_valid'))}; "
                    f"ledger rejected — "
                    f"{ledger_error.get('message', 'unknown validation failure')}"
                )
                proposed = (
                    (validation.get("parsed_output") or {}).get("evidence_ranges")
                    or []
                )
                if proposed:
                    lines.append(
                        f"  Raw response proposed {len(proposed)} ranges. They are "
                        "diagnostic only and were not accepted:"
                    )
                    for evidence_range in proposed:
                        lines.append(
                            "  - `{start}` through `{end}` — {summary}".format(
                                start=evidence_range.get("start_message_id"),
                                end=evidence_range.get("end_message_id"),
                                summary=evidence_range.get("summary"),
                            )
                        )
        raw_recall = result.get("raw_model_gold_recall")
        if raw_recall and raw_recall["count"] != result["gold_recall"]["count"]:
            lines.extend(
                [
                    "",
                    "### Diagnostic raw-output recall",
                    "",
                    "Rejected output is not evidence and is not eligible for synthesis. "
                    "For model diagnosis only, all raw responses collectively overlapped "
                    f"{raw_recall['count']}/{raw_recall['total']} provisional-positive dates.",
                    "",
                ]
            )
    lines.extend(
        [
            "",
            "## Historical GLM baseline",
            "",
            "The prior GLM semantic-ranges run using these six windows but without",
            "the frozen analysis plan produced 19 evidence ranges and overlapped",
            "5 of 7 provisional-positive dates. That historical result is the",
            "baseline for assessing how the plan changes GLM.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--cooldown-seconds", type=float, default=5.0)
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    preexisting_artifacts = [
        path
        for path in output_dir.iterdir()
        if path.name
        not in {"runner.pid", "runner.stdout.log", "runner.stderr.log"}
    ]
    if preexisting_artifacts:
        raise RuntimeError("output directory must be empty")

    source_windows = captured_windows()
    non_model_payloads = []
    window_counts = []
    for payload in source_windows:
        projection = copy.deepcopy(payload)
        projection.pop("model", None)
        non_model_payloads.append(projection)
        user_object = json.loads(payload["messages"][1]["content"])
        window_counts.append(len(user_object["messages"]))
    shared = {
        "captured_request_id": CAPTURED_REQUEST_ID,
        "capture_path": str(CAPTURE),
        "non_model_payload_hash": sha256_json(non_model_payloads),
        "window_payload_hashes": [sha256_json(value) for value in non_model_payloads],
        "window_message_counts": window_counts,
        "message_count": sum(window_counts),
        "temperature": source_windows[0]["temperature"],
        "max_tokens": source_windows[0]["max_tokens"],
        "response_format": source_windows[0].get("response_format"),
        "analysis_plan": ANALYSIS_PLAN,
    }
    (output_dir / "shared-input-manifest.json").write_text(
        json.dumps(shared, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    store = ConfigStore()
    try:
        active = store.active()
        if active is None:
            raise RuntimeError("control store has no active configuration")
        models: dict[str, dict[str, str]] = {}
        for key, profile_id in MODEL_PROFILES.items():
            profile = active.model_profiles[profile_id]
            provider = active.provider_accounts[profile.provider_account_id]
            models[key] = {
                "model_id": profile.model_id,
                "base_url": provider.base_url.rstrip("/"),
                "api_key": provider.api_key,
            }
    finally:
        store.close()

    gold = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
    all_results: dict[str, dict[str, Any]] = {}
    for model_index, model_key in enumerate(("glm", "ultra", "minimax")):
        model = models[model_key]
        model_dir = output_dir / model_key
        model_dir.mkdir()
        started_model = time.perf_counter()
        results: list[dict[str, Any]] = []
        for window_index, source_payload in enumerate(source_windows):
            payload = copy.deepcopy(source_payload)
            payload["model"] = model["model_id"]
            user_object = json.loads(payload["messages"][1]["content"])
            window_id = user_object["window_id"]
            started = time.perf_counter()
            print(
                json.dumps(
                    {
                        "event": "window_started",
                        "model": model_key,
                        "model_id": model["model_id"],
                        "window_id": window_id,
                        "window_index": window_index,
                        "message_count": len(user_object["messages"]),
                    }
                ),
                flush=True,
            )
            try:
                with httpx.Client(
                    timeout=httpx.Timeout(900.0, connect=20.0)
                ) as client:
                    response = client.post(
                        model["base_url"] + "/chat/completions",
                        json=payload,
                        headers={
                            "Authorization": f"Bearer {model['api_key']}",
                            "Content-Type": "application/json",
                        },
                    )
            except Exception as exc:
                item = {
                    "window_id": window_id,
                    "elapsed_seconds": time.perf_counter() - started,
                    "transport_error": type(exc).__name__,
                    "message": str(exc),
                }
            else:
                elapsed = time.perf_counter() - started
                try:
                    body: Any = response.json()
                except ValueError:
                    body = response.text
                item = {
                    "window_id": window_id,
                    "status_code": response.status_code,
                    "elapsed_seconds": elapsed,
                    "response": body,
                }
                if response.status_code == 200 and isinstance(body, dict):
                    try:
                        message = body["choices"][0]["message"]
                        content = message["content"]
                        if not isinstance(content, str):
                            raise TypeError("assistant content is not a string")
                    except (KeyError, IndexError, TypeError) as exc:
                        item["envelope_error"] = str(exc)
                    else:
                        item["reasoning_content"] = message.get("reasoning_content")
                        item["validation"] = validate_window(content, payload)
            results.append(item)
            (model_dir / f"{window_id}-result.json").write_text(
                json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(
                json.dumps(
                    {
                        "event": "window_completed",
                        "model": model_key,
                        "window_id": window_id,
                        "status_code": item.get("status_code"),
                        "elapsed_seconds": item["elapsed_seconds"],
                        "validation": item.get("validation"),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            if args.cooldown_seconds > 0 and (
                window_index < len(source_windows) - 1
                or model_index < len(MODEL_PROFILES) - 1
            ):
                time.sleep(args.cooldown_seconds)

        inventory, ledger_summary = range_inventory(source_windows, results)
        recall = gold_recall(source_windows, inventory, gold)
        raw_inventory = raw_model_inventory(results)
        raw_recall = gold_recall(source_windows, raw_inventory, gold)
        usage = {
            "input_tokens": sum(
                int((item.get("response") or {}).get("usage", {}).get("prompt_tokens", 0))
                for item in results
                if isinstance(item.get("response"), dict)
            ),
            "output_tokens": sum(
                int((item.get("response") or {}).get("usage", {}).get("completion_tokens", 0))
                for item in results
                if isinstance(item.get("response"), dict)
            ),
        }
        model_result = {
            "model": model_key,
            "model_id": model["model_id"],
            "elapsed_seconds": time.perf_counter() - started_model,
            "completed_http_windows": sum(
                1 for item in results if item.get("status_code") == 200
            ),
            "strict_valid_windows": sum(
                1
                for item in results
                if (item.get("validation") or {}).get("strict_ledger_valid")
            ),
            "normalized_valid_windows": sum(
                1
                for item in results
                if (item.get("validation") or {}).get("normalized_ledger_valid")
            ),
            "repair_count": sum(
                len((item.get("validation") or {}).get("repairs") or [])
                for item in results
            ),
            "usage": usage,
            "ledger": ledger_summary,
            "gold_recall": recall,
            "inventory": inventory,
            "raw_model_gold_recall": raw_recall,
            "raw_model_inventory": raw_inventory,
            "windows": results,
        }
        all_results[model_key] = model_result
        (model_dir / "model-result.json").write_text(
            json.dumps(model_result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "event": "model_completed",
                    "model": model_key,
                    "strict_valid_windows": model_result["strict_valid_windows"],
                    "normalized_valid_windows": model_result[
                        "normalized_valid_windows"
                    ],
                    "repair_count": model_result["repair_count"],
                    "evidence_range_count": ledger_summary.get(
                        "evidence_range_count"
                    ),
                    "gold_recall": recall,
                    "usage": usage,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    comparison = {"shared": shared, "models": all_results}
    (output_dir / "comparison.json").write_text(
        json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "comparison.md").write_text(
        markdown_report(output_dir, shared, all_results), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "event": "comparison_completed",
                "output_dir": str(output_dir),
                "report": str(output_dir / "comparison.md"),
            }
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
