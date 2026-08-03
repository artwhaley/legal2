"""Run two complete corpus-first 100K GLM analyses and inspect cache usage.

Order is deliberately production-realistic:
school planner -> school extraction -> school synthesis -> grandma planner ->
grandma extraction -> grandma synthesis. The single extraction window uses an
identical corpus-first prefix in both searches. No retry or fallback is used.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from server.provider import _cache_usage
from server.token_accounting import canonical_json

try:
    from scripts.probe_glm_reasoning_stream import _active_config, _captured_100k_user_object
    from scripts.run_glm_reasoning_ab import _answer_markdown, _freeze_current_plan, _run_arm
except ModuleNotFoundError:
    from probe_glm_reasoning_stream import _active_config, _captured_100k_user_object
    from run_glm_reasoning_ab import _answer_markdown, _freeze_current_plan, _run_arm


QUERIES = (
    ("school", "When did we fight about school?"),
    ("grandma", "When did we talk about grandma?"),
)


def _sha(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _cache(result: Any) -> dict[str, Any]:
    usage = result.usage if isinstance(result.usage, dict) else {}
    read, write, miss, reported = _cache_usage(usage)
    return {
        "cache_read_input_tokens": read,
        "cache_write_input_tokens": write,
        "cache_miss_input_tokens": miss,
        "cache_usage_reported": reported,
        "raw_provider_usage": usage,
    }


def _run_query(
    *,
    key: str,
    question: str,
    source: dict[str, Any],
    operations: dict[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    output_dir.mkdir()
    plan, retrieval_queries, planner, planner_metrics = _freeze_current_plan(
        question=question,
        operations=operations,
        output_dir=output_dir,
    )
    # Insertion order is the experiment: the stable corpus precedes every
    # query-dependent field while retaining the exact same keys and values.
    extraction_user = {
        "task": "window_evidence_extraction",
        "window_id": source["window_id"],
        "messages": source["messages"],
        "question": question,
        "analysis_plan": plan,
        "retrieval_queries": retrieval_queries,
        "suggestion_ranges": [],
    }
    arm = _run_arm(
        label=key,
        thinking_enabled=False,
        user_object=extraction_user,
        operations=operations,
        output_dir=output_dir,
    )
    result = arm.assembled
    return {
        "key": key,
        "question": question,
        "analysis_plan": plan,
        "retrieval_queries": retrieval_queries,
        "message_count": len(source["messages"]),
        "stable_extraction_prefix_hash": _sha(
            {
                "task": "window_evidence_extraction",
                "window_id": source["window_id"],
                "messages": source["messages"],
            }
        ),
        "planner": {
            "metrics": planner_metrics,
            "cache": _cache(planner),
            "output": json.loads(planner.content),
        },
        "extraction": {
            "metrics": arm.metrics["extraction"],
            "cache": _cache(arm.extraction),
            "accepted_range_count": arm.accepted_range_count,
            "rejected_range_count": arm.rejected_range_count,
            "schema_valid": arm.extraction.schema_valid,
            "provider_request_id": arm.extraction.provider_request_id,
        },
        "synthesis": {
            "metrics": arm.metrics["synthesis"],
            "cache": _cache(arm.synthesis),
            "schema_valid": arm.synthesis.schema_valid,
            "provider_request_id": arm.synthesis.provider_request_id,
        },
        "high_result_count": sum(
            item["probability"] == "high_probability" for item in result["results"]
        ),
        "lower_result_count": sum(
            item["probability"] == "lower_probability" for item in result["results"]
        ),
        "unclassified_evidence_count": len(result["unclassified_evidence"]),
        "unverified_statement_count": len(result["unverified_model_statements"]),
        "completion_status": result["completion_status"],
        "synthesis_validation_status": result["synthesis_validation"]["status"],
        "assembled_result": result,
        "arm": arm,
    }


def _report(manifest: dict[str, Any], results: list[dict[str, Any]]) -> str:
    lines = [
        "# 100K corpus-first cache sequence",
        "",
        "The school query completed planning, extraction, and synthesis before the grandma query began. The second query then completed the same three stages. Extraction messages and window identity were byte-identical and placed before all query-dependent fields. No retry or fallback was used.",
        "",
        f"- Active configuration: `{manifest['active_config_version']}`",
        f"- Model: `{manifest['model']}`",
        f"- Messages: `{manifest['source']['message_count']:,}`",
        f"- Stable extraction prefix hash: `{manifest['stable_extraction_prefix_hash']}`",
        "",
        "| Query | Accepted ranges | Rejected | High | Lower | Extraction cache read | Extraction cache miss | Cache telemetry |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for item in results:
        cache = item["extraction"]["cache"]
        reported = "reported" if cache["cache_usage_reported"] else "not reported"
        lines.append(
            f"| {item['key']} | {item['extraction']['accepted_range_count']} | {item['extraction']['rejected_range_count']} | {item['high_result_count']} | {item['lower_result_count']} | {cache['cache_read_input_tokens']:,} | {cache['cache_miss_input_tokens']:,} | {reported} |"
        )
    lines.extend(
        [
            "",
            "A zero paired with `not reported` is not evidence of a cache miss. It means the provider response omitted recognized cache-accounting fields.",
        ]
    )
    for item in results:
        lines.extend(["", "---", "", *_answer_markdown(item["arm"])])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(".tmp")
        / "100k-corpus-cache-sequence"
        / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)

    config_version, operations = _active_config()
    source, source_metadata = _captured_100k_user_object()
    source = {
        "window_id": source["window_id"],
        "messages": source["messages"],
    }
    results = []
    for key, question in QUERIES:
        print(f"{key}: complete analysis starting", flush=True)
        result = _run_query(
            key=key,
            question=question,
            source=source,
            operations=operations,
            output_dir=args.output_dir / key,
        )
        results.append(result)
        print(
            f"{key}: complete analysis finished; "
            f"{result['high_result_count']} high, {result['lower_result_count']} lower",
            flush=True,
        )

    prefix_hashes = {item["stable_extraction_prefix_hash"] for item in results}
    if len(prefix_hashes) != 1:
        raise RuntimeError("the two extraction corpus prefixes were not identical")
    serializable_results = [
        {key: value for key, value in item.items() if key != "arm"} for item in results
    ]
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "active_config_version": config_version,
        "model": operations["window_evidence_extraction"].model_id,
        "source": source_metadata,
        "stable_extraction_prefix_hash": next(iter(prefix_hashes)),
        "call_order": [
            "school_planner",
            "school_extraction",
            "school_synthesis",
            "grandma_planner",
            "grandma_extraction",
            "grandma_synthesis",
        ],
        "packing": [
            "task",
            "window_id",
            "messages",
            "question",
            "analysis_plan",
            "retrieval_queries",
            "suggestion_ranges",
        ],
        "no_retry_or_fallback": True,
        "results": serializable_results,
    }
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (args.output_dir / "report.md").write_text(
        _report(manifest, results), encoding="utf-8"
    )
    print(f"report: {(args.output_dir / 'report.md').resolve()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
