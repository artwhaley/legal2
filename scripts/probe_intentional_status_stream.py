"""Probe intentional user-facing status blocks without changing the server.

The experimental response remains one strict JSON object. A short
``status_reports`` array is emitted first, followed by the ordinary extraction
fields. The probe strips the experimental field and validates the final result
with the production extraction and ledger validators.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from server.contracts import SCHEMA_REGISTRY, WindowEvidenceEnvelope
from server.evidence_ledger import WindowLedgerInput, build_ledger, salvage_window_evidence
from server.model_runtime import parse_model_output
from server.token_accounting import (
    build_provider_payload,
    canonical_json,
    count_provider_payload,
    count_text_tokens,
)
try:
    from scripts.probe_glm_reasoning_stream import (
        TARGET_MODEL,
        _active_config,
        _captured_100k_user_object,
        _fenced,
    )
except ModuleNotFoundError:  # direct ``python scripts/...`` execution
    from probe_glm_reasoning_stream import (
        TARGET_MODEL,
        _active_config,
        _captured_100k_user_object,
        _fenced,
    )


STATUS_APPENDIX = """

ISOLATED STATUS-STREAM PROBE OVERRIDE
For this probe only, replace the ordinary final response shape with the exact
shape below. Keep every substantive extraction instruction above unchanged.
Emit status_reports as the first property so they can be shown while the rest
of the final extraction is generated.

Return two to four short status reports. Each must be no more than 35 words and
must report a concrete completed review milestone or preliminary finding useful
to a human waiting for the answer. Do not expose hidden reasoning, deliberation,
discarded-candidate lists, or unverifiable percentage-complete claims. Do not
pad the reports with generic statements. Reports are provisional and must not
replace, constrain, or truncate the complete final extraction.

Return exactly:
{"status_reports":[{"sequence":1,"message":"short concrete user-facing update"}],"window_id":"the supplied window_id","evidence_ranges":[{"thread_id":"supplied thread ID","start_message_id":"supplied message ID","end_message_id":"supplied message ID","summary":"what this passage shows","relevance":"how it answers or may answer the plan"}],"uncertainties":["specific uncertainty"]}
""".strip()


_STATUS_PATTERN = re.compile(
    r'\{\s*"sequence"\s*:\s*(?P<sequence>\d+)\s*,\s*'
    r'"message"\s*:\s*(?P<message>"(?:\\.|[^"\\])*")\s*\}'
)


def _status_schema() -> dict[str, Any]:
    production = SCHEMA_REGISTRY["window_evidence_extraction"]["model_output"]
    properties = {
        "status_reports": {
            "type": "array",
            "minItems": 2,
            "maxItems": 4,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "sequence": {"type": "integer", "minimum": 1, "maximum": 4},
                    "message": {"type": "string"},
                },
                "required": ["sequence", "message"],
            },
        },
        **production["properties"],
    }
    return {
        "type": "object",
        "title": "StatusStreamingWindowEvidenceEnvelope",
        "additionalProperties": False,
        "properties": properties,
        "required": [
            "status_reports",
            "window_id",
            "evidence_ranges",
            "uncertainties",
        ],
    }


def _current_user_object(ab_manifest: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = json.loads(ab_manifest.read_text(encoding="utf-8"))
    common = manifest["common_frozen_planner"]["output"]
    frozen = {
        key: value
        for key, value in common.items()
        if key != "retrieval_queries"
    }
    queries = [
        {"query_id": f"q{index:04d}", "text": text}
        for index, text in enumerate(common["retrieval_queries"], start=1)
    ]
    captured, source = _captured_100k_user_object()
    return {
        "task": "window_evidence_extraction",
        "question": captured["question"],
        "analysis_plan": frozen,
        "retrieval_queries": queries,
        "suggestion_ranges": [],
        "window_id": captured["window_id"],
        "messages": captured["messages"],
    }, source


def _baseline(ab_manifest: Path) -> dict[str, Any]:
    manifest = json.loads(ab_manifest.read_text(encoding="utf-8"))
    metrics = manifest["reasoning_off"]["metrics"]["extraction"]
    ledger = manifest["reasoning_off"]["assembled_result"]["evidence_ledger"]
    return {
        "prompt_tokens": metrics["prompt_tokens"],
        "completion_tokens": metrics["completion_tokens"],
        "elapsed_seconds": metrics["elapsed_seconds"],
        "ranges": [
            [item["start_message_id"], item["end_message_id"]] for item in ledger
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--ab-manifest",
        type=Path,
        default=Path(".tmp/glm-reasoning-ab/run2-20260731/manifest.json"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(".tmp")
        / "intentional-status-probe"
        / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)

    config_version, operations = _active_config()
    production_operation = operations["window_evidence_extraction"]
    if production_operation.model_id != TARGET_MODEL:
        raise RuntimeError("the active extraction model is no longer GLM 5.2")
    operation = replace(
        production_operation,
        system_prompt=production_operation.system_prompt + "\n\n" + STATUS_APPENDIX,
    )
    user_object, source = _current_user_object(args.ab_manifest)
    schema = _status_schema()
    wire = [
        {"role": "system", "content": operation.system_prompt},
        {"role": "user", "content": canonical_json(user_object)},
    ]
    payload = build_provider_payload(
        operation,
        operation="window_evidence_extraction_status_probe",
        messages=wire,
        user_object=user_object,
        response_schema=schema,
    )
    accounting = count_provider_payload(payload, operation)
    if not accounting.fits:
        raise RuntimeError("experimental status payload does not fit the active budget")
    payload["stream"] = True
    payload["stream_options"] = {"include_usage": True}

    started = time.perf_counter()
    buffer = ""
    statuses: list[dict[str, Any]] = []
    seen_statuses: set[int] = set()
    usage = None
    finish_reason = None
    first_content_seconds = None
    timeout = httpx.Timeout(
        operation.read_timeout_seconds,
        connect=operation.connect_timeout_seconds,
        write=operation.write_timeout_seconds,
        pool=operation.pool_timeout_seconds,
    )
    print("intentional status probe: starting", flush=True)
    with httpx.Client(timeout=timeout) as client:
        with client.stream(
            "POST",
            f"{operation.base_url}/chat/completions",
            json=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {operation.api_key}",
            },
        ) as response:
            if response.status_code >= 400:
                raise RuntimeError(
                    f"provider returned HTTP {response.status_code}: "
                    + response.read().decode("utf-8", errors="replace")
                )
            for line in response.iter_lines():
                if not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if not raw or raw == "[DONE]":
                    continue
                event = json.loads(raw)
                if isinstance(event.get("usage"), dict):
                    usage = event["usage"]
                choices = event.get("choices")
                if not isinstance(choices, list) or not choices:
                    continue
                choice = choices[0]
                if choice.get("finish_reason") is not None:
                    finish_reason = str(choice["finish_reason"])
                content = (choice.get("delta") or {}).get("content")
                if not isinstance(content, str) or not content:
                    continue
                now = time.perf_counter() - started
                if first_content_seconds is None:
                    first_content_seconds = now
                buffer += content
                for match in _STATUS_PATTERN.finditer(buffer):
                    sequence = int(match.group("sequence"))
                    if sequence in seen_statuses:
                        continue
                    seen_statuses.add(sequence)
                    statuses.append(
                        {
                            "sequence": sequence,
                            "message": json.loads(match.group("message")),
                            "available_at_seconds": now,
                        }
                    )
                    print(
                        f"status {sequence} at {now:.2f}s: {statuses[-1]['message']}",
                        flush=True,
                    )

    elapsed = time.perf_counter() - started
    raw_result = json.loads(buffer)
    reported_statuses = raw_result.pop("status_reports")
    final_content = canonical_json(raw_result)
    parse_model_output(final_content, WindowEvidenceEnvelope)
    window = WindowLedgerInput(
        str(user_object["window_id"]), tuple(user_object["messages"])
    )
    validated = salvage_window_evidence(window, raw_result)
    ledger = build_ledger([window], [validated])
    if not isinstance(usage, dict):
        raise RuntimeError("provider did not report token usage")
    baseline = _baseline(args.ab_manifest)
    experimental_ranges = [
        [record.start_message_id, record.end_message_id] for record in ledger.records
    ]
    prompt_tokens = int(usage["prompt_tokens"])
    completion_tokens = int(usage["completion_tokens"])
    summary = {
        "active_config_version": config_version,
        "model": operation.model_id,
        "source": source,
        "no_retry_or_fallback": True,
        "reasoning_enabled": False,
        "production_counted_input_tokens_before_stream_controls": accounting.input_tokens,
        "provider_usage": usage,
        "finish_reason": finish_reason,
        "first_content_seconds": first_content_seconds,
        "statuses": statuses,
        "reported_statuses_match_stream_parser": [
            {"sequence": item["sequence"], "message": item["message"]}
            for item in statuses
        ] == reported_statuses,
        "final_available_at_seconds": elapsed,
        "final_schema_valid": True,
        "accepted_range_count": validated.accepted_range_count,
        "rejected_range_count": validated.rejected_range_count,
        "experimental_ranges": experimental_ranges,
        "baseline": baseline,
        "delta": {
            "prompt_tokens": prompt_tokens - baseline["prompt_tokens"],
            "completion_tokens": completion_tokens - baseline["completion_tokens"],
            "elapsed_seconds": elapsed - baseline["elapsed_seconds"],
            "range_count": len(experimental_ranges) - len(baseline["ranges"]),
        },
        "local_status_tokens_estimate": count_text_tokens(
            canonical_json(reported_statuses), operation
        ),
    }
    (args.output_dir / "manifest.json").write_text(
        json.dumps(
            {**summary, "final_extraction": raw_result},
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    lines = [
        "# Intentional status-stream probe",
        "",
        "This isolated direct-provider probe made no server, client, configuration, or EVW changes. The model returned short user-facing status objects before its final extraction object. No reasoning stream, retry, or fallback was used.",
        "",
        "## Timing and token comparison",
        "",
        "| Metric | Reasoning-off production baseline | Intentional status probe | Delta |",
        "|---|---:|---:|---:|",
        f"| Input tokens | {baseline['prompt_tokens']:,} | {prompt_tokens:,} | {summary['delta']['prompt_tokens']:+,} |",
        f"| Output tokens | {baseline['completion_tokens']:,} | {completion_tokens:,} | {summary['delta']['completion_tokens']:+,} |",
        f"| Elapsed | {baseline['elapsed_seconds']:.2f}s | {elapsed:.2f}s | {summary['delta']['elapsed_seconds']:+.2f}s |",
        f"| Evidence ranges | {len(baseline['ranges'])} | {len(experimental_ranges)} | {summary['delta']['range_count']:+d} |",
        "",
        f"The status array itself is approximately `{summary['local_status_tokens_estimate']}` tokens using the configured local accounting tokenizer.",
        "",
        "## Statuses as they became available",
        "",
    ]
    for item in statuses:
        lines.append(
            f"- **{item['available_at_seconds']:.2f}s:** {item['message']}"
        )
    lines.extend(
        [
            "",
            f"The complete extraction became available at **{elapsed:.2f}s**.",
            "",
            "## Baseline ranges",
            "",
            _fenced(json.dumps(baseline["ranges"], indent=2, ensure_ascii=False)),
            "",
            "## Experimental ranges",
            "",
            _fenced(json.dumps(experimental_ranges, indent=2, ensure_ascii=False)),
            "",
            "## Final extraction",
            "",
            _fenced(json.dumps(raw_result, indent=2, ensure_ascii=False)),
        ]
    )
    (args.output_dir / "report.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    print(f"report: {(args.output_dir / 'report.md').resolve()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
