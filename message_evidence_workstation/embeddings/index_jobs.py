"""Embedding index build jobs."""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Iterator

from message_evidence_workstation.embeddings.adapters import EmbeddingAdapter, EmbeddingAdapterInfo
from message_evidence_workstation.embeddings.chunking import (
    ChunkingConfig,
    MessageChunkSpec,
    config_from_mapping,
    count_dataset_chunks,
    iter_dataset_chunks,
    message_vector_count,
)
from message_evidence_workstation.embeddings.sqlite_vec_backend import (
    CHUNK_VEC_TABLE,
    MESSAGE_VEC_TABLE,
    clear_chunk_vectors,
    clear_message_vectors,
    ensure_chunk_metadata_schema,
    ensure_chunk_vec_table,
    ensure_message_vec_table,
    insert_chunk_vectors,
    insert_message_vectors,
    load_sqlite_vec,
    sqlite_vec_version,
)
from message_evidence_workstation.logging_ui.process_log import ProcessLogger, utc_now_iso

BATCH_SIZE = 32
CHUNK_MAX_CHARS = 1200


@dataclass(slots=True)
class IndexBuildResult:
    success: bool
    count: int
    elapsed_ms: int
    model_name: str
    dimensions: int
    error: str | None = None
    resumed: bool = False
    total_target: int = 0


def _progress_payload(
    *,
    completed: int,
    total: int,
    batch: int,
    batch_total: int,
    resumed: bool,
) -> dict[str, Any]:
    return {
        "build_progress": {
            "completed": completed,
            "total": total,
            "batch": batch,
            "batch_total": batch_total,
            "resumed": resumed,
        }
    }


def _merge_progress_json(existing_json: str, progress: dict[str, Any]) -> str:
    try:
        payload = json.loads(existing_json) if existing_json else {}
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload.update(progress)
    return json.dumps(payload)


def _get_latest_metadata(
    conn: sqlite3.Connection,
    dataset_id: int,
    granularity: str,
    model_name: str,
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT embedding_index_id, status, dimensions, message_count, chunk_count,
               chunking_config_json, last_error
        FROM embedding_index_metadata
        WHERE dataset_id = ? AND granularity = ? AND model_name = ?
        ORDER BY embedding_index_id DESC
        LIMIT 1
        """,
        (dataset_id, granularity, model_name),
    ).fetchone()


def _metadata_chunking_config_matches(row: sqlite3.Row | None, chunking_config: dict[str, Any] | None) -> bool:
    if chunking_config is None or row is None:
        return True
    try:
        stored = json.loads(row["chunking_config_json"] or "{}")
    except json.JSONDecodeError:
        stored = {}
    if not isinstance(stored, dict):
        stored = {}
    stored.pop("build_progress", None)
    expected = dict(chunking_config)
    expected.pop("build_progress", None)
    return stored == expected


def _message_count(conn: sqlite3.Connection, dataset_id: int) -> int:
    return int(
        conn.execute(
            "SELECT COUNT(*) FROM message WHERE dataset_id = ?",
            (dataset_id,),
        ).fetchone()[0]
    )


def _iter_pending_message_batches(
    conn: sqlite3.Connection,
    dataset_id: int,
    embedded_ids: set[str],
    *,
    batch_size: int = BATCH_SIZE,
) -> Iterator[list[sqlite3.Row]]:
    cursor = conn.execute(
        """
        SELECT message_id, source_thread_id, body_normalized
        FROM message
        WHERE dataset_id = ?
        ORDER BY source_thread_id, timestamp, sort_index, message_id
        """,
        (dataset_id,),
    )
    pending: list[sqlite3.Row] = []
    for row in cursor:
        if row["message_id"] in embedded_ids:
            continue
        pending.append(row)
        if len(pending) >= batch_size:
            yield pending
            pending = []
    if pending:
        yield pending


def _vec_table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _embedded_message_ids(conn: sqlite3.Connection, dataset_id: int) -> set[str]:
    if not _vec_table_exists(conn, MESSAGE_VEC_TABLE):
        return set()
    load_sqlite_vec(conn)
    rows = conn.execute(
        "SELECT message_id FROM message_embedding_vec WHERE dataset_id = ?",
        (dataset_id,),
    ).fetchall()
    return {str(row["message_id"]) for row in rows}


def _embedded_chunk_vector_count(conn: sqlite3.Connection, dataset_id: int) -> int:
    if not _vec_table_exists(conn, CHUNK_VEC_TABLE):
        return 0
    load_sqlite_vec(conn)
    return int(
        conn.execute(
            "SELECT COUNT(*) FROM chunk_embedding_vec WHERE dataset_id = ?",
            (dataset_id,),
        ).fetchone()[0]
    )


def _embedded_chunk_checksums(conn: sqlite3.Connection, dataset_id: int) -> set[str]:
    rows = conn.execute(
        "SELECT text_checksum FROM message_chunk WHERE dataset_id = ?",
        (dataset_id,),
    ).fetchall()
    return {str(row["text_checksum"]) for row in rows}


def _should_resume_build(
    conn: sqlite3.Connection,
    dataset_id: int,
    granularity: str,
    model_name: str,
    adapter_info: EmbeddingAdapterInfo,
    chunking_config: dict[str, Any] | None = None,
) -> tuple[bool, int]:
    row = _get_latest_metadata(conn, dataset_id, granularity, model_name)
    if row is None:
        return False, 0
    if row["status"] == "stale":
        return False, 0
    if granularity == "chunk" and not _metadata_chunking_config_matches(row, chunking_config):
        return False, 0
    if row["dimensions"] != adapter_info.dimensions:
        return False, 0
    if granularity == "message":
        already = len(_embedded_message_ids(conn, dataset_id))
    else:
        already = _embedded_chunk_vector_count(conn, dataset_id)
    if already <= 0:
        if row["status"] in ("building", "failed"):
            return True, 0
        return False, 0
    if row["status"] in ("building", "failed", "ready"):
        return True, int(already)
    return False, 0


def _index_build_already_complete(
    conn: sqlite3.Connection,
    *,
    dataset_id: int,
    granularity: str,
    model_name: str,
    adapter_info: EmbeddingAdapterInfo,
    force_restart: bool,
    chunking_config: ChunkingConfig | None = None,
) -> IndexBuildResult | None:
    if force_restart:
        return None
    row = get_ready_index(conn, dataset_id, granularity, model_name)
    if row is None or row["dimensions"] != adapter_info.dimensions:
        return None
    chunking_metadata = chunking_config.to_metadata() if chunking_config is not None else None
    if granularity == "chunk" and not _metadata_chunking_config_matches(row, chunking_metadata):
        return None
    if granularity == "message":
        total = _message_count(conn, dataset_id)
        embedded = len(_embedded_message_ids(conn, dataset_id))
    else:
        total = count_dataset_chunks(conn, dataset_id, config=chunking_config)
        embedded = len(_embedded_chunk_checksums(conn, dataset_id))
    if total <= 0 or embedded < total:
        return None
    return IndexBuildResult(
        success=True,
        count=embedded,
        elapsed_ms=0,
        model_name=model_name,
        dimensions=adapter_info.dimensions,
        resumed=True,
        total_target=total,
    )


def _upsert_metadata(
    conn: sqlite3.Connection,
    *,
    dataset_id: int,
    granularity: str,
    model_name: str,
    adapter_info: EmbeddingAdapterInfo,
    status: str,
    message_count: int = 0,
    chunk_count: int = 0,
    last_error: str = "",
    chunking_config: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        """
        DELETE FROM embedding_index_metadata
        WHERE dataset_id = ? AND granularity = ? AND model_name = ?
        """,
        (dataset_id, granularity, model_name),
    )
    conn.execute(
        """
        INSERT INTO embedding_index_metadata (
            dataset_id, granularity, backend, model_name, model_revision, dimensions,
            distance_metric, normalization_mode, chunking_config_json, sqlite_vec_version,
            extension_path, created_at, status, message_count, chunk_count, last_error
        ) VALUES (?, ?, 'sqlite_vec', ?, ?, ?, 'cosine', ?, ?, ?, 'auto', ?, ?, ?, ?, ?)
        """,
        (
            dataset_id,
            granularity,
            model_name,
            adapter_info.model_revision,
            adapter_info.dimensions,
            adapter_info.normalization_mode,
            json.dumps(chunking_config or {}),
            sqlite_vec_version(),
            utc_now_iso(),
            status,
            message_count,
            chunk_count,
            last_error,
        ),
    )
    conn.commit()


def _mark_metadata_building(
    conn: sqlite3.Connection,
    *,
    dataset_id: int,
    granularity: str,
    model_name: str,
    adapter_info: EmbeddingAdapterInfo,
    resume: bool,
    already_embedded: int,
    chunking_config: dict[str, Any] | None = None,
) -> None:
    if resume:
        row = _get_latest_metadata(conn, dataset_id, granularity, model_name)
        progress_json = _merge_progress_json(
            row["chunking_config_json"] if row else "{}",
            _progress_payload(
                completed=already_embedded,
                total=already_embedded,
                batch=0,
                batch_total=0,
                resumed=True,
            ),
        )
        conn.execute(
            """
            UPDATE embedding_index_metadata
            SET status = 'building', last_error = '', chunking_config_json = ?,
                model_revision = ?, dimensions = ?, normalization_mode = ?
            WHERE dataset_id = ? AND granularity = ? AND model_name = ?
            """,
            (
                progress_json,
                adapter_info.model_revision,
                adapter_info.dimensions,
                adapter_info.normalization_mode,
                dataset_id,
                granularity,
                model_name,
            ),
        )
        if conn.total_changes == 0:
            _upsert_metadata(
                conn,
                dataset_id=dataset_id,
                granularity=granularity,
                model_name=model_name,
                adapter_info=adapter_info,
                status="building",
                message_count=already_embedded if granularity == "message" else 0,
                chunk_count=already_embedded if granularity == "chunk" else 0,
                chunking_config=chunking_config,
            )
        else:
            conn.commit()
        return
    _upsert_metadata(
        conn,
        dataset_id=dataset_id,
        granularity=granularity,
        model_name=model_name,
        adapter_info=adapter_info,
        status="building",
        chunking_config=chunking_config,
    )


def _update_build_progress(
    conn: sqlite3.Connection,
    *,
    dataset_id: int,
    granularity: str,
    model_name: str,
    message_count: int,
    chunk_count: int,
    progress: dict[str, Any],
    chunking_config: dict[str, Any] | None = None,
) -> None:
    row = _get_latest_metadata(conn, dataset_id, granularity, model_name)
    base: dict[str, Any] = {}
    if chunking_config:
        base.update(chunking_config)
    if row:
        try:
            existing = json.loads(row["chunking_config_json"] or "{}")
            if isinstance(existing, dict):
                for key, value in existing.items():
                    if key != "build_progress":
                        base.setdefault(key, value)
        except json.JSONDecodeError:
            pass
    base.update(progress)
    conn.execute(
        """
        UPDATE embedding_index_metadata
        SET message_count = ?, chunk_count = ?, chunking_config_json = ?, status = 'building'
        WHERE dataset_id = ? AND granularity = ? AND model_name = ?
        """,
        (
            message_count,
            chunk_count,
            json.dumps(base),
            dataset_id,
            granularity,
            model_name,
        ),
    )
    conn.commit()


def mark_indexes_stale_for_model_change(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    dataset_id: int,
    new_model_name: str,
) -> None:
    rows = conn.execute(
        """
        SELECT embedding_index_id, granularity, model_name, status
        FROM embedding_index_metadata
        WHERE dataset_id = ? AND granularity IN ('message', 'chunk')
          AND model_name != ? AND status = 'ready'
        """,
        (dataset_id, new_model_name),
    ).fetchall()
    if not rows:
        return
    conn.execute(
        """
        UPDATE embedding_index_metadata
        SET status = 'stale', last_error = 'Embedding model changed'
        WHERE dataset_id = ? AND granularity IN ('message', 'chunk')
          AND model_name != ? AND status = 'ready'
        """,
        (dataset_id, new_model_name),
    )
    conn.commit()
    logger.warning(
        component="embeddings.index_jobs",
        operation="mark_indexes_stale",
        message="Marked embedding indexes stale after model change",
        details={"dataset_id": dataset_id, "new_model_name": new_model_name, "count": len(rows)},
        dataset_id=dataset_id,
    )


def get_ready_index(
    conn: sqlite3.Connection,
    dataset_id: int,
    granularity: str,
    model_name: str,
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT embedding_index_id, dimensions, status, model_name, message_count, chunk_count,
               chunking_config_json, last_error
        FROM embedding_index_metadata
        WHERE dataset_id = ? AND granularity = ? AND model_name = ? AND status = 'ready'
        ORDER BY embedding_index_id DESC
        LIMIT 1
        """,
        (dataset_id, granularity, model_name),
    ).fetchone()


def build_message_embedding_index(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    *,
    dataset_id: int,
    adapter: EmbeddingAdapter,
    adapter_info: EmbeddingAdapterInfo,
    force_restart: bool = False,
) -> IndexBuildResult:
    started = time.perf_counter()
    model_name = adapter_info.model_name
    try:
        load_sqlite_vec(conn)
        ensure_message_vec_table(conn, adapter_info.dimensions)
    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return IndexBuildResult(
            success=False,
            count=0,
            elapsed_ms=elapsed_ms,
            model_name=model_name,
            dimensions=adapter_info.dimensions,
            error=f"sqlite-vec init failed: {exc}",
        )
    if force_restart:
        resume = False
        already_embedded = 0
    else:
        complete = _index_build_already_complete(
            conn,
            dataset_id=dataset_id,
            granularity="message",
            model_name=model_name,
            adapter_info=adapter_info,
            force_restart=force_restart,
        )
        if complete is not None:
            logger.info(
                component="embeddings.index_jobs",
                operation="message_index_skip_complete",
                message=(
                    f"Message embedding index already complete: "
                    f"{complete.count}/{complete.total_target} messages"
                ),
                details={
                    "dataset_id": dataset_id,
                    "model_name": model_name,
                    "embedded_count": complete.count,
                },
                dataset_id=dataset_id,
            )
            return complete
        resume, already_embedded = _should_resume_build(
            conn, dataset_id, "message", model_name, adapter_info
        )

    total_messages = _message_count(conn, dataset_id)

    logger.info(
        component="embeddings.index_jobs",
        operation="message_index_build_start",
        message=(
            f"Starting message embedding index build for {total_messages} messages"
            + (f" (resuming from {already_embedded} already embedded)" if resume else "")
        ),
        details={
            "dataset_id": dataset_id,
            "model_name": model_name,
            "dimensions": adapter_info.dimensions,
            "total_messages": total_messages,
            "batch_size": BATCH_SIZE,
            "batch_total": max((total_messages + BATCH_SIZE - 1) // BATCH_SIZE, 0),
            "resume": resume,
            "already_embedded": already_embedded,
        },
        dataset_id=dataset_id,
    )
    _mark_metadata_building(
        conn,
        dataset_id=dataset_id,
        granularity="message",
        model_name=model_name,
        adapter_info=adapter_info,
        resume=resume,
        already_embedded=already_embedded,
    )
    try:
        if not resume:
            clear_message_vectors(conn, dataset_id)

        embedded_ids = _embedded_message_ids(conn, dataset_id)
        embedded = len(embedded_ids)
        failures = 0
        if embedded_ids:
            pending_total = sum(
                len(batch)
                for batch in _iter_pending_message_batches(conn, dataset_id, embedded_ids)
            )
        else:
            pending_total = total_messages
        batch_total = max((pending_total + BATCH_SIZE - 1) // BATCH_SIZE, 0)

        if resume and embedded:
            logger.info(
                component="embeddings.index_jobs",
                operation="message_index_resume",
                message=f"Resuming message embeddings: {embedded}/{total_messages} already stored",
                details={"embedded": embedded, "remaining": pending_total},
                dataset_id=dataset_id,
            )

        batch_index = 0
        for batch in _iter_pending_message_batches(conn, dataset_id, embedded_ids):
            batch_index += 1
            texts = [row["body_normalized"] or row["message_id"] for row in batch]
            try:
                vectors = adapter.embed_texts(texts)
            except Exception as exc:
                failures += len(batch)
                logger.error(
                    component="embeddings.index_jobs",
                    operation="message_batch_embed_failed",
                    message=f"Message embeddings batch {batch_index}/{batch_total} failed",
                    details={"batch": batch_index, "batch_total": batch_total},
                    exc=exc,
                    dataset_id=dataset_id,
                )
                continue
            if len(vectors) != len(batch):
                raise RuntimeError(
                    f"Embedding count mismatch: expected {len(batch)}, got {len(vectors)}"
                )
            payload = [
                (vector, row["message_id"], dataset_id, row["source_thread_id"])
                for vector, row in zip(vectors, batch, strict=True)
            ]
            insert_message_vectors(conn, payload)
            conn.commit()
            embedded += len(batch)
            elapsed_so_far = time.perf_counter() - started
            rate = embedded / max(elapsed_so_far, 0.001)
            remaining = total_messages - embedded
            eta_seconds = int(remaining / rate) if rate > 0 else None
            progress = _progress_payload(
                completed=embedded,
                total=total_messages,
                batch=batch_index,
                batch_total=batch_total,
                resumed=resume,
            )
            _update_build_progress(
                conn,
                dataset_id=dataset_id,
                granularity="message",
                model_name=model_name,
                message_count=embedded,
                chunk_count=0,
                progress=progress,
            )
            logger.info(
                component="embeddings.index_jobs",
                operation="message_batch_progress",
                message=(
                    f"Message embeddings batch {batch_index}/{batch_total} "
                    f"({embedded}/{total_messages} messages)"
                ),
                details={
                    "batch": batch_index,
                    "batch_total": batch_total,
                    "embedded": embedded,
                    "total": total_messages,
                    "failures": failures,
                    "elapsed_ms": int(elapsed_so_far * 1000),
                    "messages_per_second": round(rate, 2),
                    "eta_seconds": eta_seconds,
                },
                dataset_id=dataset_id,
            )

        stored = conn.execute(
            "SELECT COUNT(*) FROM message_embedding_vec WHERE dataset_id = ?",
            (dataset_id,),
        ).fetchone()[0]
        if stored != embedded:
            raise RuntimeError(f"Vector row count mismatch: stored={stored}, embedded={embedded}")
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        from message_evidence_workstation.diagnostics.trace_log import trace

        trace(
            "index_jobs",
            "message_index_build_complete",
            embedded=embedded,
            total_messages=total_messages,
            elapsed_ms=elapsed_ms,
        )
        _upsert_metadata(
            conn,
            dataset_id=dataset_id,
            granularity="message",
            model_name=model_name,
            adapter_info=adapter_info,
            status="ready",
            message_count=embedded,
        )
        logger.info(
            component="embeddings.index_jobs",
            operation="message_index_build_complete",
            message=(
                f"Message embedding index ready: {embedded}/{total_messages} messages "
                f"in {elapsed_ms}ms"
            ),
            details={
                "embedded_count": embedded,
                "total_messages": total_messages,
                "failures": failures,
                "elapsed_ms": elapsed_ms,
                "resumed": resume,
                "messages_per_second": round(embedded / max(elapsed_ms / 1000.0, 0.001), 2),
            },
            dataset_id=dataset_id,
        )
        return IndexBuildResult(
            success=True,
            count=embedded,
            elapsed_ms=elapsed_ms,
            model_name=model_name,
            dimensions=adapter_info.dimensions,
            resumed=resume,
            total_target=total_messages,
        )
    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        embedded_now = len(_embedded_message_ids(conn, dataset_id))
        conn.execute(
            """
            UPDATE embedding_index_metadata
            SET status = 'failed', last_error = ?, message_count = ?
            WHERE dataset_id = ? AND granularity = 'message' AND model_name = ?
            """,
            (str(exc), embedded_now, dataset_id, model_name),
        )
        conn.commit()
        logger.error(
            component="embeddings.index_jobs",
            operation="message_index_build_failed",
            message=(
                f"Message embedding index build failed after {embedded_now} messages "
                f"(re-run Build to resume)"
            ),
            details={"embedded_before_failure": embedded_now, "total_messages": total_messages},
            exc=exc,
            dataset_id=dataset_id,
        )
        return IndexBuildResult(
            success=False,
            count=embedded_now,
            elapsed_ms=elapsed_ms,
            model_name=model_name,
            dimensions=adapter_info.dimensions,
            error=str(exc),
            resumed=resume,
            total_target=total_messages,
        )


def build_chunk_embedding_index(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    *,
    dataset_id: int,
    adapter: EmbeddingAdapter,
    adapter_info: EmbeddingAdapterInfo,
    force_restart: bool = False,
    chunking_config: ChunkingConfig | dict[str, Any] | None = None,
) -> IndexBuildResult:
    started = time.perf_counter()
    model_name = adapter_info.model_name
    resolved_chunking_config = (
        chunking_config
        if isinstance(chunking_config, ChunkingConfig)
        else config_from_mapping(chunking_config, max_chars=CHUNK_MAX_CHARS)
    )
    chunking_metadata = resolved_chunking_config.to_metadata()
    try:
        load_sqlite_vec(conn)
        ensure_chunk_metadata_schema(conn)
        ensure_chunk_vec_table(conn, adapter_info.dimensions)
    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return IndexBuildResult(
            success=False,
            count=0,
            elapsed_ms=elapsed_ms,
            model_name=model_name,
            dimensions=adapter_info.dimensions,
            error=f"sqlite-vec init failed: {exc}",
        )
    if resolved_chunking_config.use_semantic_boundaries:
        total_messages = _message_count(conn, dataset_id)
        ready_message_vectors = message_vector_count(conn, dataset_id)
        if ready_message_vectors < total_messages:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            error = (
                "Build message embeddings before semantic chunk embeddings "
                f"({ready_message_vectors}/{total_messages} message vectors ready)."
            )
            logger.warning(
                component="embeddings.index_jobs",
                operation="chunk_index_requires_message_vectors",
                message=error,
                details={
                    "message_count": total_messages,
                    "message_vector_count": ready_message_vectors,
                    "chunking_config": chunking_metadata,
                },
                dataset_id=dataset_id,
            )
            return IndexBuildResult(
                success=False,
                count=0,
                elapsed_ms=elapsed_ms,
                model_name=model_name,
                dimensions=adapter_info.dimensions,
                error=error,
            )
    if force_restart:
        resume = False
        already_embedded = 0
    else:
        complete = _index_build_already_complete(
            conn,
            dataset_id=dataset_id,
            granularity="chunk",
            model_name=model_name,
            adapter_info=adapter_info,
            force_restart=force_restart,
            chunking_config=resolved_chunking_config,
        )
        if complete is not None:
            logger.info(
                component="embeddings.index_jobs",
                operation="chunk_index_skip_complete",
                message=(
                    f"Chunk embedding index already complete: "
                    f"{complete.count}/{complete.total_target} chunks"
                ),
                details={
                    "dataset_id": dataset_id,
                    "model_name": model_name,
                    "embedded_count": complete.count,
                },
                dataset_id=dataset_id,
            )
            return complete
        resume, already_embedded = _should_resume_build(
            conn,
            dataset_id,
            "chunk",
            model_name,
            adapter_info,
            chunking_metadata,
        )

    logger.info(
        component="embeddings.index_jobs",
        operation="chunk_index_count_start",
        message="Counting chunks (per-thread streaming)…",
        details={"dataset_id": dataset_id, **chunking_metadata},
        dataset_id=dataset_id,
    )
    total_chunks = count_dataset_chunks(conn, dataset_id, config=resolved_chunking_config)

    logger.info(
        component="embeddings.index_jobs",
        operation="chunk_index_build_start",
        message=(
            f"Starting chunk embedding index build for {total_chunks} chunks"
            + (f" (resuming from {already_embedded} already embedded)" if resume else "")
        ),
        details={
            "dataset_id": dataset_id,
            "model_name": model_name,
            "chunking_config": chunking_metadata,
            "total_chunks": total_chunks,
            "batch_size": BATCH_SIZE,
            "resume": resume,
            "already_embedded": already_embedded,
        },
        dataset_id=dataset_id,
    )
    _mark_metadata_building(
        conn,
        dataset_id=dataset_id,
        granularity="chunk",
        model_name=model_name,
        adapter_info=adapter_info,
        resume=resume,
        already_embedded=already_embedded,
        chunking_config=chunking_metadata,
    )
    try:
        if not resume:
            clear_chunk_vectors(conn, dataset_id)

        embedded_checksums = _embedded_chunk_checksums(conn, dataset_id)
        embedded = len(embedded_checksums)
        if embedded_checksums:
            pending_total = sum(
                1
                for chunk in iter_dataset_chunks(conn, dataset_id, config=resolved_chunking_config)
                if chunk.text_checksum not in embedded_checksums
            )
        else:
            pending_total = total_chunks
        batch_total = max((pending_total + BATCH_SIZE - 1) // BATCH_SIZE, 0)

        logger.info(
            component="embeddings.index_jobs",
            operation="chunking_complete",
            message=f"Chunking complete: {total_chunks} chunks ({pending_total} remaining)",
            details={"chunk_count": total_chunks, "pending": pending_total},
            dataset_id=dataset_id,
        )

        if resume and embedded:
            logger.info(
                component="embeddings.index_jobs",
                operation="chunk_index_resume",
                message=f"Resuming chunk embeddings: {embedded}/{total_chunks} already stored",
                details={"embedded": embedded, "remaining": pending_total},
                dataset_id=dataset_id,
            )

        batch_index = 0
        failures = 0
        pending_batch: list[MessageChunkSpec] = []
        for chunk in iter_dataset_chunks(conn, dataset_id, config=resolved_chunking_config):
            if chunk.text_checksum in embedded_checksums:
                continue
            pending_batch.append(chunk)
            if len(pending_batch) < BATCH_SIZE:
                continue
            batch_index += 1
            batch = pending_batch
            pending_batch = []
            texts = [item.body_text for item in batch]
            try:
                vectors = adapter.embed_texts(texts)
            except Exception as exc:
                failures += len(batch)
                logger.error(
                    component="embeddings.index_jobs",
                    operation="chunk_batch_embed_failed",
                    message=f"Chunk embeddings batch {batch_index}/{batch_total} failed",
                    details={"batch": batch_index, "batch_total": batch_total},
                    exc=exc,
                    dataset_id=dataset_id,
                )
                continue
            if len(vectors) != len(batch):
                raise RuntimeError(
                    f"Chunk embedding count mismatch: expected {len(batch)}, got {len(vectors)}"
                )
            for chunk_item, vector in zip(batch, vectors, strict=True):
                cursor = conn.execute(
                    """
                    INSERT INTO message_chunk (
                        dataset_id, source_thread_id, start_message_id, end_message_id,
                        message_count, char_count, text_checksum, body_text
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        dataset_id,
                        chunk_item.source_thread_id,
                        chunk_item.start_message_id,
                        chunk_item.end_message_id,
                        chunk_item.message_count,
                        chunk_item.char_count,
                        chunk_item.text_checksum,
                        chunk_item.body_text,
                    ),
                )
                chunk_id = int(cursor.lastrowid)
                insert_chunk_vectors(
                    conn,
                    [(vector, chunk_id, dataset_id, chunk_item.source_thread_id)],
                )
                embedded_checksums.add(chunk_item.text_checksum)
            conn.commit()
            embedded += len(batch)
            elapsed_so_far = time.perf_counter() - started
            rate = embedded / max(elapsed_so_far, 0.001)
            remaining = total_chunks - embedded
            eta_seconds = int(remaining / rate) if rate > 0 else None
            progress = _progress_payload(
                completed=embedded,
                total=total_chunks,
                batch=batch_index,
                batch_total=batch_total,
                resumed=resume,
            )
            _update_build_progress(
                conn,
                dataset_id=dataset_id,
                granularity="chunk",
                model_name=model_name,
                message_count=0,
                chunk_count=embedded,
                progress=progress,
                chunking_config=chunking_metadata,
            )
            logger.info(
                component="embeddings.index_jobs",
                operation="chunk_batch_progress",
                message=(
                    f"Chunk embeddings batch {batch_index}/{batch_total} "
                    f"({embedded}/{total_chunks} chunks)"
                ),
                details={
                    "batch": batch_index,
                    "batch_total": batch_total,
                    "embedded": embedded,
                    "total": total_chunks,
                    "failures": failures,
                    "elapsed_ms": int(elapsed_so_far * 1000),
                    "chunks_per_second": round(rate, 2),
                    "eta_seconds": eta_seconds,
                },
                dataset_id=dataset_id,
            )

        if pending_batch:
            batch_index += 1
            batch = pending_batch
            texts = [item.body_text for item in batch]
            try:
                vectors = adapter.embed_texts(texts)
            except Exception as exc:
                failures += len(batch)
                logger.error(
                    component="embeddings.index_jobs",
                    operation="chunk_batch_embed_failed",
                    message=f"Chunk embeddings final batch {batch_index}/{batch_total} failed",
                    details={"batch": batch_index, "batch_total": batch_total},
                    exc=exc,
                    dataset_id=dataset_id,
                )
            else:
                if len(vectors) != len(batch):
                    raise RuntimeError(
                        f"Chunk embedding count mismatch: expected {len(batch)}, got {len(vectors)}"
                    )
                for chunk_item, vector in zip(batch, vectors, strict=True):
                    cursor = conn.execute(
                        """
                        INSERT INTO message_chunk (
                            dataset_id, source_thread_id, start_message_id, end_message_id,
                            message_count, char_count, text_checksum, body_text
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            dataset_id,
                            chunk_item.source_thread_id,
                            chunk_item.start_message_id,
                            chunk_item.end_message_id,
                            chunk_item.message_count,
                            chunk_item.char_count,
                            chunk_item.text_checksum,
                            chunk_item.body_text,
                        ),
                    )
                    chunk_id = int(cursor.lastrowid)
                    insert_chunk_vectors(
                        conn,
                        [(vector, chunk_id, dataset_id, chunk_item.source_thread_id)],
                    )
                    embedded_checksums.add(chunk_item.text_checksum)
                conn.commit()
                embedded += len(batch)
                progress = _progress_payload(
                    completed=embedded,
                    total=total_chunks,
                    batch=batch_index,
                    batch_total=batch_total,
                    resumed=resume,
                )
                _update_build_progress(
                    conn,
                    dataset_id=dataset_id,
                    granularity="chunk",
                    model_name=model_name,
                    message_count=0,
                    chunk_count=embedded,
                    progress=progress,
                    chunking_config=chunking_metadata,
                )

        stored = conn.execute(
            "SELECT COUNT(*) FROM chunk_embedding_vec WHERE dataset_id = ?",
            (dataset_id,),
        ).fetchone()[0]
        if stored != embedded:
            raise RuntimeError(f"Chunk vector row count mismatch: stored={stored}, embedded={embedded}")
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        _upsert_metadata(
            conn,
            dataset_id=dataset_id,
            granularity="chunk",
            model_name=model_name,
            adapter_info=adapter_info,
            status="ready",
            chunk_count=embedded,
            chunking_config=chunking_metadata,
        )
        logger.info(
            component="embeddings.index_jobs",
            operation="chunk_index_build_complete",
            message=f"Chunk embedding index ready: {embedded}/{total_chunks} chunks in {elapsed_ms}ms",
            details={"chunk_count": embedded, "elapsed_ms": elapsed_ms, "resumed": resume},
            dataset_id=dataset_id,
        )
        return IndexBuildResult(
            success=True,
            count=embedded,
            elapsed_ms=elapsed_ms,
            model_name=model_name,
            dimensions=adapter_info.dimensions,
            resumed=resume,
            total_target=total_chunks,
        )
    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        embedded_now = conn.execute(
            "SELECT COUNT(*) FROM chunk_embedding_vec WHERE dataset_id = ?",
            (dataset_id,),
        ).fetchone()[0]
        conn.execute(
            """
            UPDATE embedding_index_metadata
            SET status = 'failed', last_error = ?, chunk_count = ?
            WHERE dataset_id = ? AND granularity = 'chunk' AND model_name = ?
            """,
            (str(exc), embedded_now, dataset_id, model_name),
        )
        conn.commit()
        logger.error(
            component="embeddings.index_jobs",
            operation="chunk_index_build_failed",
            message=(
                f"Chunk embedding index build failed after {embedded_now} chunks "
                f"(re-run Build to resume)"
            ),
            details={"embedded_before_failure": embedded_now, "total_chunks": total_chunks},
            exc=exc,
            dataset_id=dataset_id,
        )
        return IndexBuildResult(
            success=False,
            count=embedded_now,
            elapsed_ms=elapsed_ms,
            model_name=model_name,
            dimensions=adapter_info.dimensions,
            error=str(exc),
            resumed=resume,
            total_target=total_chunks,
        )
