"""Normalized fixture dataset loader."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from message_evidence_workstation.domain.constants import (
    IMPORT_VALIDITY_FAILED,
    IMPORT_VALIDITY_LOADING,
    IMPORT_VALIDITY_READY,
    IMPORT_VALIDITY_STALE,
    NORMALIZED_FORMAT_VERSION,
    SCHEMA_VERSION,
    WORKSPACE_KEY_DATASET_IMPORT_ERROR,
    WORKSPACE_KEY_DATASET_IMPORT_VALIDITY,
)
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

INSERT_BATCH_SIZE = 1000

ProgressCallback = Callable[[str, int, int], None]

THREAD_INSERT_SQL = """
INSERT INTO source_thread (
    source_thread_id, dataset_id, source_platform, platform_thread_id,
    display_title, participant_summary, start_ts, end_ts, message_count,
    metadata_json
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
"""

MESSAGE_INSERT_SQL = """
INSERT INTO message (
    message_id, dataset_id, source_thread_id, source_platform,
    source_message_id, timestamp, sender_id, sender_display, body,
    body_normalized, has_attachment, attachment_summary, sort_index,
    source_metadata_json
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


class DatasetLoadError(Exception):
    def __init__(self, message: str, *, file: str | None = None, line_number: int | None = None):
        super().__init__(message)
        self.file = file
        self.line_number = line_number


def normalize_body(body: str) -> str:
    collapsed = re.sub(r"\s+", " ", body.strip())
    return collapsed.casefold()


def get_dataset_import_validity(conn: sqlite3.Connection, dataset_id: int) -> str:
    row = conn.execute(
        "SELECT import_validity FROM dataset WHERE dataset_id = ?",
        (dataset_id,),
    ).fetchone()
    if row is None:
        raise DatasetLoadError(f"Unknown dataset_id {dataset_id}")
    return str(row["import_validity"])


def get_workspace_import_validity(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT value FROM workspace_metadata WHERE key = ?",
        (WORKSPACE_KEY_DATASET_IMPORT_VALIDITY,),
    ).fetchone()
    return str(row["value"]) if row else None


def _iter_jsonl(path: Path) -> Iterator[tuple[int, dict[str, Any]]]:
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
            yield line_number, payload


def _validate_required(
    payload: dict[str, Any],
    required: set[str],
    *,
    file: str,
    line_number: int | None = None,
) -> None:
    missing = sorted(required - payload.keys())
    if missing:
        raise DatasetLoadError(
            f"Missing required field(s): {', '.join(missing)}",
            file=file,
            line_number=line_number,
        )


def _validate_normalized_format_version(dataset_meta: dict[str, Any]) -> int | None:
    if "normalized_format_version" not in dataset_meta:
        return None
    raw = dataset_meta["normalized_format_version"]
    if not isinstance(raw, int):
        raise DatasetLoadError(
            "normalized_format_version must be an integer",
            file="dataset.json",
        )
    if raw != NORMALIZED_FORMAT_VERSION:
        raise DatasetLoadError(
            f"Unsupported normalized_format_version {raw} "
            f"(supported: {NORMALIZED_FORMAT_VERSION})",
            file="dataset.json",
        )
    return raw


def _report_progress(
    progress_callback: ProgressCallback | None,
    phase: str,
    lines_read: int,
    lines_written: int,
) -> None:
    if progress_callback is not None:
        progress_callback(phase, lines_read, lines_written)


def _set_workspace_import_validity(
    conn: sqlite3.Connection,
    validity: str,
    *,
    error: str = "",
) -> None:
    for key, value in (
        (WORKSPACE_KEY_DATASET_IMPORT_VALIDITY, validity),
        (WORKSPACE_KEY_DATASET_IMPORT_ERROR, error),
    ):
        conn.execute(
            """
            INSERT INTO workspace_metadata (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
    conn.commit()


def _set_dataset_import_validity(
    conn: sqlite3.Connection,
    dataset_id: int,
    validity: str,
    *,
    error: str = "",
) -> None:
    conn.execute(
        """
        UPDATE dataset
        SET import_validity = ?, import_error = ?
        WHERE dataset_id = ?
        """,
        (validity, error, dataset_id),
    )
    conn.commit()


def _mark_import_failed(
    conn: sqlite3.Connection,
    dataset_id: int | None,
    exc: BaseException,
) -> None:
    message = str(exc)
    _set_workspace_import_validity(conn, IMPORT_VALIDITY_FAILED, error=message)
    if dataset_id is not None:
        _set_dataset_import_validity(conn, dataset_id, IMPORT_VALIDITY_FAILED, error=message)


def _insert_threads_streaming(
    conn: sqlite3.Connection,
    dataset_id: int,
    path: Path,
    thread_ids: set[str],
    *,
    progress_callback: ProgressCallback | None,
    batch_log: Any,
) -> int:
    batch: list[tuple[Any, ...]] = []
    lines_read = 0
    lines_written = 0
    for line_number, thread in _iter_jsonl(path):
        lines_read += 1
        _validate_required(thread, REQUIRED_THREAD_FIELDS, file="source_threads.jsonl", line_number=line_number)
        source_thread_id = str(thread["source_thread_id"])
        thread_ids.add(source_thread_id)
        batch.append(
            (
                source_thread_id,
                dataset_id,
                thread["source_platform"],
                thread["platform_thread_id"],
                thread["display_title"],
                thread.get("participant_summary", ""),
                thread["start_ts"],
                thread["end_ts"],
                json.dumps(thread.get("metadata_json", {})),
            )
        )
        if len(batch) >= INSERT_BATCH_SIZE:
            conn.executemany(THREAD_INSERT_SQL, batch)
            conn.commit()
            lines_written += len(batch)
            _report_progress(progress_callback, "threads", lines_read, lines_written)
            batch_log.info(
                component="importers.normalized_loader",
                operation="threads_batch",
                message=f"Inserted thread batch ({lines_written} rows)",
                details={"lines_read": lines_read, "lines_written": lines_written},
                dataset_id=dataset_id,
            )
            batch.clear()
    if batch:
        conn.executemany(THREAD_INSERT_SQL, batch)
        conn.commit()
        lines_written += len(batch)
        _report_progress(progress_callback, "threads", lines_read, lines_written)
        batch_log.info(
            component="importers.normalized_loader",
            operation="threads_batch",
            message=f"Inserted final thread batch ({lines_written} rows total)",
            details={"lines_read": lines_read, "lines_written": lines_written},
            dataset_id=dataset_id,
        )
    return lines_written


def _insert_messages_streaming(
    conn: sqlite3.Connection,
    dataset_id: int,
    path: Path,
    thread_ids: set[str],
    counts_by_thread: dict[str, int],
    *,
    progress_callback: ProgressCallback | None,
    batch_log: Any,
) -> int:
    batch: list[tuple[Any, ...]] = []
    lines_read = 0
    lines_written = 0
    for line_number, message in _iter_jsonl(path):
        lines_read += 1
        _validate_required(message, REQUIRED_MESSAGE_FIELDS, file="messages.jsonl", line_number=line_number)
        source_thread_id = str(message["source_thread_id"])
        if source_thread_id not in thread_ids:
            raise DatasetLoadError(
                f"Unknown source_thread_id '{source_thread_id}'",
                file="messages.jsonl",
                line_number=line_number,
            )
        body = str(message["body"])
        batch.append(
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
            )
        )
        counts_by_thread[source_thread_id] = counts_by_thread.get(source_thread_id, 0) + 1
        if len(batch) >= INSERT_BATCH_SIZE:
            conn.executemany(MESSAGE_INSERT_SQL, batch)
            conn.commit()
            lines_written += len(batch)
            _report_progress(progress_callback, "messages", lines_read, lines_written)
            batch_log.info(
                component="importers.normalized_loader",
                operation="messages_batch",
                message=f"Inserted message batch ({lines_written} rows)",
                details={"lines_read": lines_read, "lines_written": lines_written},
                dataset_id=dataset_id,
            )
            batch.clear()
    if batch:
        conn.executemany(MESSAGE_INSERT_SQL, batch)
        conn.commit()
        lines_written += len(batch)
        _report_progress(progress_callback, "messages", lines_read, lines_written)
        batch_log.info(
            component="importers.normalized_loader",
            operation="messages_batch",
            message=f"Inserted final message batch ({lines_written} rows total)",
            details={"lines_read": lines_read, "lines_written": lines_written},
            dataset_id=dataset_id,
        )
    return lines_written


def clear_dataset(conn: sqlite3.Connection, dataset_id: int) -> None:
    from message_evidence_workstation.embeddings.sqlite_vec_backend import (
        clear_chunk_vectors,
        clear_message_vectors,
        ensure_chunk_metadata_schema,
    )

    conn.execute(
        "DELETE FROM printable_artifact_evidence_block WHERE printable_artifact_id IN "
        "(SELECT printable_artifact_id FROM printable_artifact WHERE dataset_id = ?)",
        (dataset_id,),
    )
    conn.execute("DELETE FROM printable_artifact WHERE dataset_id = ?", (dataset_id,))
    conn.execute("DELETE FROM printable_artifact_group WHERE dataset_id = ?", (dataset_id,))
    conn.execute(
        "DELETE FROM evidence_block_highlight WHERE evidence_block_id IN "
        "(SELECT evidence_block_id FROM evidence_block WHERE dataset_id = ?)",
        (dataset_id,),
    )
    conn.execute("DELETE FROM evidence_block WHERE dataset_id = ?", (dataset_id,))
    conn.execute("DELETE FROM category WHERE dataset_id = ?", (dataset_id,))
    from message_evidence_workstation.search.spellfix import clear_spellfix_for_dataset

    clear_spellfix_for_dataset(conn, dataset_id)
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


def mark_dataset_import_ready(conn: sqlite3.Connection, dataset_id: int) -> None:
    _set_dataset_import_validity(conn, dataset_id, IMPORT_VALIDITY_READY)
    _set_workspace_import_validity(conn, IMPORT_VALIDITY_READY)


def mark_dataset_import_failed(conn: sqlite3.Connection, dataset_id: int | None, error: str) -> None:
    _set_workspace_import_validity(conn, IMPORT_VALIDITY_FAILED, error=error)
    if dataset_id is not None:
        _set_dataset_import_validity(conn, dataset_id, IMPORT_VALIDITY_FAILED, error=error)


def load_normalized_dataset(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    dataset_dir: Path,
    *,
    reload: bool = False,
    progress_callback: ProgressCallback | None = None,
    run_post_import_steps: bool = True,
) -> int:
    dataset_dir = dataset_dir.resolve()
    dataset_json = dataset_dir / "dataset.json"
    threads_jsonl = dataset_dir / "source_threads.jsonl"
    messages_jsonl = dataset_dir / "messages.jsonl"

    for path in (dataset_json, threads_jsonl, messages_jsonl):
        if not path.is_file():
            raise DatasetLoadError(f"Required file not found: {path.name}", file=path.name)

    dataset_id: int | None = None
    thread_count = 0
    message_count = 0

    try:
        with logger.batch() as batch_log:
            logger.dataset_id = None
            batch_log.info(
                component="importers.normalized_loader",
                operation="load_start",
                message=f"Loading normalized dataset from {dataset_dir}",
                details={"dataset_dir": str(dataset_dir)},
            )

            with dataset_json.open("r", encoding="utf-8") as handle:
                try:
                    dataset_meta = json.load(handle)
                except json.JSONDecodeError as exc:
                    raise DatasetLoadError(
                        f"Malformed JSON in dataset.json: {exc.msg}",
                        file="dataset.json",
                    ) from exc
            if not isinstance(dataset_meta, dict):
                raise DatasetLoadError("dataset.json must contain a JSON object", file="dataset.json")
            _validate_required(dataset_meta, REQUIRED_DATASET_FIELDS, file="dataset.json")
            format_version = _validate_normalized_format_version(dataset_meta)

            existing = conn.execute(
                "SELECT dataset_id, import_validity FROM dataset WHERE name = ? ORDER BY dataset_id DESC LIMIT 1",
                (dataset_meta["name"],),
            ).fetchone()
            if existing and not reload:
                dataset_id = int(existing["dataset_id"])
                logger.dataset_id = dataset_id
                batch_log.info(
                    component="importers.normalized_loader",
                    operation="load_skip_existing",
                    message="Dataset already loaded; skipping duplicate load",
                    details={"dataset_id": dataset_id, "name": dataset_meta["name"]},
                    dataset_id=dataset_id,
                )
                return dataset_id

            _set_workspace_import_validity(conn, IMPORT_VALIDITY_LOADING)

            embedding_snapshot = None
            if existing and reload:
                from message_evidence_workstation.embeddings.dataset_embedding_cache import (
                    restore_dataset_embeddings,
                    snapshot_dataset_embeddings,
                )

                existing_id = int(existing["dataset_id"])
                _set_dataset_import_validity(conn, existing_id, IMPORT_VALIDITY_STALE)
                _set_workspace_import_validity(conn, IMPORT_VALIDITY_STALE)
                embedding_snapshot = snapshot_dataset_embeddings(conn, existing_id)
                clear_dataset(conn, existing_id)

            created_at = utc_now_iso()
            cursor = conn.execute(
                """
                INSERT INTO dataset (
                    name, created_at, schema_version, notes,
                    import_validity, import_error, normalized_format_version
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    dataset_meta["name"],
                    created_at,
                    SCHEMA_VERSION,
                    dataset_meta.get("notes", ""),
                    IMPORT_VALIDITY_LOADING,
                    "",
                    format_version,
                ),
            )
            dataset_id = int(cursor.lastrowid)
            conn.commit()
            logger.dataset_id = dataset_id

            thread_ids: set[str] = set()
            thread_count = _insert_threads_streaming(
                conn,
                dataset_id,
                threads_jsonl,
                thread_ids,
                progress_callback=progress_callback,
                batch_log=batch_log,
            )

            counts_by_thread: dict[str, int] = {}
            message_count = _insert_messages_streaming(
                conn,
                dataset_id,
                messages_jsonl,
                thread_ids,
                counts_by_thread,
                progress_callback=progress_callback,
                batch_log=batch_log,
            )

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

            from message_evidence_workstation.db.repositories import backfill_thread_ordinals

            backfill_thread_ordinals(conn, dataset_id)

            if run_post_import_steps:
                from message_evidence_workstation.search.fts import rebuild_message_fts

                rebuild_message_fts(
                    conn,
                    logger,
                    dataset_id,
                    progress_callback=progress_callback,
                )
                from message_evidence_workstation.search.spellfix import rebuild_spellfix_for_dataset

                rebuild_spellfix_for_dataset(
                    conn,
                    logger,
                    dataset_id,
                    progress_callback=progress_callback,
                )
                if embedding_snapshot is not None:
                    restore_dataset_embeddings(
                        conn,
                        logger,
                        dataset_id=dataset_id,
                        snapshot=embedding_snapshot,
                    )

                _set_dataset_import_validity(conn, dataset_id, IMPORT_VALIDITY_READY)
                _set_workspace_import_validity(conn, IMPORT_VALIDITY_READY)
            elif embedding_snapshot is not None:
                restore_dataset_embeddings(
                    conn,
                    logger,
                    dataset_id=dataset_id,
                    snapshot=embedding_snapshot,
                )

            batch_log.info(
                component="importers.normalized_loader",
                operation="load_complete",
                message="Normalized dataset load completed",
                details={
                    "dataset_id": dataset_id,
                    "thread_count": thread_count,
                    "message_count": message_count,
                },
                dataset_id=dataset_id,
            )
            return dataset_id
    except DatasetLoadError as exc:
        _mark_import_failed(conn, dataset_id, exc)
        logger.error(
            component="importers.normalized_loader",
            operation="load_failed",
            message=str(exc),
            details={"file": exc.file, "line_number": exc.line_number},
            exc=exc,
            dataset_id=dataset_id,
        )
        raise
    except Exception as exc:
        _mark_import_failed(conn, dataset_id, exc)
        logger.error(
            component="importers.normalized_loader",
            operation="load_failed",
            message="Unexpected dataset load failure",
            exc=exc,
            dataset_id=dataset_id,
        )
        raise
