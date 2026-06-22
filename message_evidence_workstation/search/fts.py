"""SQLite FTS5 message search."""

from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from message_evidence_workstation.db.fts_schema import MESSAGE_FTS_DDL

if TYPE_CHECKING:
    from message_evidence_workstation.logging_ui.process_log import ProcessLogger

TOKEN_SPLIT_RE = re.compile(r"\s+")
# Strip punctuation that breaks FTS5 prefix/exact queries (?, !, etc.)
FTS_TOKEN_EDGE_RE = re.compile(r"^[^\w']+|[^\w']+$", re.UNICODE)


@dataclass(slots=True)
class FtsHit:
    message_id: str
    source_thread_id: str
    match_type: str
    rank: float


def ensure_fts_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(MESSAGE_FTS_DDL)


def clear_fts_for_dataset(conn: sqlite3.Connection, dataset_id: int) -> None:
    conn.execute("DELETE FROM message_fts WHERE dataset_id = ?", (dataset_id,))


def rebuild_message_fts(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    dataset_id: int,
) -> int:
    ensure_fts_schema(conn)
    logger.info(
        component="search.fts",
        operation="rebuild_start",
        message="Rebuilding message FTS index",
        details={"dataset_id": dataset_id},
        dataset_id=dataset_id,
    )
    started = time.perf_counter()
    clear_fts_for_dataset(conn, dataset_id)
    rows = conn.execute(
        """
        SELECT message_id, dataset_id, source_thread_id, body, body_normalized, sender_display
        FROM message
        WHERE dataset_id = ?
        ORDER BY source_thread_id, timestamp, sort_index
        """,
        (dataset_id,),
    ).fetchall()
    for row in rows:
        conn.execute(
            """
            INSERT INTO message_fts (
                message_id, dataset_id, source_thread_id, body, body_normalized, sender_display
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                row["message_id"],
                row["dataset_id"],
                row["source_thread_id"],
                row["body"],
                row["body_normalized"],
                row["sender_display"],
            ),
        )
    conn.commit()
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        component="search.fts",
        operation="rebuild_complete",
        message="Message FTS index rebuild completed",
        details={
            "dataset_id": dataset_id,
            "row_count": len(rows),
            "elapsed_ms": elapsed_ms,
        },
        dataset_id=dataset_id,
    )
    return len(rows)


def escape_fts_phrase(query: str) -> str:
    return '"' + query.replace('"', '""') + '"'


def normalize_fts_token(token: str) -> str:
    """Drop leading/trailing punctuation so tokens like 'allergies?' search as 'allergies'."""
    cleaned = FTS_TOKEN_EDGE_RE.sub("", token.strip())
    return cleaned


def tokenize_query(query: str) -> list[str]:
    tokens: list[str] = []
    for raw in TOKEN_SPLIT_RE.split(query.strip()):
        if not raw:
            continue
        normalized = normalize_fts_token(raw)
        if normalized:
            tokens.append(normalized)
    return tokens


def build_prefix_query(query: str) -> str:
    tokens = tokenize_query(query)
    if not tokens:
        return ""
    escaped_tokens = []
    for token in tokens:
        cleaned = re.sub(r'["*]', "", token)
        if cleaned:
            escaped_tokens.append(f"{cleaned}*")
    return " ".join(escaped_tokens)


def compound_token_variants(token: str) -> list[str]:
    """Generate spacing/punctuation variants for compound terms (epi-pen, epi pen, epipen)."""
    cleaned = token.strip()
    if not cleaned:
        return []
    variants: list[str] = [cleaned]
    collapsed = re.sub(r"[\s\-_]+", "", cleaned)
    if collapsed and collapsed.casefold() != cleaned.casefold():
        variants.append(collapsed)
    spaced = re.sub(r"[\s\-_]+", " ", cleaned).strip()
    if spaced and spaced.casefold() != cleaned.casefold():
        variants.append(spaced)
    hyphenated = re.sub(r"\s+", "-", cleaned.strip())
    if hyphenated and hyphenated.casefold() != cleaned.casefold():
        variants.append(hyphenated)
    seen: set[str] = set()
    ordered: list[str] = []
    for variant in variants:
        key = variant.casefold()
        if key not in seen:
            seen.add(key)
            ordered.append(variant)
    return ordered


def token_search_variants(token: str) -> list[str]:
    """Generate spelling variants so FTS does not miss obvious inflections."""
    cleaned = token.strip()
    if not cleaned:
        return []
    variants: list[str] = [cleaned]
    lower = cleaned.casefold()
    if lower.endswith("ies") and len(lower) > 4:
        variants.append(cleaned[:-3] + "y")
    elif lower.endswith("es") and len(lower) > 3:
        variants.append(cleaned[:-2])
        variants.append(cleaned[:-1])
    elif lower.endswith("s") and len(lower) > 3:
        variants.append(cleaned[:-1])
    if len(cleaned) >= 5:
        variants.append(cleaned[:5])
    for compound_variant in compound_token_variants(cleaned):
        variants.append(compound_variant)
    seen: set[str] = set()
    ordered: list[str] = []
    for variant in variants:
        key = variant.casefold()
        if key not in seen:
            seen.add(key)
            ordered.append(variant)
    return ordered


def _search_token_variants(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    dataset_id: int,
    token: str,
) -> dict[str, list[FtsHit]]:
    exact_hits: list[FtsHit] = []
    partial_hits: list[FtsHit] = []
    seen_exact: set[str] = set()
    seen_partial: set[str] = set()
    for variant in token_search_variants(token):
        for hit in search_exact(conn, logger, dataset_id, variant):
            if hit.message_id not in seen_exact:
                seen_exact.add(hit.message_id)
                exact_hits.append(hit)
        for hit in search_partial(conn, logger, dataset_id, variant):
            if hit.message_id not in seen_partial:
                seen_partial.add(hit.message_id)
                partial_hits.append(hit)
    return {"exact": exact_hits, "partial": partial_hits}


def _run_fts_query(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    *,
    dataset_id: int,
    raw_query: str,
    fts_query: str,
    match_type: str,
) -> list[FtsHit]:
    if not fts_query.strip():
        return []
    started = time.perf_counter()
    try:
        rows = conn.execute(
            """
            SELECT message_id, source_thread_id, bm25(message_fts) AS rank
            FROM message_fts
            WHERE dataset_id = ? AND message_fts MATCH ?
            ORDER BY rank
            """,
            (dataset_id, fts_query),
        ).fetchall()
    except sqlite3.OperationalError as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.error(
            component="search.fts",
            operation="query_failed",
            message="FTS query failed",
            details={
                "dataset_id": dataset_id,
                "raw_query": raw_query,
                "escaped_query": fts_query,
                "match_type": match_type,
                "elapsed_ms": elapsed_ms,
            },
            exc=exc,
            dataset_id=dataset_id,
        )
        if "syntax error" in str(exc).lower() or "fts5" in str(exc).lower():
            return []
        raise
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    hits = [
        FtsHit(
            message_id=row["message_id"],
            source_thread_id=row["source_thread_id"],
            match_type=match_type,
            rank=float(row["rank"]),
        )
        for row in rows
    ]
    logger.info(
        component="search.fts",
        operation="query_complete",
        message="FTS query completed",
        details={
            "dataset_id": dataset_id,
            "raw_query": raw_query,
            "escaped_query": fts_query,
            "match_type": match_type,
            "result_count": len(hits),
            "elapsed_ms": elapsed_ms,
            "message_ids": [hit.message_id for hit in hits[:20]],
        },
        dataset_id=dataset_id,
    )
    return hits


def search_exact(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    dataset_id: int,
    query: str,
) -> list[FtsHit]:
    if not query.strip():
        return []
    fts_query = escape_fts_phrase(query.strip())
    return _run_fts_query(
        conn,
        logger,
        dataset_id=dataset_id,
        raw_query=query,
        fts_query=fts_query,
        match_type="exact",
    )


def search_partial(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    dataset_id: int,
    query: str,
) -> list[FtsHit]:
    if not query.strip():
        return []
    fts_query = build_prefix_query(query)
    if not fts_query:
        logger.warning(
            component="search.fts",
            operation="query_empty_after_tokenize",
            message="Partial FTS query produced no tokens",
            details={"raw_query": query},
            dataset_id=dataset_id,
        )
        return []
    return _run_fts_query(
        conn,
        logger,
        dataset_id=dataset_id,
        raw_query=query,
        fts_query=fts_query,
        match_type="partial",
    )


def search_messages(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    dataset_id: int,
    query: str,
) -> dict[str, Any]:
    tokens = tokenize_query(query)
    if len(tokens) <= 1:
        if not tokens:
            return {"exact": [], "partial": []}
        return _search_token_variants(conn, logger, dataset_id, tokens[0])

    exact_hits: list[FtsHit] = []
    partial_hits: list[FtsHit] = []
    seen_exact: set[str] = set()
    seen_partial: set[str] = set()
    for token in tokens:
        token_results = _search_token_variants(conn, logger, dataset_id, token)
        for hit in token_results["exact"]:
            if hit.message_id not in seen_exact:
                seen_exact.add(hit.message_id)
                exact_hits.append(hit)
        for hit in token_results["partial"]:
            if hit.message_id not in seen_partial:
                seen_partial.add(hit.message_id)
                partial_hits.append(hit)
    return {"exact": exact_hits, "partial": partial_hits}
