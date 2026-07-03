"""Assistive retrieval hints for conversational answering."""

from __future__ import annotations

import sqlite3
from typing import Any

from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.search.embedding_search import (
    EmbeddingIndexNotReadyError,
    search_chunk_embeddings,
    search_message_embeddings,
)
from message_evidence_workstation.search.fusion import fuse_hits
from message_evidence_workstation.search.result_models import SearchHit
from message_evidence_workstation.search.tool_runner import ToolRunnerDeps, _fts_to_hits


def collect_retrieval_assists(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    *,
    dataset_id: int,
    user_query: str,
    deps: ToolRunnerDeps | None = None,
) -> list[dict[str, Any]]:
    deps = deps or ToolRunnerDeps()
    hits: list[SearchHit] = list(_fts_to_hits(conn, logger, dataset_id, user_query))
    if deps.embedding_adapter is not None:
        try:
            hits.extend(
                search_message_embeddings(
                    conn,
                    dataset_id,
                    user_query,
                    adapter=deps.embedding_adapter,
                    model_name=deps.embedding_model_name,
                )
            )
            hits.extend(
                search_chunk_embeddings(
                    conn,
                    dataset_id,
                    user_query,
                    adapter=deps.embedding_adapter,
                    model_name=deps.embedding_model_name,
                )
            )
        except EmbeddingIndexNotReadyError:
            logger.info(
                component="search.retrieval_assist",
                operation="embedding_assist_skipped",
                message="Embedding index not ready; FTS assists only",
                dataset_id=dataset_id,
            )
    fused = fuse_hits(hits)[:40]
    assists: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for hit in fused:
        key = (hit.source_thread_id, hit.message_id)
        if key in seen:
            continue
        seen.add(key)
        assists.append(
            {
                "message_id": hit.message_id,
                "source_thread_id": hit.source_thread_id,
                "retrieval_method": hit.retrieval_method,
                "snippet": (hit.snippet or hit.body)[:200],
            }
        )
    logger.info(
        component="search.retrieval_assist",
        operation="assists_collected",
        message="Collected assistive retrieval hits for conversational answer planning",
        details={"assist_count": len(assists)},
        dataset_id=dataset_id,
    )
    return assists
