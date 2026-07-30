"""Replay one captured extraction window with a frozen analysis plan.

This is an investigation utility, not a production execution path. It performs
exactly one provider call, never retries, never falls back, and writes the raw
request/response plus strict-validation results for review.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from server.config_store import ConfigStore
from server.contracts import WindowEvidenceOutput
from server.evidence_ledger import LedgerError, WindowLedgerInput, build_ledger
from server.model_runtime import ModelOutputInvalid, parse_model_output


ANALYSIS_PLAN = """REQUEST-SCOPED ANALYSIS PLAN

Original question: "When did we fight about school?"

Analysis brief:
Identify and date every materially distinct exchange in which the conversation
participants were in conflict about school, education, homeschooling, academic
quality or progress, curriculum, school-related schedules, educational costs,
or responsibility for educational decisions.

Relevance criteria:
- Treat "fight" behaviorally, not as a required literal word.
- Include direct arguments, disagreements, challenges, accusations, criticism,
  defensiveness, competing proposals, or sustained tense exchanges.
- Include conflicts that combine education with parenting time, gymnastics or
  activity schedules, money, tuition, workload, or responsibility when the
  educational issue is a material part of the disagreement.
- Include evidence that supports, contradicts, weakens, narrows, or qualifies
  whether an exchange was a fight about school.
- When a passage is plausibly relevant but borderline, return it and explain
  the uncertainty instead of silently excluding it.

Exclusion criteria:
- Exclude purely cooperative or neutral school logistics with no disagreement,
  criticism, accusation, competing position, or tension.
- Do not treat a dispute involving an unrelated third party as a fight between
  the conversation participants unless their own disagreement is also shown.

Ambiguities to preserve:
- "Fight" may range from an explicit argument to a meaningful disagreement; do
  not require insults, raised voices, or use of the word "fight."
- A conflict may be partly about school and partly about another issue. Include
  it when education is material and describe the overlap.

Answer requirements:
- Preserve each distinct responsive exchange rather than selecting only the
  strongest example.
- Capture enough surrounding messages to show both positions and context.
- The eventual answer must identify when each exchange occurred and what the
  school-related disagreement concerned.

This plan interprets the question but is not evidence and is not an exhaustive
filter. The original question remains authoritative. Inspect every supplied
message and return relevant evidence even when it falls outside these examples.
"""


PROBES = {
    "minimax": {
        "capture": Path.home()
        / ".message_evidence_server"
        / "debug-captures"
        / "20260730T022045Z-bf99b0ac9134.jsonl",
        "request_id": "fc5acfe9-9484-4954-82b0-703678345c81",
        "operation_instance": "w000002",
        "model_profile_id": "model-minimax-m3",
        "native": {
            "temperature": 1.0,
            "top_p": 0.95,
            "chat_template_kwargs": {"thinking_mode": "enabled"},
        },
    },
    "ultra": {
        "capture": Path.home()
        / ".message_evidence_server"
        / "debug-captures"
        / "20260730T020559Z-795d639cba73.jsonl",
        "request_id": "05b5cc1f-bac7-4fb1-97f6-b7284c700792",
        "operation_instance": "w000002",
        "model_profile_id": "model-nemotron-3-ultra-550b-a55b",
        "native": {
            "temperature": 1.0,
            "top_p": 0.95,
            "chat_template_kwargs": {
                "enable_thinking": True,
                "medium_effort": True,
            },
        },
    },
}


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def read_captured_payload(spec: dict[str, Any]) -> dict[str, Any]:
    capture = Path(spec["capture"])
    with capture.open("r", encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            data = record.get("data") or {}
            if (
                record.get("request_id") == spec["request_id"]
                and record.get("kind") == "provider_request"
                and data.get("operation") == "window_evidence_extraction"
                and data.get("operation_instance") == spec["operation_instance"]
            ):
                payload = data.get("payload")
                if not isinstance(payload, dict):
                    raise RuntimeError("captured provider request has no payload")
                return copy.deepcopy(payload)
    raise RuntimeError("captured extraction payload was not found")


def normalize_reversed_ranges(
    output: WindowEvidenceOutput, messages: list[dict[str, Any]]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    normalized = output.model_dump()
    positions = {
        str(message["message_id"]): index for index, message in enumerate(messages)
    }
    repairs: list[dict[str, Any]] = []
    for index, evidence_range in enumerate(normalized["evidence_ranges"]):
        start = evidence_range["start_message_id"]
        end = evidence_range["end_message_id"]
        if start not in positions or end not in positions:
            continue
        if positions[start] <= positions[end]:
            continue
        selected = messages[positions[end] : positions[start] + 1]
        thread_id = evidence_range["thread_id"]
        if not selected or any(
            str(message.get("thread_id", "")) != thread_id for message in selected
        ):
            continue
        evidence_range["start_message_id"] = end
        evidence_range["end_message_id"] = start
        repairs.append(
            {
                "range_index": index,
                "reason": "reversed_in_supplied_message_order",
                "original_start_message_id": start,
                "original_end_message_id": end,
                "normalized_start_message_id": end,
                "normalized_end_message_id": start,
                "original_start_message_index": positions[start],
                "original_end_message_index": positions[end],
            }
        )
    return normalized, repairs


def validate_content(
    content: str, messages: list[dict[str, Any]]
) -> dict[str, Any]:
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
        result["normalized_output"] = normalized
        result["evidence_range_count"] = len(ledger.records)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=sorted(PROBES), required=True)
    parser.add_argument("--mode", choices=("current", "native"), required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    spec = PROBES[args.model]
    payload = read_captured_payload(spec)
    payload["messages"][0]["content"] = (
        str(payload["messages"][0]["content"]).rstrip()
        + "\n\n"
        + ANALYSIS_PLAN.strip()
    )
    if args.mode == "native":
        payload.update(copy.deepcopy(spec["native"]))

    user_object = json.loads(payload["messages"][1]["content"])
    messages = user_object["messages"]
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{args.model}-{args.mode}"

    store = ConfigStore()
    try:
        active = store.active()
        if active is None:
            raise RuntimeError("server control store has no active configuration")
        profile = active.model_profiles[spec["model_profile_id"]]
        provider = active.provider_accounts[profile.provider_account_id]
        if payload["model"] != profile.model_id:
            raise RuntimeError("captured model does not match configured profile")
        api_key = provider.api_key
        url = provider.base_url.rstrip("/") + "/chat/completions"
    finally:
        store.close()

    sanitized_request = {
        "probe": args.model,
        "mode": args.mode,
        "captured_request_id": spec["request_id"],
        "captured_operation_instance": spec["operation_instance"],
        "provider_url": url,
        "payload": payload,
    }
    (output_dir / f"{stem}-request.json").write_text(
        json.dumps(sanitized_request, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "event": "probe_started",
                "model": args.model,
                "mode": args.mode,
                "message_count": len(messages),
                "temperature": payload.get("temperature"),
                "top_p": payload.get("top_p"),
                "chat_template_kwargs": payload.get("chat_template_kwargs"),
                "timestamp": utc_stamp(),
            }
        ),
        flush=True,
    )
    started = time.perf_counter()
    try:
        with httpx.Client(timeout=httpx.Timeout(900.0, connect=20.0)) as client:
            response = client.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            )
    except Exception as exc:
        failure = {
            "transport_error": type(exc).__name__,
            "message": str(exc),
            "elapsed_seconds": time.perf_counter() - started,
        }
        (output_dir / f"{stem}-result.json").write_text(
            json.dumps(failure, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps({"event": "probe_failed", **failure}), flush=True)
        return 2

    elapsed = time.perf_counter() - started
    try:
        response_body: Any = response.json()
    except ValueError:
        response_body = response.text
    result: dict[str, Any] = {
        "status_code": response.status_code,
        "elapsed_seconds": elapsed,
        "response": response_body,
    }
    if response.status_code == 200 and isinstance(response_body, dict):
        try:
            message = response_body["choices"][0]["message"]
            content = message["content"]
            if not isinstance(content, str):
                raise TypeError("assistant content is not a string")
        except (KeyError, IndexError, TypeError) as exc:
            result["envelope_error"] = str(exc)
        else:
            result["reasoning_content"] = message.get("reasoning_content")
            result["validation"] = validate_content(content, messages)

    (output_dir / f"{stem}-result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    summary = {
        "event": "probe_completed",
        "model": args.model,
        "mode": args.mode,
        "status_code": response.status_code,
        "elapsed_seconds": elapsed,
        "usage": response_body.get("usage")
        if isinstance(response_body, dict)
        else None,
        "validation": result.get("validation"),
        "result_path": str(output_dir / f"{stem}-result.json"),
    }
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return 0 if response.status_code == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
