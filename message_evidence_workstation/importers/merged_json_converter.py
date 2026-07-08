"""Convert merged donor JSON (schema 1.0) to EVW normalized import directory."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from message_evidence_workstation.domain.constants import NORMALIZED_FORMAT_VERSION

MERGED_SCHEMA_VERSION = "1.0"
SOURCE_THREAD_ID = "julie_kramer"
SOURCE_PLATFORM = "facebook_messenger"


@dataclass(slots=True)
class MergedConversionStats:
    message_count: int
    thread_count: int
    source_file_count: int
    output_dir: Path


def _slug_sender(sender: str) -> str:
    collapsed = re.sub(r"\s+", "_", sender.strip().casefold())
    cleaned = re.sub(r"[^a-z0-9_]+", "", collapsed)
    return cleaned or "unknown"


def _attachment_summary(message: dict[str, Any]) -> tuple[bool, str]:
    media = message.get("media") or []
    if not isinstance(media, list) or not media:
        share = message.get("share")
        if isinstance(share, dict) and share.get("link"):
            return False, str(share.get("link", ""))[:500]
        return False, ""
    parts: list[str] = []
    for item in media[:3]:
        if not isinstance(item, dict):
            continue
        uri = item.get("uri") or item.get("path") or ""
        if uri:
            parts.append(str(uri).split("/")[-1])
    summary = ", ".join(parts)
    if len(media) > 3:
        summary = f"{summary}, +{len(media) - 3} more"
    return True, summary[:500]


def _message_body(message: dict[str, Any]) -> str:
    if message.get("is_unsent") or message.get("message_type") == "unsent_placeholder":
        placeholder = (message.get("text") or "").strip()
        return placeholder or "[Message unsent]"
    text = (message.get("text") or "").strip()
    message_type = str(message.get("message_type") or "text")
    if text:
        return text
    if message_type == "call":
        seconds = message.get("call_duration_seconds")
        if seconds:
            return f"[Call, {seconds}s]"
        return "[Call]"
    if message_type in {"photo", "video", "audio", "gif", "media"}:
        return f"[{message_type.title()}]"
    if message_type == "share":
        share = message.get("share")
        if isinstance(share, dict) and share.get("link"):
            return str(share["link"])
    if message_type == "link":
        return text or "[Link]"
    if message_type == "call_event":
        return "[Call event]"
    return f"[{message_type}]"


def _platform_thread_id(sources: list[dict[str, Any]]) -> str:
    for source in sources:
        path = str(source.get("path") or "")
        match = re.search(r"juliekramer_(\d+)", path)
        if match:
            return f"juliekramer_{match.group(1)}"
    if sources:
        return str(sources[0].get("source_id") or SOURCE_THREAD_ID)
    return SOURCE_THREAD_ID


def convert_merged_json_to_normalized_dir(
    merged_json_path: Path,
    output_dir: Path,
    *,
    overwrite: bool = False,
) -> MergedConversionStats:
    """Write dataset.json, source_threads.jsonl, messages.jsonl under output_dir."""
    merged_json_path = merged_json_path.resolve()
    output_dir = output_dir.resolve()

    if not merged_json_path.is_file():
        raise FileNotFoundError(f"Merged JSON not found: {merged_json_path}")

    if output_dir.exists():
        if not overwrite and any(output_dir.iterdir()):
            raise FileExistsError(
                f"Output directory already exists and is not empty: {output_dir}. "
                "Pass overwrite=True to replace."
            )
    else:
        output_dir.mkdir(parents=True)

    with merged_json_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    if not isinstance(payload, dict):
        raise ValueError("Merged JSON root must be an object")
    if str(payload.get("schema_version")) != MERGED_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported merged schema_version {payload.get('schema_version')!r} "
            f"(expected {MERGED_SCHEMA_VERSION})"
        )

    thread_meta = payload.get("thread") or {}
    sources = [item for item in (payload.get("sources") or []) if isinstance(item, dict)]
    messages = payload.get("messages")
    if not isinstance(messages, list):
        raise ValueError("Merged JSON must contain a messages array")

    participants = thread_meta.get("participants") or []
    participant_summary = ", ".join(str(name) for name in participants)

    thread_record = {
        "source_thread_id": SOURCE_THREAD_ID,
        "source_platform": SOURCE_PLATFORM,
        "platform_thread_id": _platform_thread_id(sources),
        "display_title": str(thread_meta.get("title") or "Julie Kramer"),
        "participant_summary": participant_summary,
        "start_ts": str((thread_meta.get("date_range_utc") or {}).get("start") or ""),
        "end_ts": str((thread_meta.get("date_range_utc") or {}).get("end") or ""),
        "metadata_json": {
            "merged_schema_version": payload.get("schema_version"),
            "merge_policy": thread_meta.get("merge_policy"),
            "merged_at_utc": thread_meta.get("merged_at_utc"),
            "local_timezone": thread_meta.get("local_timezone"),
            "sources": sources,
            "overlap_summary": payload.get("overlap_summary") or {},
            "source_merged_json": merged_json_path.name,
        },
    }

    source_formats = sorted({str(source.get("format") or "unknown") for source in sources})
    dataset_record = {
        "name": "Julie Kramer (merged)",
        "notes": (
            f"Normalized from merged donor JSON with {len(sources)} source file(s) "
            f"({', '.join(source_formats)}). Original: {merged_json_path.name}"
        ),
        "normalized_format_version": NORMALIZED_FORMAT_VERSION,
    }

    dataset_path = output_dir / "dataset.json"
    threads_path = output_dir / "source_threads.jsonl"
    messages_path = output_dir / "messages.jsonl"

    dataset_path.write_text(json.dumps(dataset_record, indent=2) + "\n", encoding="utf-8")
    threads_path.write_text(json.dumps(thread_record) + "\n", encoding="utf-8")

    message_count = 0
    with messages_path.open("w", encoding="utf-8") as out:
        for sort_index, message in enumerate(messages):
            if not isinstance(message, dict):
                continue
            provenance = message.get("provenance") or {}
            if not isinstance(provenance, dict):
                provenance = {}
            merged_id = str(message.get("id") or f"{SOURCE_THREAD_ID}:{sort_index}")
            sender_display = str(message.get("sender") or "Unknown")
            has_attachment, attachment_summary = _attachment_summary(message)
            body = _message_body(message)
            source_metadata = {
                "merged_message_id": merged_id,
                "message_type": message.get("message_type"),
                "timestamp_local": message.get("timestamp_local"),
                "date_utc": message.get("date_utc"),
                "date_local": message.get("date_local"),
                "is_unsent": bool(message.get("is_unsent")),
                "provenance": provenance,
                "duplicate_flags": message.get("duplicate_flags") or {},
            }
            if message.get("share"):
                source_metadata["share"] = message.get("share")
            if message.get("media"):
                source_metadata["media"] = message.get("media")
            if message.get("reactions"):
                source_metadata["reactions"] = message.get("reactions")
            record = {
                "message_id": merged_id,
                "source_thread_id": SOURCE_THREAD_ID,
                "source_platform": SOURCE_PLATFORM,
                "source_message_id": merged_id,
                "timestamp": str(message.get("timestamp_utc") or ""),
                "sender_id": _slug_sender(sender_display),
                "sender_display": sender_display,
                "body": body,
                "has_attachment": has_attachment,
                "attachment_summary": attachment_summary,
                "sort_index": sort_index,
                "source_metadata_json": source_metadata,
            }
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            message_count += 1

    return MergedConversionStats(
        message_count=message_count,
        thread_count=1,
        source_file_count=len(sources),
        output_dir=output_dir,
    )


def main() -> None:
    import argparse

    project_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Convert merged donor JSON to EVW normalized directory")
    parser.add_argument(
        "--input",
        type=Path,
        default=project_root / "julie_kramer_merged_normalized.json",
        help="Path to merged JSON file",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=project_root / "donor_datasets" / "julie_kramer",
        help="Output directory for normalized import files",
    )
    parser.add_argument("--overwrite", action="store_true", help="Replace existing output files")
    args = parser.parse_args()

    stats = convert_merged_json_to_normalized_dir(
        args.input,
        args.output,
        overwrite=args.overwrite,
    )
    print(
        f"Wrote {stats.message_count} messages, {stats.thread_count} thread(s), "
        f"{stats.source_file_count} source file(s) -> {stats.output_dir}"
    )


if __name__ == "__main__":
    main()
