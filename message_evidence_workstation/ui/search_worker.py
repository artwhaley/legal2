"""Background search execution off the UI thread."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QTimer

from message_evidence_workstation.config.settings import load_settings
from message_evidence_workstation.db import repositories
from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.llm.router import ModelRouter
from message_evidence_workstation.llm.types import UserFacingModelRole
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.search import fts
from message_evidence_workstation.search.embedding_search import EmbeddingIndexNotReadyError
from message_evidence_workstation.search.fusion import fuse_hits
from message_evidence_workstation.search.grouping import group_hits
from message_evidence_workstation.search.keyword_expansion import expand_keywords
from message_evidence_workstation.search.result_models import GroupedSearchResult, SearchHit
from message_evidence_workstation.search.search_modes import SearchMode


@dataclass(slots=True)
class SearchJobSpec:
    db_path: Path
    dataset_id: int
    mode: SearchMode
    query: str
    page_size: int
    offset: int = 0
    keyword_terms: list[str] = field(default_factory=list)
    expand_keywords: bool = False
    embedding_model: str = ""
    embedding_selectivity: str = "balanced"
    generation: int = 0


@dataclass(slots=True)
class SearchJobResult:
    generation: int
    mode: SearchMode
    query: str
    groups: list[GroupedSearchResult]
    total_count: int | None
    page_size: int | None
    offset: int
    has_more: bool
    next_offset: int | None
    elapsed_ms: int
    cancelled: bool = False
    keyword_terms: list[str] = field(default_factory=list)
    status_message: str = ""


class SearchCancellationToken:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cancelled = False

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True

    def is_cancelled(self) -> bool:
        with self._lock:
            return self._cancelled


def _hits_from_fts_page(
    conn,
    logger: ProcessLogger,
    dataset_id: int,
    query: str,
    fts_hits: list[fts.FtsHit],
) -> list[SearchHit]:
    messages_by_id = repositories.fetch_messages_by_ids(
        conn,
        dataset_id,
        [hit.message_id for hit in fts_hits],
    )
    hits: list[SearchHit] = []
    for fts_hit in fts_hits:
        message = messages_by_id.get(fts_hit.message_id)
        body = message.body if message else ""
        retrieval_method = {
            "exact": "fts_exact",
            "partial": "fts_partial",
            "fuzzy": "spellfix_fuzzy",
            "keyword": "keyword_expansion",
        }.get(fts_hit.match_type, "fts_exact")
        hits.append(
            SearchHit(
                message_id=fts_hit.message_id,
                source_thread_id=fts_hit.source_thread_id,
                match_type=fts_hit.match_type,
                retrieval_method=retrieval_method,
                query_text=query,
                matched_term=query,
                score=fts_hit.rank,
                sender_display=message.sender_display if message else "",
                timestamp=message.timestamp if message else "",
                body=body,
                snippet=body[:160],
                thread_ordinal=message.thread_ordinal if message else None,
                sort_index=message.sort_index if message else None,
            )
        )
    return fuse_hits(hits)


def run_search_job(spec: SearchJobSpec, cancel_token: SearchCancellationToken | None = None) -> SearchJobResult:
    started = time.perf_counter()
    conn = connect(spec.db_path)
    try:
        logger = ProcessLogger(conn, dataset_id=spec.dataset_id)
        if cancel_token is not None and cancel_token.is_cancelled():
            return SearchJobResult(
                generation=spec.generation,
                mode=spec.mode,
                query=spec.query,
                groups=[],
                total_count=0,
                page_size=spec.page_size,
                offset=spec.offset,
                has_more=False,
                next_offset=None,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                cancelled=True,
                keyword_terms=list(spec.keyword_terms),
                status_message="Search cancelled.",
            )

        keyword_terms = list(spec.keyword_terms)
        if spec.mode == "expanded_keyword" and spec.expand_keywords and not keyword_terms:
            settings = load_settings()
            router = ModelRouter(settings)
            keyword_terms = expand_keywords(
                conn,
                logger,
                router,
                spec.query,
                dataset_id=spec.dataset_id,
                max_expansion_terms=settings.search.max_expansion_terms,
            )
            if cancel_token is not None and cancel_token.is_cancelled():
                return SearchJobResult(
                    generation=spec.generation,
                    mode=spec.mode,
                    query=spec.query,
                    groups=[],
                    total_count=0,
                    page_size=spec.page_size,
                    offset=spec.offset,
                    has_more=False,
                    next_offset=None,
                    elapsed_ms=int((time.perf_counter() - started) * 1000),
                    cancelled=True,
                    keyword_terms=keyword_terms,
                    status_message="Search cancelled.",
                )

        total_count: int | None = None
        has_more = False
        next_offset: int | None = None
        hits: list[SearchHit] = []

        if spec.mode == "fts5":
            page = fts.search_messages(
                conn,
                logger,
                spec.dataset_id,
                spec.query,
                limit=spec.page_size,
                offset=spec.offset,
            )
            total_count = int(page["total_count"])
            has_more = bool(page["has_more"])
            next_offset = page.get("next_offset")
            hits = _hits_from_fts_page(conn, logger, spec.dataset_id, spec.query, page["hits"])
        elif spec.mode == "expanded_keyword":
            terms = keyword_terms or ([spec.query] if spec.query else [])
            page = fts.search_keyword_terms(
                conn,
                logger,
                spec.dataset_id,
                terms,
                limit=spec.page_size,
                offset=spec.offset,
            )
            total_count = int(page["total_count"])
            has_more = bool(page["has_more"])
            next_offset = page.get("next_offset")
            hits = _hits_from_fts_page(conn, logger, spec.dataset_id, spec.query, page["hits"])
            for hit in hits:
                if hit.match_type == "keyword":
                    hit.query_text = spec.query
        elif spec.mode == "message_embedding":
            raise ValueError("message_embedding must run through embedding worker")
        elif spec.mode == "chunk_embedding":
            raise ValueError("chunk_embedding must run through embedding worker")
        else:
            raise ValueError(f"Unsupported search mode: {spec.mode}")

        if cancel_token is not None and cancel_token.is_cancelled():
            return SearchJobResult(
                generation=spec.generation,
                mode=spec.mode,
                query=spec.query,
                groups=[],
                total_count=total_count,
                page_size=spec.page_size,
                offset=spec.offset,
                has_more=has_more,
                next_offset=next_offset,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                cancelled=True,
                keyword_terms=keyword_terms,
                status_message="Search cancelled.",
            )

        groups = group_hits(hits, logger=logger, dataset_id=spec.dataset_id)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        if spec.mode in ("message_embedding", "chunk_embedding"):
            status_message = f"Showing top {len(hits)} by similarity ({elapsed_ms} ms)."
        else:
            status_message = f"{len(groups)} grouped result(s) ({elapsed_ms} ms)."
        return SearchJobResult(
            generation=spec.generation,
            mode=spec.mode,
            query=spec.query,
            groups=groups,
            total_count=total_count,
            page_size=spec.page_size,
            offset=spec.offset,
            has_more=has_more,
            next_offset=next_offset,
            elapsed_ms=elapsed_ms,
            keyword_terms=keyword_terms,
            status_message=status_message,
        )
    finally:
        conn.close()


def run_search_job_background(
    parent: QObject,
    spec: SearchJobSpec,
    cancel_token: SearchCancellationToken,
    *,
    on_success: Callable[[SearchJobResult], None],
    on_error: Callable[[BaseException], None],
) -> threading.Thread:
    from message_evidence_workstation.ui.background_tasks import run_background

    return run_background(
        parent,
        lambda: run_search_job(spec, cancel_token),
        on_success=on_success,
        on_error=on_error,
    )
