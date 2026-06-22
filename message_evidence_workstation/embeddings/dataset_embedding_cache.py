"""Preserve embedding indexes across dataset reloads."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from message_evidence_workstation.logging_ui.process_log import ProcessLogger


@dataclass(slots=True)
class MessageVectorSnapshot:
    embedding_blob: bytes
    message_id: str
    source_thread_id: str


@dataclass(slots=True)
class ChunkVectorSnapshot:
    embedding_blob: bytes
    source_thread_id: str
    start_message_id: str
    end_message_id: str
    message_count: int
    char_count: int
    text_checksum: str
    body_text: str


@dataclass(slots=True)
class EmbeddingMetadataSnapshot:
    granularity: str
    backend: str
    model_name: str
    model_revision: str
    dimensions: int | None
    distance_metric: str
    normalization_mode: str
    chunking_config_json: str
    sqlite_vec_version: str
    extension_path: str
    created_at: str
    status: str
    message_count: int
    chunk_count: int
    last_error: str


@dataclass(slots=True)
class DatasetEmbeddingSnapshot:
    dimensions: int | None
    messages: list[MessageVectorSnapshot] = field(default_factory=list)
    chunks: list[ChunkVectorSnapshot] = field(default_factory=list)
    metadata: list[EmbeddingMetadataSnapshot] = field(default_factory=list)


@dataclass(slots=True)
class EmbeddingRestoreResult:
    restored_messages: int
    restored_chunks: int
    skipped_messages: int
    skipped_chunks: int


def snapshot_dataset_embeddings(
    conn: sqlite3.Connection,
    dataset_id: int,
) -> DatasetEmbeddingSnapshot | None:
    from message_evidence_workstation.embeddings.sqlite_vec_backend import (
        CHUNK_VEC_TABLE,
        MESSAGE_VEC_TABLE,
        _table_dimensions,
        _table_exists,
        ensure_chunk_metadata_schema,
        load_sqlite_vec,
    )

    snapshot = DatasetEmbeddingSnapshot(dimensions=None)
    if _table_exists(conn, MESSAGE_VEC_TABLE):
        load_sqlite_vec(conn)
        snapshot.dimensions = _table_dimensions(conn, MESSAGE_VEC_TABLE)
        rows = conn.execute(
            f"""
            SELECT embedding, message_id, source_thread_id
            FROM {MESSAGE_VEC_TABLE}
            WHERE dataset_id = ?
            """,
            (dataset_id,),
        ).fetchall()
        for row in rows:
            snapshot.messages.append(
                MessageVectorSnapshot(
                    embedding_blob=bytes(row["embedding"]),
                    message_id=str(row["message_id"]),
                    source_thread_id=str(row["source_thread_id"]),
                )
            )

    ensure_chunk_metadata_schema(conn)
    chunk_meta = {
        int(row["chunk_id"]): row
        for row in conn.execute(
            """
            SELECT chunk_id, source_thread_id, start_message_id, end_message_id,
                   message_count, char_count, text_checksum, body_text
            FROM message_chunk
            WHERE dataset_id = ?
            """,
            (dataset_id,),
        ).fetchall()
    }
    if _table_exists(conn, CHUNK_VEC_TABLE):
        load_sqlite_vec(conn)
        if snapshot.dimensions is None:
            snapshot.dimensions = _table_dimensions(conn, CHUNK_VEC_TABLE)
        rows = conn.execute(
            f"""
            SELECT embedding, chunk_id, source_thread_id
            FROM {CHUNK_VEC_TABLE}
            WHERE dataset_id = ?
            """,
            (dataset_id,),
        ).fetchall()
        for row in rows:
            meta = chunk_meta.get(int(row["chunk_id"]))
            if meta is None:
                continue
            snapshot.chunks.append(
                ChunkVectorSnapshot(
                    embedding_blob=bytes(row["embedding"]),
                    source_thread_id=str(meta["source_thread_id"]),
                    start_message_id=str(meta["start_message_id"]),
                    end_message_id=str(meta["end_message_id"]),
                    message_count=int(meta["message_count"]),
                    char_count=int(meta["char_count"]),
                    text_checksum=str(meta["text_checksum"]),
                    body_text=str(meta["body_text"]),
                )
            )

    meta_rows = conn.execute(
        """
        SELECT granularity, backend, model_name, model_revision, dimensions,
               distance_metric, normalization_mode, chunking_config_json,
               sqlite_vec_version, extension_path, created_at, status,
               message_count, chunk_count, last_error
        FROM embedding_index_metadata
        WHERE dataset_id = ? AND granularity IN ('message', 'chunk') AND status = 'ready'
        """,
        (dataset_id,),
    ).fetchall()
    for row in meta_rows:
        snapshot.metadata.append(
            EmbeddingMetadataSnapshot(
                granularity=str(row["granularity"]),
                backend=str(row["backend"]),
                model_name=str(row["model_name"]),
                model_revision=str(row["model_revision"] or ""),
                dimensions=int(row["dimensions"]) if row["dimensions"] is not None else None,
                distance_metric=str(row["distance_metric"] or "cosine"),
                normalization_mode=str(row["normalization_mode"] or ""),
                chunking_config_json=str(row["chunking_config_json"] or "{}"),
                sqlite_vec_version=str(row["sqlite_vec_version"] or ""),
                extension_path=str(row["extension_path"] or ""),
                created_at=str(row["created_at"]),
                status=str(row["status"]),
                message_count=int(row["message_count"] or 0),
                chunk_count=int(row["chunk_count"] or 0),
                last_error=str(row["last_error"] or ""),
            )
        )

    if not snapshot.messages and not snapshot.chunks:
        return None
    return snapshot


def restore_dataset_embeddings(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    *,
    dataset_id: int,
    snapshot: DatasetEmbeddingSnapshot,
) -> EmbeddingRestoreResult:
    from message_evidence_workstation.embeddings.sqlite_vec_backend import (
        CHUNK_VEC_TABLE,
        MESSAGE_VEC_TABLE,
        ensure_chunk_metadata_schema,
        ensure_chunk_vec_table,
        ensure_message_vec_table,
        load_sqlite_vec,
    )

    if snapshot.dimensions is None:
        return EmbeddingRestoreResult(0, 0, len(snapshot.messages), len(snapshot.chunks))

    valid_messages = {
        str(row["message_id"]): row
        for row in conn.execute(
            """
            SELECT message_id, source_thread_id
            FROM message
            WHERE dataset_id = ?
            """,
            (dataset_id,),
        ).fetchall()
    }

    load_sqlite_vec(conn)
    ensure_message_vec_table(conn, snapshot.dimensions)
    ensure_chunk_metadata_schema(conn)
    ensure_chunk_vec_table(conn, snapshot.dimensions)

    message_payload: list[tuple[bytes, str, int, str]] = []
    skipped_messages = 0
    for item in snapshot.messages:
        row = valid_messages.get(item.message_id)
        if row is None or str(row["source_thread_id"]) != item.source_thread_id:
            skipped_messages += 1
            continue
        message_payload.append(
            (item.embedding_blob, item.message_id, dataset_id, item.source_thread_id)
        )
    if message_payload:
        conn.executemany(
            f"""
            INSERT INTO {MESSAGE_VEC_TABLE} (
                embedding, message_id, dataset_id, source_thread_id
            ) VALUES (?, ?, ?, ?)
            """,
            message_payload,
        )

    restored_chunks = 0
    skipped_chunks = 0
    for item in snapshot.chunks:
        if item.start_message_id not in valid_messages or item.end_message_id not in valid_messages:
            skipped_chunks += 1
            continue
        cursor = conn.execute(
            """
            INSERT INTO message_chunk (
                dataset_id, source_thread_id, start_message_id, end_message_id,
                message_count, char_count, text_checksum, body_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                dataset_id,
                item.source_thread_id,
                item.start_message_id,
                item.end_message_id,
                item.message_count,
                item.char_count,
                item.text_checksum,
                item.body_text,
            ),
        )
        chunk_id = int(cursor.lastrowid)
        conn.execute(
            f"""
            INSERT INTO {CHUNK_VEC_TABLE} (
                embedding, chunk_id, dataset_id, source_thread_id
            ) VALUES (?, ?, ?, ?)
            """,
            (item.embedding_blob, chunk_id, dataset_id, item.source_thread_id),
        )
        restored_chunks += 1

    for meta in snapshot.metadata:
        if meta.granularity == "message" and not message_payload:
            continue
        if meta.granularity == "chunk" and restored_chunks <= 0:
            continue
        conn.execute(
            """
            INSERT INTO embedding_index_metadata (
                dataset_id, granularity, backend, model_name, model_revision, dimensions,
                distance_metric, normalization_mode, chunking_config_json, sqlite_vec_version,
                extension_path, created_at, status, message_count, chunk_count, last_error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                dataset_id,
                meta.granularity,
                meta.backend,
                meta.model_name,
                meta.model_revision,
                meta.dimensions,
                meta.distance_metric,
                meta.normalization_mode,
                meta.chunking_config_json,
                meta.sqlite_vec_version,
                meta.extension_path,
                meta.created_at,
                meta.status,
                len(message_payload) if meta.granularity == "message" else meta.message_count,
                restored_chunks if meta.granularity == "chunk" else meta.chunk_count,
                meta.last_error,
            ),
        )

    conn.commit()
    result = EmbeddingRestoreResult(
        restored_messages=len(message_payload),
        restored_chunks=restored_chunks,
        skipped_messages=skipped_messages,
        skipped_chunks=skipped_chunks,
    )
    logger.info(
        component="embeddings.dataset_embedding_cache",
        operation="restore_complete",
        message=(
            f"Restored embeddings after dataset reload: "
            f"{result.restored_messages} messages, {result.restored_chunks} chunks"
        ),
        details={
            "restored_messages": result.restored_messages,
            "restored_chunks": result.restored_chunks,
            "skipped_messages": result.skipped_messages,
            "skipped_chunks": result.skipped_chunks,
        },
        dataset_id=dataset_id,
    )
    return result
