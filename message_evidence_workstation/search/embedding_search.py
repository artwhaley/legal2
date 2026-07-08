"""Embedding vector search helpers.

Embedding hits are top-K by vector similarity (selectivity-controlled ranking budget),
not a completeness claim over all semantically related messages.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from message_evidence_workstation.embeddings.adapters import EmbeddingAdapter
from message_evidence_workstation.embeddings.index_jobs import get_ready_index
from message_evidence_workstation.embeddings.sqlite_vec_backend import (
    VectorSearchHit,
    search_chunk_vectors,
    search_message_vectors,
)
from message_evidence_workstation.db.repositories import fetch_messages_by_ids
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.search.date_scope import MessageDateScope
from message_evidence_workstation.search.result_models import SearchHit


class EmbeddingIndexNotReadyError(RuntimeError):
    def __init__(self, granularity: str, model_name: str, reason: str):
        super().__init__(reason)
        self.granularity = granularity
        self.model_name = model_name


@dataclass(frozen=True, slots=True)
class EmbeddingSelectivity:
    top_k: int
    distance_multiplier: float | None
    distance_delta: float | None


EMBEDDING_SELECTIVITY: dict[str, EmbeddingSelectivity] = {
    "broad": EmbeddingSelectivity(top_k=40, distance_multiplier=None, distance_delta=None),
    "balanced": EmbeddingSelectivity(top_k=20, distance_multiplier=1.75, distance_delta=0.15),
    "narrow": EmbeddingSelectivity(top_k=10, distance_multiplier=1.35, distance_delta=0.08),
}


def resolve_embedding_selectivity(selectivity: str) -> EmbeddingSelectivity:
    return EMBEDDING_SELECTIVITY.get(selectivity, EMBEDDING_SELECTIVITY["balanced"])


def filter_vector_hits_by_selectivity(
    hits: list[VectorSearchHit],
    selectivity: str,
) -> list[VectorSearchHit]:
    resolved = resolve_embedding_selectivity(selectivity)
    limited = hits[: resolved.top_k]
    if not limited or resolved.distance_multiplier is None or resolved.distance_delta is None:
        return limited
    best_distance = max(0.0, limited[0].distance)
    max_distance = (best_distance * resolved.distance_multiplier) + resolved.distance_delta
    return [hit for hit in limited if hit.distance <= max_distance]


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
    top_k: int | None = None,
    selectivity: str = "balanced",
    date_scope: MessageDateScope | None = None,
) -> list[SearchHit]:
    index = _require_ready_index(conn, dataset_id, "message", model_name)
    if index["dimensions"] is None:
        raise EmbeddingIndexNotReadyError("message", model_name, "Message index dimensions missing")
    vectors = adapter.embed_texts([query])
    resolved_selectivity = resolve_embedding_selectivity(selectivity)
    raw_hits = search_message_vectors(
        conn,
        logger,
        dataset_id=dataset_id,
        query_vector=vectors[0],
        model_name=model_name,
        top_k=top_k if top_k is not None else resolved_selectivity.top_k,
        date_scope=date_scope,
    )
    raw_hits = filter_vector_hits_by_selectivity(raw_hits, selectivity)
    messages_by_id = fetch_messages_by_ids(
        conn,
        dataset_id,
        [raw.message_id for raw in raw_hits],
    )
    hits: list[SearchHit] = []
    for raw in raw_hits:
        message = messages_by_id.get(raw.message_id)
        body = message.body if message else ""
        hits.append(
            SearchHit(
                message_id=raw.message_id,
                source_thread_id=raw.source_thread_id,
                match_type="message_embedding",
                retrieval_method="message_embedding",
                query_text=query,
                distance=raw.distance,
                rank=raw.rank,
                sender_display=message.sender_display if message else "",
                timestamp=message.timestamp if message else "",
                body=body,
                snippet=body[:160],
                thread_ordinal=message.thread_ordinal if message else None,
                sort_index=message.sort_index if message else None,
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
    top_k: int | None = None,
    selectivity: str = "balanced",
    date_scope: MessageDateScope | None = None,
) -> list[SearchHit]:
    _require_ready_index(conn, dataset_id, "chunk", model_name)
    vectors = adapter.embed_texts([query])
    resolved_selectivity = resolve_embedding_selectivity(selectivity)
    raw_hits = search_chunk_vectors(
        conn,
        logger,
        dataset_id=dataset_id,
        query_vector=vectors[0],
        model_name=model_name,
        top_k=top_k if top_k is not None else resolved_selectivity.top_k,
        date_scope=date_scope,
    )
    raw_hits = filter_vector_hits_by_selectivity(raw_hits, selectivity)
    messages_by_id = fetch_messages_by_ids(
        conn,
        dataset_id,
        [raw.message_id for raw in raw_hits],
    )
    hits: list[SearchHit] = []
    for raw in raw_hits:
        message = messages_by_id.get(raw.message_id)
        body = message.body if message else ""
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
                sender_display=message.sender_display if message else "",
                timestamp=message.timestamp if message else "",
                body=body,
                snippet=snippet,
                chunk_id=raw.chunk_id,
                thread_ordinal=message.thread_ordinal if message else None,
                sort_index=message.sort_index if message else None,
            )
        )
    return hits
