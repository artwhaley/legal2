"""Input loading, parsing, compaction, and validation helpers."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

SPIKE_DIR = Path(__file__).resolve().parent
INPUTS_DIR = SPIKE_DIR / "inputs"
RICH_PATH = INPUTS_DIR / "school_scan_windows.json"
COMPACT_PATH = INPUTS_DIR / "school_scan_windows_compact.json"


ScanWindow = dict[str, Any]


def load_scan_windows(path: Path | None = None) -> list[ScanWindow]:
    path = path or RICH_PATH
    return json.loads(path.read_text(encoding="utf-8"))


def load_compact_windows(path: Path | None = None) -> list[ScanWindow]:
    path = path or COMPACT_PATH
    return json.loads(path.read_text(encoding="utf-8"))


def parse_fenced_json(text: str) -> dict | None:
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
        return json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        return None


def extract_scan_result(window: ScanWindow) -> dict | None:
    raw_text = window.get("raw_response_text", "")
    return parse_fenced_json(raw_text)


def _estimate_output_chars(parsed: dict | None) -> int:
    if not parsed:
        return 0
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


def compact_from_rich(window: ScanWindow) -> ScanWindow:
    parsed = extract_scan_result(window)
    return {
        "model_run_id": window["model_run_id"],
        "window_id": window.get("window_id", ""),
        "session_id": window.get("session_id", ""),
        "source_thread_id": window.get("source_thread_id", ""),
        "input_estimated_tokens": window.get("input_estimated_tokens", window.get("estimated_tokens", 0)),
        "output_estimated_chars": _estimate_output_chars(parsed),
        "messages_considered": window.get("messages_considered", 0),
        "message_ids": list(window.get("message_ids", [])),
        "answer_summary": (parsed or {}).get("answer_summary", ""),
        "answer": (parsed or {}).get("answer", ""),
        "answer_format": (parsed or {}).get("answer_format", "detailed"),
        "cited_message_ids": list((parsed or {}).get("cited_message_ids", [])),
        "answer_ranges": list((parsed or {}).get("answer_ranges", [])),
        "uncertainties": list((parsed or {}).get("uncertainties", [])),
        "parse_status": "ok" if parsed else "failed",
    }


def count_ranges(window: ScanWindow) -> int:
    parsed = extract_scan_result(window)
    if parsed is None:
        return 0
    ranges = parsed.get("answer_ranges", [])
    if isinstance(ranges, list):
        return len(ranges)
    return 0


def validate_message_ids(
    window: ScanWindow,
    valid_ids: set[str] | None = None,
) -> dict[str, list[str]]:
    result = extract_scan_result(window)
    invalid: dict[str, list[str]] = {"cited": [], "ranges": [], "all_invalid": []}
    if result is None:
        return invalid
    if valid_ids is None:
        valid_ids = set(window.get("message_ids", []))
    cited = result.get("cited_message_ids", [])
    if isinstance(cited, list):
        for mid in cited:
            mid = str(mid).strip()
            if mid and mid not in valid_ids:
                invalid["cited"].append(mid)
                invalid["all_invalid"].append(mid)
    ranges = result.get("answer_ranges", [])
    if isinstance(ranges, list):
        for r in ranges:
            if not isinstance(r, dict):
                continue
            for key in ("hit_message_id", "start_message_id", "end_message_id"):
                val = str(r.get(key, "")).strip()
                if val and val not in valid_ids:
                    invalid["ranges"].append(val)
                    invalid["all_invalid"].append(val)
    return invalid


def get_window_summary(window: ScanWindow) -> dict:
    parsed = extract_scan_result(window)
    return {
        "model_run_id": window["model_run_id"],
        "window_id": window.get("window_id", ""),
        "input_estimated_tokens": window.get("input_estimated_tokens", window.get("estimated_tokens", 0)),
        "output_estimated_chars": window.get("output_estimated_chars", len(window.get("raw_response_text", ""))),
        "range_count": count_ranges(window) if parsed else 0,
        "parse_status": "ok" if parsed else (
            "error" if window.get("error_type") else "unparsed"
        ),
        "latency_ms": window.get("latency_ms"),
        "error_type": window.get("error_type"),
        "answer_summary": (parsed or {}).get("answer_summary", "")[:120] if parsed else "",
    }
