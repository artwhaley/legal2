"""Read-only exporter of model run scan windows from the .evw workspace."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from message_evidence_workstation.config.paths import default_workspace_path
from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.export.audit_export import get_model_run_detail


EXPORT_RUN_IDS = [165, 166, 167, 168, 169, 170]
RUN_TYPE = "exhaustive_window_scan"
INPUTS_DIR = Path(__file__).resolve().parent / "inputs"
RICH_OUTPUT = INPUTS_DIR / "school_scan_windows.json"
COMPACT_OUTPUT = INPUTS_DIR / "school_scan_windows_compact.json"


def _extract_user_content(req: dict) -> str:
    try:
        for msg in req.get("messages", []):
            if msg.get("role") == "user":
                return msg.get("content", "")
    except Exception:
        return ""
    return ""


def _parse_user_content_json(content_str: str) -> dict:
    try:
        return json.loads(content_str)
    except (json.JSONDecodeError, ValueError, TypeError):
        return {}


def _extract_scan_text(resp: dict) -> str:
    try:
        return resp["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return json.dumps(resp)


def export_scan_windows(
    conn: sqlite3.Connection,
    *,
    run_ids: list[int],
) -> list[dict]:
    windows: list[dict] = []
    for run_id in run_ids:
        detail = get_model_run_detail(conn, run_id)
        if detail is None:
            print(f"WARNING: model_run_id={run_id} not found, skipping")
            continue
        if detail.get("run_type") != RUN_TYPE:
            print(f"WARNING: model_run_id={run_id} has run_type={detail.get('run_type')}, skipping")
            continue
        raw_request = detail.get("raw_request_json") or {}
        raw_response = detail.get("raw_response_json") or {}
        user_content_str = _extract_user_content(raw_request)
        user_content = _parse_user_content_json(user_content_str)
        scan_text = _extract_scan_text(raw_response)
        windows.append(
            {
                "model_run_id": detail["model_run_id"],
                "run_type": detail["run_type"],
                "provider": raw_request.get("provider", detail.get("model", "")),
                "model": detail["model"],
                "created_at": detail["created_at"],
                "latency_ms": detail["latency_ms"],
                "error_type": detail["error_type"],
                "error_message": detail["error_message"],
                "user_query": user_content.get("user_query", user_content_str),
                "window_id": user_content.get("window_id", ""),
                "session_id": user_content.get("session_id", ""),
                "source_thread_id": user_content.get("source_thread_id", ""),
                "input_estimated_tokens": user_content.get("estimated_tokens", 0),
                "output_response_chars": len(scan_text),
                "message_ids": user_content.get("message_ids", []),
                "messages_considered": user_content.get("messages_considered", 0),
                "raw_response_text": scan_text,
                "raw_request_payload": raw_request,
            }
        )
    return windows


def _try_parse_response(text: str) -> dict:
    if not text:
        return {}
    cleaned = text.strip()
    for prefix in ("```json\n", "```json\r\n", "```\n", "```"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :]
    for suffix in ("\n```", "\r\n```"):
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)]
    cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        return {}


def _estimate_output_chars(parsed: dict) -> int:
    total = 0
    total += len(parsed.get("answer_summary", "") or "")
    total += len(parsed.get("answer", "") or "")
    for r in parsed.get("answer_ranges", []):
        if isinstance(r, dict):
            for k in ("title", "summary", "date_description", "display_text",
                       "hit_message_id", "start_message_id", "end_message_id"):
                total += len(r.get(k, "") or "")
    for mid in parsed.get("cited_message_ids", []):
        total += len(str(mid))
    for u in parsed.get("uncertainties", []):
        total += len(str(u))
    return total


def _compact_window(window: dict) -> dict:
    parsed = _try_parse_response(window.get("raw_response_text", ""))
    return {
        "model_run_id": window["model_run_id"],
        "window_id": window.get("window_id", ""),
        "session_id": window.get("session_id", ""),
        "source_thread_id": window.get("source_thread_id", ""),
        "input_estimated_tokens": window.get("input_estimated_tokens", 0),
        "output_estimated_chars": _estimate_output_chars(parsed),
        "messages_considered": window.get("messages_considered", 0),
        "message_ids": list(window.get("message_ids", [])),
        "answer_summary": parsed.get("answer_summary", ""),
        "answer": parsed.get("answer", ""),
        "answer_format": parsed.get("answer_format", "detailed"),
        "cited_message_ids": list(parsed.get("cited_message_ids", [])),
        "answer_ranges": list(parsed.get("answer_ranges", [])),
        "uncertainties": list(parsed.get("uncertainties", [])),
        "parse_status": "ok" if parsed else "failed",
    }


def main() -> None:
    INPUTS_DIR.mkdir(parents=True, exist_ok=True)
    conn = connect(default_workspace_path())
    try:
        windows = export_scan_windows(conn, run_ids=EXPORT_RUN_IDS)
        if not windows:
            print("ERROR: No scan windows exported.")
            return
        RICH_OUTPUT.write_text(
            json.dumps(windows, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        print(f"Exported {len(windows)} windows to {RICH_OUTPUT}")
        compact = [_compact_window(w) for w in windows]
        COMPACT_OUTPUT.write_text(
            json.dumps(compact, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        print(f"Exported {len(compact)} compact windows to {COMPACT_OUTPUT}")
        for w in windows:
            run_id = w["model_run_id"]
            wid = w.get("window_id", "")
            err = w.get("error_type")
            status = "OK" if not err else f"ERROR({err})"
            print(f"  run={run_id} window={wid} latency={w.get('latency_ms')}ms {status}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
