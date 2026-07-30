"""Execute the one authorized RPV1-900 diagnostic run.

This runner performs one plan, one query-embedding workload, one read-only
revision-4 lookup, and one conversational analysis request. It never retries
the diagnostic sequence or changes provider/model selection.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from server.config_store import ConfigStore
from server.conversation_unified import _window_input_target, count_working_corpus_tokens
from server.contracts import parse_ndjson_event

try:
    from scripts.run_retrieval_hint_experiment import (
        ExperimentError,
        HttpClient,
        ReadOnlyCorpus,
        _admin_post,
        _analysis_context,
        _atomic_json,
        _atomic_text,
        _ensure_debug_capture,
        _local_candidates,
        _require_capture,
        _utc_now,
    )
except ModuleNotFoundError:  # direct ``python scripts/...`` execution
    from run_retrieval_hint_experiment import (
        ExperimentError,
        HttpClient,
        ReadOnlyCorpus,
        _admin_post,
        _analysis_context,
        _atomic_json,
        _atomic_text,
        _ensure_debug_capture,
        _local_candidates,
        _require_capture,
        _utc_now,
    )


QUESTION = "Show me fights about school."
EVW = Path(".tmp/sfv1-fixture-multicorpus-v15.evw")
REVISION_ID = 4
TEMPORARY_UTILIZATION = 60.0


def _active_config_summary(store: ConfigStore) -> dict[str, Any]:
    config = store.active()
    if config is None:
        raise ExperimentError("no active schema-v4 configuration is available")
    operations = {}
    for name, assignment in config.operation_assignments.items():
        profile = config.model_profiles[assignment.model_profile_id]
        operations[name] = {
            "model_profile_id": assignment.model_profile_id,
            "model_id": profile.model_id,
            "context_window_tokens": profile.context_window_tokens,
            "max_output_tokens": assignment.max_output_tokens,
            "target_input_tokens": assignment.target_input_tokens,
            "temperature": assignment.temperature,
        }
    return {
        "config_version": config.config_version,
        "config_schema_version": 4,
        "host": config.host,
        "port": config.port,
        "retrieval_assistance_mode": config.global_config.retrieval_assistance_mode,
        "window_input_utilization_percent": config.global_config.window_input_utilization_percent,
        "embedding": {
            "model_name": config.embedding.model_name,
            "required_dimensions": config.embedding.required_dimensions,
            "normalization": config.embedding.normalization,
        },
        "operations": operations,
    }


def _set_window_utilization(client: HttpClient, value: float) -> dict[str, Any]:
    status, _, body = client.request("GET", "/admin/server")
    if status != 200:
        raise ExperimentError(f"GET /admin/server returned HTTP {status}")
    page = body.decode("utf-8")
    try:
        from scripts.run_retrieval_hint_experiment import _extract_form
    except ModuleNotFoundError:
        from run_retrieval_hint_experiment import _extract_form

    fields = _extract_form(page, "server-editor")
    field = "global_config.window_input_utilization_percent"
    if field not in fields:
        raise ExperimentError("server admin form does not expose window utilization")
    fields[field] = str(value)
    fields["action"] = "save_server"
    fields["return_page"] = "server"
    request = urllib.request.Request(
        client.base_url + "/admin/action",
        data=urllib.parse.urlencode(fields).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "text/html"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            response.read()
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ExperimentError(f"saving window utilization {value} failed: {exc}") from exc
    status, _, body = client.request("GET", "/admin/server")
    if status != 200:
        raise ExperimentError("could not reload server admin page after saving window utilization")
    _admin_post(client, body.decode("utf-8"), "validate", "server")
    status, _, body = client.request("GET", "/admin/server")
    if status != 200:
        raise ExperimentError("could not reload server admin page after validating window utilization")
    _admin_post(client, body.decode("utf-8"), "activate", "server")
    return client.json("GET", "/admin/events")


def _event_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    for event in events:
        parse_ndjson_event(event, endpoint="/v1/conversational-analysis")
    sequences = [event.get("sequence") for event in events]
    if sequences != list(range(1, len(events) + 1)):
        raise ExperimentError("analysis stream sequence is not exact and monotonic")
    plan = next((event for event in events if event.get("event") == "window_plan_created"), None)
    windows = [event for event in events if event.get("event") == "window_completed"]
    unavailable = [event for event in events if event.get("event") == "window_unavailable"]
    return {
        "window_plan": plan,
        "window_count": plan.get("data", {}).get("window_count") if plan else None,
        "per_window": [
            {
                "window_id": event["data"]["window_id"],
                "window_index": event["data"]["window_index"],
                "window_count": event["data"]["window_count"],
                "accepted_range_count": event["data"]["accepted_range_count"],
                "rejected_range_count": event["data"]["rejected_range_count"],
                "normalized_range_count": event["data"]["normalized_range_count"],
                "validation_status": event["data"]["validation_status"],
                "input_tokens": event["data"]["input_tokens"],
                "output_tokens": event["data"]["output_tokens"],
                "usage_source": event["data"]["usage_source"],
                "estimated_cost": event["data"]["estimated_cost"],
            }
            for event in windows
        ],
        "unavailable_windows": [event["data"] for event in unavailable],
        "unusable_output_events": [event["data"] for event in events if event.get("event") == "window_output_unusable"],
        "preflight": [
            event["data"]
            for event in events
            if event.get("event") in {"ledger_synthesis_preflight", "ledger_compaction_required", "ledger_compaction_completed"}
        ],
        "terminal_event": events[-1].get("event") if events else None,
    }


def _markdown(result: dict[str, Any], manifest: dict[str, Any]) -> str:
    lines = [
        "# RPV1-900 live validation",
        "",
        f"- Question: `{manifest['question']}`",
        f"- Analysis plan ID: `{manifest['analysis_plan_id']}`",
        f"- Completion status: **{result.get('completion_status')}**",
        f"- Window count: **{result.get('coverage', {}).get('planned_window_count')}**",
        f"- Evidence validation: **{result.get('evidence_validation', {}).get('status')}**",
        "",
        "## Actual overview",
        "",
        result.get("overview") or result.get("raw_answer") or "Synthesis unavailable; see retained evidence below.",
        "",
        "## High-probability results",
        "",
        json.dumps([item for item in result.get("results", []) if item.get("probability") == "high_probability"], indent=2, ensure_ascii=False),
        "",
        "---",
        "",
        "## Lower-probability results",
        "",
        "```json",
        json.dumps([item for item in result.get("results", []) if item.get("probability") == "lower_probability"], indent=2, ensure_ascii=False),
        "```",
        "",
        "## Unclassified evidence and unverified statements",
        "",
        "```json",
        json.dumps({"unclassified_evidence": result.get("unclassified_evidence", []), "unverified_model_statements": result.get("unverified_model_statements", [])}, indent=2, ensure_ascii=False),
        "```",
        "",
        "## Warnings and complete ledger metadata",
        "",
        "```json",
        json.dumps({"warnings": result.get("synthesis_validation", {}).get("warnings", []), "evidence_ledger": result.get("evidence_ledger", [])}, indent=2, ensure_ascii=False),
        "```",
        "",
        "## Validation diagnostics, uncertainties, usage, and timing",
        "",
        "```json",
        json.dumps({
            "evidence_validation": result.get("evidence_validation"),
            "uncertainties": result.get("uncertainties"),
            "retrieval_diagnostics": result.get("retrieval_diagnostics"),
            "ledger_processing": result.get("ledger_processing"),
            "usage": result.get("usage"),
            "timing": manifest.get("timing"),
        }, indent=2, ensure_ascii=False),
        "```",
        "",
        "## Quality review",
        "",
        "The ledger retains every accepted candidate. Review the high-probability, lower-probability, unclassified, and unverified sections together; this run records the model output without tuning or rerunning.",
        "",
    ]
    return "\n".join(lines)


def run(server_url: str, evw_path: Path, output_root: Path) -> Path:
    output_dir = output_root / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    output_dir.mkdir(parents=True, exist_ok=False)
    client = HttpClient(server_url)
    store = ConfigStore()
    corpus = ReadOnlyCorpus(evw_path, REVISION_ID)
    before = _active_config_summary(store)
    corpus_tokens = count_working_corpus_tokens(corpus.messages, store.active().operations["window_evidence_extraction"])
    _, active_target = _window_input_target(
        store.active().operations["window_evidence_extraction"],
        before["window_input_utilization_percent"],
    )
    lower_bound = corpus_tokens / active_target
    temporary_changed = False
    capture_session_id: str | None = None
    terminal_result: dict[str, Any] | None = None
    analysis_plan_id: str | None = None
    analysis_events: list[dict[str, Any]] = []
    started_at = _utc_now()
    try:
        if before["config_schema_version"] != 4:
            raise ExperimentError("active configuration is not schema v4")
        if before["retrieval_assistance_mode"] != "semantic_ranges":
            raise ExperimentError("active retrieval mode is not semantic_ranges")
        if lower_bound < 6:
            _set_window_utilization(client, TEMPORARY_UTILIZATION)
            temporary_changed = True
        adjusted = _active_config_summary(store)
        if temporary_changed:
            # The HTTP activation updates the running app; the local store
            # object is reopened so the recorded version is the one in force.
            store.conn.close()
            store = ConfigStore()
            adjusted = _active_config_summary(store)
        capture_session_id = _ensure_debug_capture(client)
        _require_capture(client)
        plan = client.json("POST", "/v1/conversational-plan", {"request_id": str(uuid.uuid4()), "question": QUESTION})
        analysis_plan_id = plan["analysis_plan_id"]
        _require_capture(client)
        if plan["search_policy"]["mode"] != "semantic_ranges" or plan["embedding"] is None:
            raise ExperimentError("live plan did not return semantic retrieval geometry")
        embedding_payload = {
            "request_id": str(uuid.uuid4()),
            "items": [{"message_id": query["query_id"], "text": query["text"]} for query in plan["retrieval_queries"]],
        }
        embedding_status, embedding_events = client.ndjson("/v1/embeddings", embedding_payload)
        if embedding_status != 200:
            raise ExperimentError(f"embedding workload returned HTTP {embedding_status}")
        for event in embedding_events:
            parse_ndjson_event(event, endpoint="/v1/embeddings")
        if embedding_events[-1].get("event") != "completed":
            raise ExperimentError("embedding workload did not complete")
        _require_capture(client)
        candidates = _local_candidates(corpus, plan, embedding_events)
        hits = [hit for values in candidates.values() for hit in values]
        context = _analysis_context(plan, hits)
        request_metadata = {
            "request_id": str(uuid.uuid4()),
            "question": QUESTION,
            "scope_id": f"question-planned-analysis-revision-{corpus.revision_id}",
            "working_corpus_revision_id": corpus.revision_id,
            "working_corpus_message_count": len(corpus.messages),
            "analysis_plan_id": plan["analysis_plan_id"],
            "analysis_context": context,
            "working_corpus_messages_omitted_from_artifact": True,
        }
        _atomic_json(output_dir / "analysis-plan.json", plan)
        _atomic_json(output_dir / "retrieval-metadata.json", {
            "retrieval_queries": plan["retrieval_queries"],
            "embedding": plan["embedding"],
            "search_policy": plan["search_policy"],
            "accepted": next(event["data"] for event in embedding_events if event.get("event") == "accepted"),
            "completed": embedding_events[-1].get("result"),
            "query_vector_sha256": {
                item["message_id"]: __import__("hashlib").sha256(json.dumps(item["vector"], separators=(",", ":")).encode("utf-8")).hexdigest()
                for event in embedding_events if event.get("event") == "vector_batch"
                for item in event["data"]["items"]
            },
            "ranked_hits": candidates,
        })
        _atomic_json(output_dir / "request-metadata.json", request_metadata)
        analysis_request_id = request_metadata["request_id"]
        analysis_request = {
            "request_id": analysis_request_id,
            "question": QUESTION,
            "working_corpus": {"scope_id": request_metadata["scope_id"], "messages": [{
                "message_id": row["message_id"], "thread_id": row["thread_id"], "timestamp": row["timestamp"], "sender": row["sender"], "text": row["text"]
            } for row in corpus.messages]},
            "analysis_context": context,
        }
        started = __import__("time").perf_counter()
        analysis_status, analysis_events = client.ndjson("/v1/conversational-analysis", analysis_request)
        elapsed_ms = (__import__("time").perf_counter() - started) * 1000
        if analysis_status != 200:
            raise ExperimentError(f"analysis returned HTTP {analysis_status}")
        summary = _event_summary(analysis_events)
        _atomic_json(output_dir / "window-and-synthesis-events.json", summary)
        if summary["window_count"] is None or int(summary["window_count"]) < 6:
            raise ExperimentError(f"live run produced {summary['window_count']} windows; packet requires at least six")
        if analysis_events[-1].get("event") != "completed":
            error = analysis_events[-1].get("error", {})
            raise ExperimentError(
                f"live analysis did not complete: {error.get('code', 'UNKNOWN_ERROR')}: "
                f"{error.get('message', 'terminal event was not completed')} "
                f"(request_id={analysis_events[-1].get('request_id')})"
            )
        terminal_result = analysis_events[-1]["result"]
        _atomic_json(output_dir / "final-result.json", terminal_result)
        _atomic_text(output_dir / "result.md", _markdown(terminal_result, {
            "question": QUESTION,
            "analysis_plan_id": plan["analysis_plan_id"],
            "timing": {"analysis_elapsed_ms": elapsed_ms},
        }))
        return output_dir
    except Exception as exc:
        _atomic_json(output_dir / "live-blocker.json", {
            "error_type": exc.__class__.__name__,
            "message": str(exc),
            "request_id": analysis_events[-1].get("request_id") if analysis_events else None,
        })
        raise
    finally:
        stopped_status: dict[str, Any] | None = None
        try:
            if capture_session_id is not None:
                status = client.json("GET", "/admin/events")
                if (status.get("debug_status") or {}).get("active"):
                    page_status, _, page_body = client.request("GET", "/admin/debug")
                    if page_status == 200:
                        _admin_post(client, page_body.decode("utf-8"), "stop_debug_capture", "debug")
                stopped_status = client.json("GET", "/admin/events").get("debug_status")
        finally:
            if temporary_changed:
                _set_window_utilization(client, float(before["window_input_utilization_percent"]))
            after = _active_config_summary(store)
            manifest = {
                "runner": "RPV1-900",
                "started_at": started_at,
                "finished_at": _utc_now(),
                "question": QUESTION,
                "analysis_plan_id": analysis_plan_id,
                "evw_path": str(evw_path.resolve()),
                "working_corpus_revision_id": REVISION_ID,
                "working_corpus_message_count": len(corpus.messages),
                "corpus_tokens_preflight": corpus_tokens,
                "active_window_lower_bound_before_temporary_setting": lower_bound,
                "temporary_window_setting_applied": temporary_changed,
                "temporary_utilization_percent": TEMPORARY_UTILIZATION if temporary_changed else None,
                "configuration_before": before,
                "configuration_used": adjusted,
                "configuration_after_restore": after,
                "capture": {"session_id": capture_session_id, "stopped_and_flushed": bool(stopped_status and not stopped_status.get("active")), "status": stopped_status},
                "server_stdout": str((output_root / "server-stdout.log").resolve()),
                "server_stderr": str((output_root / "server-stderr.log").resolve()),
                "client_stdout": str((output_root / "client-stdout.log").resolve()),
                "client_stderr": str((output_root / "client-stderr.log").resolve()),
                "exact_result_written": terminal_result is not None,
                "no_provider_fallback_or_automatic_rerun": True,
            }
            _atomic_json(output_dir / "run-manifest.json", manifest)
            _atomic_text(output_dir / "debug-capture-path.txt", json.dumps({"session_id": capture_session_id, "path": (stopped_status or {}).get("sessions", [{}])[0].get("path") if stopped_status else None, "stopped_and_flushed": bool(stopped_status and not stopped_status.get("active"))}, indent=2))
            corpus.close()
            if store.conn is not None:
                store.conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server-url", default="http://127.0.0.1:8710")
    parser.add_argument("--evw", type=Path, default=EVW)
    parser.add_argument("--output-root", type=Path, default=Path(".tmp/question-planned-analysis-live"))
    args = parser.parse_args(argv)
    try:
        path = run(args.server_url, args.evw, args.output_root)
    except Exception as exc:
        print(f"RPV1-900 failed: {exc}", file=sys.stderr)
        return 1
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
