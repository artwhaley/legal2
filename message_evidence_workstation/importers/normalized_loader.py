"""Normalized fixture dataset loader."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from message_evidence_workstation.domain.constants import SCHEMA_VERSION
from message_evidence_workstation.logging_ui.process_log import ProcessLogger, utc_now_iso

REQUIRED_DATASET_FIELDS = {"name"}
REQUIRED_THREAD_FIELDS = {
    "source_thread_id",
    "source_platform",
    "platform_thread_id",
    "display_title",
    "start_ts",
    "end_ts",
}
REQUIRED_MESSAGE_FIELDS = {
    "message_id",
    "source_thread_id",
    "source_platform",
    "source_message_id",
    "timestamp",
    "sender_id",
    "sender_display",
    "body",
    "sort_index",
}


class DatasetLoadError(Exception):
    def __init__(self, message: str, *, file: str | None = None, line_number: int | None = None):
        super().__init__(message)
        self.file = file
        self.line_number = line_number


def normalize_body(body: str) -> str:
    collapsed = re.sub(r"\s+", " ", body.strip())
    return collapsed.casefold()


def _read_jsonl(path: Path) -> list[tuple[int, dict[str, Any]]]:
    rows: list[tuple[int, dict[str, Any]]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise DatasetLoadError(
                    f"Malformed JSON on line {line_number}: {exc.msg}",
                    file=path.name,
                    line_number=line_number,
                ) from exc
            if not isinstance(payload, dict):
                raise DatasetLoadError(
                    f"Expected JSON object on line {line_number}",
                    file=path.name,
                    line_number=line_number,
                )
            rows.append((line_number, payload))
    return rows


def _validate_required(
    payload: dict[str, Any],
    required: set[str],
    *,
    file: str,
    line_number: int | None = None,
) -> None:
    missing = sorted(required - payload.keys())
    if missing:
        location = f"{file}"
        if line_number is not None:
            location += f" line {line_number}"
        raise DatasetLoadError(
            f"Missing required field(s): {', '.join(missing)}",
            file=file,
            line_number=line_number,
        )


def clear_dataset(conn: sqlite3.Connection, dataset_id: int) -> None:
    from message_evidence_workstation.embeddings.sqlite_vec_backend import (
        clear_chunk_vectors,
        clear_message_vectors,
        ensure_chunk_metadata_schema,
    )

    conn.execute(
        "DELETE FROM conversation_hit WHERE workstation_conversation_id IN "
        "(SELECT workstation_conversation_id FROM workstation_conversation WHERE dataset_id = ?)",
        (dataset_id,),
    )
    conn.execute(
        "DELETE FROM conversation_range WHERE workstation_conversation_id IN "
        "(SELECT workstation_conversation_id FROM workstation_conversation WHERE dataset_id = ?)",
        (dataset_id,),
    )
    conn.execute(
        "DELETE FROM message_highlight_override WHERE workstation_conversation_id IN "
        "(SELECT workstation_conversation_id FROM workstation_conversation WHERE dataset_id = ?)",
        (dataset_id,),
    )
    conn.execute("DELETE FROM workstation_conversation WHERE dataset_id = ?", (dataset_id,))
    conn.execute("DELETE FROM category WHERE dataset_id = ?", (dataset_id,))
    ensure_chunk_metadata_schema(conn)
    clear_chunk_vectors(conn, dataset_id)
    clear_message_vectors(conn, dataset_id)
    conn.execute("DELETE FROM message WHERE dataset_id = ?", (dataset_id,))
    conn.execute("DELETE FROM message_fts WHERE dataset_id = ?", (dataset_id,))
    conn.execute("DELETE FROM source_thread WHERE dataset_id = ?", (dataset_id,))
    conn.execute("DELETE FROM model_run WHERE dataset_id = ?", (dataset_id,))
    conn.execute("DELETE FROM embedding_index_metadata WHERE dataset_id = ?", (dataset_id,))
    conn.execute("UPDATE process_log SET dataset_id = NULL WHERE dataset_id = ?", (dataset_id,))
    conn.execute("DELETE FROM dataset WHERE dataset_id = ?", (dataset_id,))
    conn.commit()


def load_normalized_dataset(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    dataset_dir: Path,
    *,
    reload: bool = False,
) -> int:
    dataset_dir = dataset_dir.resolve()
    dataset_json = dataset_dir / "dataset.json"
    threads_jsonl = dataset_dir / "source_threads.jsonl"
    messages_jsonl = dataset_dir / "messages.jsonl"

    for path in (dataset_json, threads_jsonl, messages_jsonl):
        if not path.is_file():
            raise DatasetLoadError(f"Required file not found: {path.name}", file=path.name)

    logger.info(
        component="importers.normalized_loader",
        operation="load_start",
        message=f"Loading normalized dataset from {dataset_dir}",
        details={"dataset_dir": str(dataset_dir)},
    )

    try:
        with dataset_json.open("r", encoding="utf-8") as handle:
            dataset_meta = json.load(handle)
        if not isinstance(dataset_meta, dict):
            raise DatasetLoadError("dataset.json must contain a JSON object", file="dataset.json")
        _validate_required(dataset_meta, REQUIRED_DATASET_FIELDS, file="dataset.json")

        existing = conn.execute(
            "SELECT dataset_id FROM dataset WHERE name = ? ORDER BY dataset_id DESC LIMIT 1",
            (dataset_meta["name"],),
        ).fetchone()
        if existing and not reload:
            dataset_id = int(existing["dataset_id"])
            logger.info(
                component="importers.normalized_loader",
                operation="load_skip_existing",
                message="Dataset already loaded; skipping duplicate load",
                details={"dataset_id": dataset_id, "name": dataset_meta["name"]},
                dataset_id=dataset_id,
            )
            return dataset_id
        embedding_snapshot = None
        if existing and reload:
            from message_evidence_workstation.embeddings.dataset_embedding_cache import (
                restore_dataset_embeddings,
                snapshot_dataset_embeddings,
            )

            embedding_snapshot = snapshot_dataset_embeddings(conn, int(existing["dataset_id"]))
            clear_dataset(conn, int(existing["dataset_id"]))

        created_at = utc_now_iso()
        cursor = conn.execute(
            """
            INSERT INTO dataset (name, created_at, schema_version, notes)
            VALUES (?, ?, ?, ?)
            """,
            (
                dataset_meta["name"],
                created_at,
                SCHEMA_VERSION,
                dataset_meta.get("notes", ""),
            ),
        )
        dataset_id = int(cursor.lastrowid)

        thread_rows = _read_jsonl(threads_jsonl)
        message_rows = _read_jsonl(messages_jsonl)

        thread_ids: set[str] = set()
        for line_number, thread in thread_rows:
            _validate_required(thread, REQUIRED_THREAD_FIELDS, file="source_threads.jsonl", line_number=line_number)
            thread_ids.add(str(thread["source_thread_id"]))
            conn.execute(
                """
                INSERT INTO source_thread (
                    source_thread_id, dataset_id, source_platform, platform_thread_id,
                    display_title, participant_summary, start_ts, end_ts, message_count,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    thread["source_thread_id"],
                    dataset_id,
                    thread["source_platform"],
                    thread["platform_thread_id"],
                    thread["display_title"],
                    thread.get("participant_summary", ""),
                    thread["start_ts"],
                    thread["end_ts"],
                    json.dumps(thread.get("metadata_json", {})),
                ),
            )

        counts_by_thread: dict[str, int] = {thread_id: 0 for thread_id in thread_ids}
        for line_number, message in message_rows:
            _validate_required(message, REQUIRED_MESSAGE_FIELDS, file="messages.jsonl", line_number=line_number)
            source_thread_id = str(message["source_thread_id"])
            if source_thread_id not in thread_ids:
                raise DatasetLoadError(
                    f"Unknown source_thread_id '{source_thread_id}'",
                    file="messages.jsonl",
                    line_number=line_number,
                )
            body = str(message["body"])
            conn.execute(
                """
                INSERT INTO message (
                    message_id, dataset_id, source_thread_id, source_platform,
                    source_message_id, timestamp, sender_id, sender_display, body,
                    body_normalized, has_attachment, attachment_summary, sort_index,
                    source_metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message["message_id"],
                    dataset_id,
                    source_thread_id,
                    message["source_platform"],
                    message["source_message_id"],
                    message["timestamp"],
                    message["sender_id"],
                    message["sender_display"],
                    body,
                    normalize_body(body),
                    int(bool(message.get("has_attachment", False))),
                    message.get("attachment_summary", ""),
                    int(message["sort_index"]),
                    json.dumps(message.get("source_metadata_json", {})),
                ),
            )
            counts_by_thread[source_thread_id] += 1

        for source_thread_id, count in counts_by_thread.items():
            conn.execute(
                """
                UPDATE source_thread
                SET message_count = ?
                WHERE dataset_id = ? AND source_thread_id = ?
                """,
                (count, dataset_id, source_thread_id),
            )

        conn.commit()
        logger.dataset_id = dataset_id
        from message_evidence_workstation.search.fts import rebuild_message_fts

        rebuild_message_fts(conn, logger, dataset_id)
        if embedding_snapshot is not None:
            restore_dataset_embeddings(
                conn,
                logger,
                dataset_id=dataset_id,
                snapshot=embedding_snapshot,
            )
        logger.info(
            component="importers.normalized_loader",
            operation="load_complete",
            message="Normalized dataset load completed",
            details={
                "dataset_id": dataset_id,
                "thread_count": len(thread_rows),
                "message_count": len(message_rows),
            },
            dataset_id=dataset_id,
        )
        return dataset_id
    except DatasetLoadError as exc:
        conn.rollback()
        logger.error(
            component="importers.normalized_loader",
            operation="load_failed",
            message=str(exc),
            details={"file": exc.file, "line_number": exc.line_number},
            exc=exc,
            dataset_id=None,
        )
        raise
    except Exception as exc:
        conn.rollback()
        logger.error(
            component="importers.normalized_loader",
            operation="load_failed",
            message="Unexpected dataset load failure",
            exc=exc,
            dataset_id=None,
        )
        raise
