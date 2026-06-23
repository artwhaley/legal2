"""Assistive retrieval for session-coverage answering."""

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
from message_evidence_workstation.search.session_map import TranscriptSession, load_thread_messages
from message_evidence_workstation.search.tool_runner import ToolRunnerDeps, _fts_to_hits

SESSION_CLASS_NOT_RELEVANT = "not_relevant"
SESSION_CLASS_POSSIBLY_RELEVANT = "possibly_relevant"


def session_id_for_message(
    conn: sqlite3.Connection,
    dataset_id: int,
    sessions: list[TranscriptSession],
    message_id: str,
) -> str | None:
    row = conn.execute(
        """
        SELECT source_thread_id
        FROM message
        WHERE dataset_id = ? AND message_id = ?
        """,
        (dataset_id, message_id),
    ).fetchone()
    if row is None:
        return None
    thread_id = str(row["source_thread_id"])
    ordered_ids = [
        message.message_id
        for message in load_thread_messages(conn, dataset_id, thread_id)
    ]
    if message_id not in ordered_ids:
        return None
    message_index = ordered_ids.index(message_id)
    for session in sessions:
        if session.source_thread_id != thread_id:
            continue
        if session.start_message_id not in ordered_ids or session.end_message_id not in ordered_ids:
            continue
        start_index = ordered_ids.index(session.start_message_id)
        end_index = ordered_ids.index(session.end_message_id)
        if start_index <= message_index <= end_index:
            return session.session_id
    return None


def collect_retrieval_assists(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    *,
    dataset_id: int,
    user_query: str,
    sessions: list[TranscriptSession],
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
        session_id = session_id_for_message(conn, dataset_id, sessions, hit.message_id)
        if session_id is None:
            continue
        key = (session_id, hit.message_id)
        if key in seen:
            continue
        seen.add(key)
        assists.append(
            {
                "session_id": session_id,
                "message_id": hit.message_id,
                "source_thread_id": hit.source_thread_id,
                "retrieval_method": hit.retrieval_method,
                "snippet": (hit.snippet or hit.body)[:200],
            }
        )
    logger.info(
        component="search.retrieval_assist",
        operation="assists_collected",
        message="Collected assistive retrieval hits for session coverage",
        details={"assist_count": len(assists)},
        dataset_id=dataset_id,
    )
    return assists


def promote_sessions_from_retrieval_assists(
    classifications: dict[str, str],
    assists: list[dict[str, Any]],
    *,
    inspected_session_ids: set[str],
) -> tuple[dict[str, str], list[str]]:
    notes: list[str] = []
    updated = dict(classifications)
    for assist in assists:
        session_id = str(assist.get("session_id", "")).strip()
        if not session_id or session_id in inspected_session_ids:
            continue
        if updated.get(session_id) == SESSION_CLASS_NOT_RELEVANT:
            updated[session_id] = SESSION_CLASS_POSSIBLY_RELEVANT
            notes.append(
                f"Retrieval assist promoted session {session_id} to possibly_relevant "
                f"via {assist.get('message_id')} ({assist.get('retrieval_method')})."
            )
    return updated, notes
