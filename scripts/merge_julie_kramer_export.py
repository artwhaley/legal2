from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from message_evidence_workstation.importers.merged_json_converter import (
    convert_merged_json_to_normalized_dir,
)

LOCAL_TIMEZONE = ZoneInfo("America/Chicago")
MERGED_SCHEMA_VERSION = "1.0"
SOURCE_FORMAT = "decipher_thread_export"


@dataclass(slots=True)
class MergeReport:
    merged_path: Path
    export_path: Path
    normalized_output_dir: Path
    report_path: Path
    source_id: str
    source_sha256: str
    existing_message_count: int
    incoming_message_count: int
    incoming_exact_duplicates_existing: int
    incoming_exact_duplicates_within_file: int
    added_message_count: int
    final_message_count: int
    existing_end_utc: str
    incoming_start_utc: str
    incoming_end_utc: str
    final_end_utc: str


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _timestamp_fields(timestamp_ms: int) -> tuple[str, str, str, str]:
    utc_dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
    local_dt = utc_dt.astimezone(LOCAL_TIMEZONE)
    return (
        utc_dt.isoformat(timespec="microseconds"),
        local_dt.isoformat(timespec="microseconds"),
        utc_dt.date().isoformat(),
        local_dt.date().isoformat(),
    )


def _canonical_message_key(message: dict[str, Any]) -> tuple[Any, ...]:
    share = message.get("share")
    media = message.get("media") or []
    reactions = message.get("reactions") or []
    return (
        str(message.get("sender") or ""),
        str(message.get("message_type") or ""),
        int(message.get("timestamp_ms") or 0),
        bool(message.get("is_unsent")),
        str(message.get("text") or ""),
        json.dumps(share, sort_keys=True, ensure_ascii=False),
        json.dumps(media, sort_keys=True, ensure_ascii=False),
        json.dumps(reactions, sort_keys=True, ensure_ascii=False),
    )


def _source_id_from_export_name(export_name: str) -> str:
    stem = Path(export_name).stem
    suffix = stem.rsplit("_", 1)[-1]
    if suffix.isdigit():
        return f"decipher_export_{suffix}"
    safe = "".join(char.lower() if char.isalnum() else "_" for char in stem).strip("_")
    return f"decipher_export_{safe or 'new'}"


def _normalize_export_message(
    raw: dict[str, Any],
    *,
    source_id: str,
    export_file_name: str,
    export_path_label: str,
    export_sha256: str,
    source_index: int,
    thread_name: str,
) -> dict[str, Any]:
    timestamp_ms = int(raw.get("timestamp") or 0)
    timestamp_utc, timestamp_local, date_utc, date_local = _timestamp_fields(timestamp_ms)
    text = str(raw.get("text") or "")
    media = raw.get("media") or []
    reactions = raw.get("reactions") or []
    message_type = str(raw.get("type") or "text")
    return {
        "id": f"{source_id}:{source_index}",
        "sender": str(raw.get("senderName") or "Unknown"),
        "message_type": message_type,
        "text": text,
        "share": raw.get("share"),
        "media": media if isinstance(media, list) else [],
        "reactions": reactions if isinstance(reactions, list) else [],
        "call_duration_seconds": raw.get("call_duration_seconds"),
        "is_unsent": bool(raw.get("isUnsent")),
        "timestamp_ms": timestamp_ms,
        "timestamp_utc": timestamp_utc,
        "timestamp_local": timestamp_local,
        "date_utc": date_utc,
        "date_local": date_local,
        "provenance": {
            "source_id": source_id,
            "source_format": SOURCE_FORMAT,
            "source_file": export_file_name,
            "source_path": export_path_label,
            "source_file_sha256": export_sha256,
            "source_message_index": source_index,
            "source_message_index_1based": source_index + 1,
            "thread_name": thread_name,
            "raw": raw,
        },
        "duplicate_flags": {
            "exact_cross_source_match_ids": [],
            "near_match_ids": [],
            "review_status": "unreviewed",
        },
    }


def _date_range_utc(messages: list[dict[str, Any]]) -> dict[str, str]:
    if not messages:
        return {"start": "", "end": ""}
    ordered = sorted(messages, key=lambda row: int(row.get("timestamp_ms") or 0))
    return {
        "start": str(ordered[0].get("timestamp_utc") or ""),
        "end": str(ordered[-1].get("timestamp_utc") or ""),
    }


def merge_export_into_julie_dataset(
    *,
    merged_json_path: Path,
    new_export_path: Path,
    normalized_output_dir: Path,
    report_path: Path,
) -> MergeReport:
    merged_payload = _read_json(merged_json_path)
    new_export = _read_json(new_export_path)
    if not isinstance(merged_payload, dict) or str(merged_payload.get("schema_version")) != MERGED_SCHEMA_VERSION:
        raise ValueError("Existing merged Julie dataset has an unexpected schema")
    if not isinstance(new_export, dict) or not isinstance(new_export.get("messages"), list):
        raise ValueError("New export must be a JSON object with a messages array")

    export_file_name = new_export_path.name
    export_path_label = str(new_export_path)
    export_sha256 = _sha256_file(new_export_path)
    source_id = _source_id_from_export_name(export_file_name)
    if any(str(source.get("sha256") or "") == export_sha256 for source in merged_payload.get("sources", [])):
        raise ValueError(f"Source file already present in merged dataset by sha256: {export_file_name}")

    existing_messages = list(merged_payload.get("messages") or [])
    existing_count = len(existing_messages)
    existing_keys = {_canonical_message_key(message) for message in existing_messages if isinstance(message, dict)}
    existing_end_utc = ""
    if existing_messages:
        existing_end_utc = max(
            str(message.get("timestamp_utc") or "")
            for message in existing_messages
            if isinstance(message, dict)
        )

    incoming_raw_messages = [message for message in new_export["messages"] if isinstance(message, dict)]
    incoming_count = len(incoming_raw_messages)
    thread_name = str(new_export.get("threadName") or export_file_name)

    added_messages: list[dict[str, Any]] = []
    incoming_keys_seen: set[tuple[Any, ...]] = set()
    duplicates_existing = 0
    duplicates_within_file = 0
    for index, raw_message in enumerate(incoming_raw_messages):
        normalized = _normalize_export_message(
            raw_message,
            source_id=source_id,
            export_file_name=export_file_name,
            export_path_label=export_path_label,
            export_sha256=export_sha256,
            source_index=index,
            thread_name=thread_name,
        )
        key = _canonical_message_key(normalized)
        if key in existing_keys:
            duplicates_existing += 1
            continue
        if key in incoming_keys_seen:
            duplicates_within_file += 1
            continue
        incoming_keys_seen.add(key)
        added_messages.append(normalized)

    merged_messages = existing_messages + added_messages
    merged_messages.sort(key=lambda row: (int(row.get("timestamp_ms") or 0), str(row.get("id") or "")))
    merged_payload["messages"] = merged_messages

    sources = list(merged_payload.get("sources") or [])
    new_range = _date_range_utc(added_messages or [
        _normalize_export_message(
            raw_message,
            source_id=source_id,
            export_file_name=export_file_name,
            export_path_label=export_path_label,
            export_sha256=export_sha256,
            source_index=index,
            thread_name=thread_name,
        )
        for index, raw_message in enumerate(incoming_raw_messages)
    ])
    sources.append(
        {
            "source_id": source_id,
            "format": SOURCE_FORMAT,
            "description": "Decipher thread export merged after initial dataset build",
            "path": export_path_label,
            "file_name": export_file_name,
            "sha256": export_sha256,
            "message_count": incoming_count,
            "date_range_utc": new_range,
        }
    )
    merged_payload["sources"] = sources

    thread = dict(merged_payload.get("thread") or {})
    thread["merged_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    thread["message_count"] = len(merged_messages)
    thread["date_range_utc"] = _date_range_utc(merged_messages)
    merged_payload["thread"] = thread
    merged_payload["overlap_summary"] = {
        "exact_cross_source_group_count": 0,
        "near_cross_source_group_count": 0,
        "messages_flagged_exact": duplicates_existing,
        "messages_flagged_near": 0,
    }

    merged_json_path.write_text(json.dumps(merged_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    convert_merged_json_to_normalized_dir(merged_json_path, normalized_output_dir, overwrite=True)

    final_range = thread["date_range_utc"]
    report = MergeReport(
        merged_path=merged_json_path,
        export_path=new_export_path,
        normalized_output_dir=normalized_output_dir,
        report_path=report_path,
        source_id=source_id,
        source_sha256=export_sha256,
        existing_message_count=existing_count,
        incoming_message_count=incoming_count,
        incoming_exact_duplicates_existing=duplicates_existing,
        incoming_exact_duplicates_within_file=duplicates_within_file,
        added_message_count=len(added_messages),
        final_message_count=len(merged_messages),
        existing_end_utc=existing_end_utc,
        incoming_start_utc=new_range["start"],
        incoming_end_utc=new_range["end"],
        final_end_utc=final_range["end"],
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(_render_report(report), encoding="utf-8")
    return report


def _render_report(report: MergeReport) -> str:
    return "\n".join(
        [
            "# Julie Kramer Merge Report",
            "",
            f"- Merged source JSON: `{report.merged_path}`",
            f"- New export JSON: `{report.export_path}`",
            f"- Normalized output dir: `{report.normalized_output_dir}`",
            f"- Source ID added: `{report.source_id}`",
            f"- Source sha256: `{report.source_sha256}`",
            "",
            "## Counts",
            "",
            f"- Existing merged messages before run: {report.existing_message_count}",
            f"- Incoming export messages: {report.incoming_message_count}",
            f"- Exact duplicates vs existing merged messages skipped: {report.incoming_exact_duplicates_existing}",
            f"- Exact duplicates within incoming file skipped: {report.incoming_exact_duplicates_within_file}",
            f"- Messages added: {report.added_message_count}",
            f"- Final merged message count: {report.final_message_count}",
            "",
            "## Date Range",
            "",
            f"- Existing merged end UTC before run: {report.existing_end_utc}",
            f"- Incoming export start UTC: {report.incoming_start_utc}",
            f"- Incoming export end UTC: {report.incoming_end_utc}",
            f"- Final merged end UTC: {report.final_end_utc}",
            "",
            "## Outputs",
            "",
            "- Updated merged JSON in place.",
            "- Regenerated `dataset.json`, `source_threads.jsonl`, and `messages.jsonl` from the updated merged JSON.",
        ]
    ) + "\n"


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="One-time Julie Kramer export merge tool")
    parser.add_argument(
        "--merged-json",
        type=Path,
        default=project_root / "julie_kramer_merged_normalized.json",
        help="Existing merged Julie JSON source of truth",
    )
    parser.add_argument(
        "--new-export",
        type=Path,
        default=Path(r"C:\Users\artwh\Downloads\messages (1)\Julie Kramer_5.json"),
        help="New Decipher export to merge",
    )
    parser.add_argument(
        "--normalized-output",
        type=Path,
        default=project_root / "donor_datasets" / "julie_kramer",
        help="Normalized donor dataset output directory",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=project_root / "recovered_outputs" / "2026-07-03_julie_kramer_merge_report.md",
        help="Markdown report output path",
    )
    args = parser.parse_args()

    report = merge_export_into_julie_dataset(
        merged_json_path=args.merged_json,
        new_export_path=args.new_export,
        normalized_output_dir=args.normalized_output,
        report_path=args.report,
    )
    print(
        f"Merged {report.added_message_count} new messages "
        f"({report.incoming_exact_duplicates_existing} exact duplicates skipped) "
        f"-> {report.final_message_count} total. Report: {report.report_path}"
    )


if __name__ == "__main__":
    main()
