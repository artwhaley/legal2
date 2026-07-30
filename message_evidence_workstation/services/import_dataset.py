"""Deterministic normalized-dataset importer for EVW v14."""

from __future__ import annotations

import json
import hashlib
import re
import sqlite3
from pathlib import Path
from typing import Any

from message_evidence_workstation.domain.constants import SCHEMA_VERSION
from message_evidence_workstation.domain.search_scope import count_tokens
from message_evidence_workstation.logging_ui.diagnostic_logger import DiagnosticLogger, utc_now_iso


class DatasetLoadError(RuntimeError):
    pass


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise DatasetLoadError(f"Required normalized dataset file is missing: {path.name}")
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DatasetLoadError(f"Malformed {path.name} line {line_number}: {exc}") from exc
        if not isinstance(value, dict):
            raise DatasetLoadError(f"Expected object in {path.name} line {line_number}")
        rows.append(value)
    return rows


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip()).casefold()


def import_normalized_dataset(conn: sqlite3.Connection, logger: DiagnosticLogger, dataset_dir: Path, *, reload: bool = False) -> int:
    if reload:
        raise DatasetLoadError("CANONICAL_REIMPORT_NOT_SUPPORTED: an existing EVW cannot be destructively reloaded")
    dataset_dir = dataset_dir.resolve()
    metadata = json.loads((dataset_dir / "dataset.json").read_text(encoding="utf-8"))
    if not isinstance(metadata, dict) or not str(metadata.get("name", "")).strip():
        raise DatasetLoadError("dataset.json must contain a non-empty name")
    threads = _jsonl(dataset_dir / "source_threads.jsonl")
    messages = sorted(_jsonl(dataset_dir / "messages.jsonl"), key=lambda value: (str(value.get("source_thread_id", "")), str(value.get("timestamp", "")), int(value.get("sort_index", 0)), str(value.get("message_id", ""))))
    existing = conn.execute("SELECT dataset_id FROM dataset LIMIT 1").fetchone()
    if existing:
        raise DatasetLoadError("CANONICAL_REIMPORT_NOT_SUPPORTED: this EVW already contains a canonical dataset")
    content_revision = 1
    now = utc_now_iso()
    cursor = conn.execute("INSERT INTO dataset(name,created_at,schema_version,notes,content_revision,import_validity,normalized_format_version) VALUES (?,?,?,?,?,?,?)", (str(metadata["name"]), now, SCHEMA_VERSION, str(metadata.get("notes", "")), content_revision, "loading", 1))
    dataset_id = int(cursor.lastrowid)
    seen_threads: set[str] = set()
    for thread in threads:
        required = ("source_thread_id", "source_platform", "platform_thread_id", "display_title", "start_ts", "end_ts")
        if any(not str(thread.get(key, "")).strip() for key in required):
            raise DatasetLoadError("source thread is missing a required field")
        thread_id = str(thread["source_thread_id"])
        if thread_id in seen_threads:
            raise DatasetLoadError(f"Duplicate source_thread_id: {thread_id}")
        seen_threads.add(thread_id)
        conn.execute("INSERT INTO source_thread(source_thread_id,dataset_id,source_platform,platform_thread_id,display_title,participant_summary,start_ts,end_ts,metadata_json) VALUES (?,?,?,?,?,?,?,?,?)", (thread_id, dataset_id, str(thread["source_platform"]), str(thread["platform_thread_id"]), str(thread["display_title"]), str(thread.get("participant_summary", "")), str(thread["start_ts"]), str(thread["end_ts"]), json.dumps(thread.get("metadata_json", {}), ensure_ascii=False)))
    per_thread: dict[str, int] = {}
    seen_messages: set[str] = set()
    for message in messages:
        required = ("message_id", "source_thread_id", "source_platform", "source_message_id", "timestamp", "sender_id", "sender_display", "body", "sort_index")
        if any(key not in message for key in required):
            raise DatasetLoadError("message is missing a required field")
        message_id = str(message["message_id"])
        thread_id = str(message["source_thread_id"])
        if message_id in seen_messages:
            raise DatasetLoadError(f"Duplicate message_id: {message_id}")
        if thread_id not in seen_threads:
            raise DatasetLoadError(f"Message references unknown thread: {thread_id}")
        seen_messages.add(message_id)
        ordinal = per_thread.get(thread_id, 0)
        per_thread[thread_id] = ordinal + 1
        body = str(message["body"])
        body_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
        serialized = f"[{message_id}] {message['timestamp']} | {message['sender_display']}: {body.strip() or '(empty message)'}"
        conn.execute("INSERT INTO message(message_id,dataset_id,source_thread_id,source_platform,source_message_id,timestamp,sender_id,sender_display,body,body_normalized,embedding_input_hash,has_attachment,attachment_summary,sort_index,source_metadata_json,thread_ordinal,token_count) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (message_id, dataset_id, thread_id, str(message["source_platform"]), str(message["source_message_id"]), str(message["timestamp"]), str(message["sender_id"]), str(message["sender_display"]), body, _normalize(body), body_hash, int(bool(message.get("has_attachment", False))), str(message.get("attachment_summary", "")), int(message["sort_index"]), json.dumps(message.get("source_metadata_json", {}), ensure_ascii=False), ordinal, count_tokens(serialized)))
    conn.execute("UPDATE source_thread SET message_count=(SELECT COUNT(*) FROM message WHERE message.source_thread_id=source_thread.source_thread_id) WHERE dataset_id=?", (dataset_id,))
    conn.execute("INSERT INTO category(dataset_id,name,created_at,updated_at) VALUES (?,?,?,?)", (dataset_id, "Uncategorized", now, now))
    conn.execute("UPDATE dataset SET import_validity='ready' WHERE dataset_id=?", (dataset_id,))
    conn.execute("INSERT INTO workspace_state(key,value) VALUES ('dataset_import_validity','ready') ON CONFLICT(key) DO UPDATE SET value='ready'")
    conn.execute("UPDATE workspace_state SET value=? WHERE key='updated_at'", (now,))
    conn.commit()
    logger.info(component="services.import_dataset", operation="import_complete", message="Normalized dataset imported into EVW v15", details={"dataset_id": dataset_id, "threads": len(threads), "messages": len(messages)}, dataset_id=dataset_id)
    return dataset_id
