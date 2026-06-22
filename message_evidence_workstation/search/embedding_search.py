"""Embedding vector search helpers."""

from __future__ import annotations

import sqlite3

from message_evidence_workstation.embeddings.adapters import EmbeddingAdapter
from message_evidence_workstation.embeddings.index_jobs import get_ready_index
from message_evidence_workstation.embeddings.sqlite_vec_backend import (
    search_chunk_vectors,
    search_message_vectors,
)
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.search.result_models import SearchHit


class EmbeddingIndexNotReadyError(RuntimeError):
    def __init__(self, granularity: str, model_name: str, reason: str):
        super().__init__(reason)
        self.granularity = granularity
        self.model_name = model_name


def _require_ready_index(
    conn: sqlite3.Connection,
    dataset_id: int,
    granularity: str,
    model_name: str,
) -> sqlite3.Row:
    row = get_ready_index(conn, dataset_id, granularity, model_name)
    if row is None:
        stale = conn.execute(
            """
            SELECT status, last_error FROM embedding_index_metadata
            WHERE dataset_id = ? AND granularity = ? AND model_name = ?
            ORDER BY embedding_index_id DESC LIMIT 1
            """,
            (dataset_id, granularity, model_name),
        ).fetchone()
        if stale:
            raise EmbeddingIndexNotReadyError(
                granularity,
                model_name,
                f"{granularity} embedding index is {stale['status']}: {stale['last_error']}",
            )
        raise EmbeddingIndexNotReadyError(
            granularity,
            model_name,
            f"No ready {granularity} embedding index for model '{model_name}'. Build it in Setup / Settings.",
        )
    return row


def search_message_embeddings(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    *,
    dataset_id: int,
    query: str,
    model_name: str,
    adapter: EmbeddingAdapter,
    top_k: int = 20,
) -> list[SearchHit]:
    index = _require_ready_index(conn, dataset_id, "message", model_name)
    if index["dimensions"] is None:
        raise EmbeddingIndexNotReadyError("message", model_name, "Message index dimensions missing")
    vectors = adapter.embed_texts([query])
    raw_hits = search_message_vectors(
        conn,
        logger,
        dataset_id=dataset_id,
        query_vector=vectors[0],
        model_name=model_name,
        top_k=top_k,
    )
    hits: list[SearchHit] = []
    for raw in raw_hits:
        row = conn.execute(
            """
            SELECT sender_display, timestamp, body
            FROM message WHERE dataset_id = ? AND message_id = ?
            """,
            (dataset_id, raw.message_id),
        ).fetchone()
        body = row["body"] if row else ""
        hits.append(
            SearchHit(
                message_id=raw.message_id,
                source_thread_id=raw.source_thread_id,
                match_type="message_embedding",
                retrieval_method="message_embedding",
                query_text=query,
                distance=raw.distance,
                rank=raw.rank,
                sender_display=row["sender_display"] if row else "",
                timestamp=row["timestamp"] if row else "",
                body=body,
                snippet=body[:160],
            )
        )
    return hits


def search_chunk_embeddings(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    *,
    dataset_id: int,
    query: str,
    model_name: str,
    adapter: EmbeddingAdapter,
    top_k: int = 20,
) -> list[SearchHit]:
    _require_ready_index(conn, dataset_id, "chunk", model_name)
    vectors = adapter.embed_texts([query])
    raw_hits = search_chunk_vectors(
        conn,
        logger,
        dataset_id=dataset_id,
        query_vector=vectors[0],
        model_name=model_name,
        top_k=top_k,
    )
    hits: list[SearchHit] = []
    for raw in raw_hits:
        row = conn.execute(
            """
            SELECT sender_display, timestamp, body
            FROM message WHERE dataset_id = ? AND message_id = ?
            """,
            (dataset_id, raw.message_id),
        ).fetchone()
        body = row["body"] if row else ""
        snippet = body[:160]
        if raw.start_message_id and raw.end_message_id and raw.start_message_id != raw.end_message_id:
            snippet = f"chunk {raw.start_message_id}..{raw.end_message_id}: {snippet}"
        hits.append(
            SearchHit(
                message_id=raw.message_id,
                source_thread_id=raw.source_thread_id,
                match_type="chunk_embedding",
                retrieval_method="chunk_embedding",
                query_text=query,
                distance=raw.distance,
                rank=raw.rank,
                sender_display=row["sender_display"] if row else "",
                timestamp=row["timestamp"] if row else "",
                body=body,
                snippet=snippet,
                chunk_id=raw.chunk_id,
            )
        )
    return hits
