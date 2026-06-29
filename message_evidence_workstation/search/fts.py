"""SQLite FTS5 message search."""

from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

from message_evidence_workstation.db.fts_schema import MESSAGE_FTS_DDL, MESSAGE_FTS_TOKENIZER
if TYPE_CHECKING:
    from message_evidence_workstation.logging_ui.process_log import ProcessLogger

TOKEN_SPLIT_RE = re.compile(r"\s+")
# Strip punctuation that breaks FTS5 prefix/exact queries (?, !, etc.)
FTS_TOKEN_EDGE_RE = re.compile(r"^[^\w']+|[^\w']+$", re.UNICODE)
FTS_REBUILD_BATCH_SIZE = 1000
ORDER_KEY_CHUNK_SIZE = 500


@dataclass(slots=True)
class FtsHit:
    message_id: str
    source_thread_id: str
    match_type: str
    rank: float


@dataclass(slots=True)
class FtsSearchPage:
    """Paginated FTS results.

    Future keyset cursor fields (if offset pagination is too slow on scale fixtures):
    after_rank, after_timestamp, after_sort_index, after_message_id.
    """

    hits: list[FtsHit]
    total_count: int
    has_more: bool
    next_offset: int | None


MATCH_TYPE_ORDER = {"exact": 0, "partial": 1, "fuzzy": 2}


def ensure_fts_schema(conn: sqlite3.Connection) -> bool:
    existing = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'message_fts'"
    ).fetchone()
    if existing is not None:
        sql = str(existing["sql"] if isinstance(existing, sqlite3.Row) else existing[0])
        if f"tokenize='{MESSAGE_FTS_TOKENIZER}'" not in sql.replace(" ", ""):
            conn.execute("DROP TABLE message_fts")
            conn.executescript(MESSAGE_FTS_DDL)
            return True
    conn.executescript(MESSAGE_FTS_DDL)
    return False


def clear_fts_for_dataset(conn: sqlite3.Connection, dataset_id: int) -> None:
    conn.execute("DELETE FROM message_fts WHERE dataset_id = ?", (dataset_id,))


def rebuild_message_fts(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    dataset_id: int,
    *,
    progress_callback: Callable[[str, int, int], None] | None = None,
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
    row_count = 0
    last_thread_id = ""
    last_timestamp = ""
    last_sort_index = -1
    last_message_id = ""
    while True:
        rows = conn.execute(
            """
            SELECT message_id, dataset_id, source_thread_id, body, body_normalized,
                   sender_display, timestamp, sort_index
            FROM message
            WHERE dataset_id = ?
              AND (
                    source_thread_id > ?
                    OR (
                        source_thread_id = ?
                        AND (
                            timestamp > ?
                            OR (timestamp = ? AND sort_index > ?)
                            OR (timestamp = ? AND sort_index = ? AND message_id > ?)
                        )
                    )
                  )
            ORDER BY source_thread_id, timestamp, sort_index, message_id
            LIMIT ?
            """,
            (
                dataset_id,
                last_thread_id,
                last_thread_id,
                last_timestamp,
                last_timestamp,
                last_sort_index,
                last_timestamp,
                last_sort_index,
                last_message_id,
                FTS_REBUILD_BATCH_SIZE,
            ),
        ).fetchall()
        if not rows:
            break
        conn.executemany(
            """
            INSERT INTO message_fts (
                message_id, dataset_id, source_thread_id, body, body_normalized, sender_display
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    row["message_id"],
                    row["dataset_id"],
                    row["source_thread_id"],
                    row["body"],
                    row["body_normalized"],
                    row["sender_display"],
                )
                for row in rows
            ],
        )
        conn.commit()
        row_count += len(rows)
        last = rows[-1]
        last_thread_id = str(last["source_thread_id"])
        last_timestamp = str(last["timestamp"])
        last_sort_index = int(last["sort_index"])
        last_message_id = str(last["message_id"])
        if progress_callback is not None:
            progress_callback("fts", row_count, row_count)
        if len(rows) < FTS_REBUILD_BATCH_SIZE:
            break
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        component="search.fts",
        operation="rebuild_complete",
        message="Message FTS index rebuild completed",
        details={
            "dataset_id": dataset_id,
            "row_count": row_count,
            "elapsed_ms": elapsed_ms,
        },
        dataset_id=dataset_id,
    )
    return row_count


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
        parts = [part for part in re.split(r"[^\w']+", cleaned, flags=re.UNICODE) if part]
        if parts:
            escaped_tokens.extend(parts)
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
    fuzzy_hits: list[FtsHit] = []
    seen_exact: set[str] = set()
    seen_partial: set[str] = set()
    seen_fuzzy: set[str] = set()
    for variant in token_search_variants(token):
        for hit in search_exact(conn, logger, dataset_id, variant):
            if hit.message_id not in seen_exact:
                seen_exact.add(hit.message_id)
                exact_hits.append(hit)
        for hit in search_partial(conn, logger, dataset_id, variant):
            if hit.message_id not in seen_partial:
                seen_partial.add(hit.message_id)
                partial_hits.append(hit)
    from message_evidence_workstation.search.spellfix import expand_fuzzy_terms

    for fuzzy_term in expand_fuzzy_terms(conn, logger, dataset_id, token):
        for hit in search_exact(conn, logger, dataset_id, fuzzy_term):
            if hit.message_id not in seen_exact and hit.message_id not in seen_partial and hit.message_id not in seen_fuzzy:
                seen_fuzzy.add(hit.message_id)
                fuzzy_hits.append(
                    FtsHit(
                        message_id=hit.message_id,
                        source_thread_id=hit.source_thread_id,
                        match_type="fuzzy",
                        rank=hit.rank,
                    )
                )
    return {"exact": exact_hits, "partial": partial_hits, "fuzzy": fuzzy_hits}


def count_fts_matches(
    conn: sqlite3.Connection,
    dataset_id: int,
    fts_query: str,
) -> int:
    """COUNT(*) for a single FTS MATCH clause."""
    if not fts_query.strip():
        return 0
    row = conn.execute(
        """
        SELECT COUNT(*) AS match_count
        FROM message_fts
        WHERE dataset_id = ? AND message_fts MATCH ?
        """,
        (dataset_id, fts_query),
    ).fetchone()
    return int(row["match_count"] if row is not None else 0)


def _run_fts_query(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    *,
    dataset_id: int,
    raw_query: str,
    fts_query: str,
    match_type: str,
    limit: int | None = None,
    offset: int = 0,
) -> list[FtsHit]:
    if not fts_query.strip():
        return []
    started = time.perf_counter()
    pagination_sql = ""
    pagination_params: tuple[int, ...] = ()
    if limit is not None:
        pagination_sql = " LIMIT ? OFFSET ?"
        pagination_params = (limit, offset)
    try:
        rows = conn.execute(
            f"""
            SELECT mf.message_id, mf.source_thread_id, bm25(message_fts) AS rank
            FROM message_fts mf
            JOIN message m
              ON m.message_id = mf.message_id AND m.dataset_id = mf.dataset_id
            WHERE mf.dataset_id = ? AND message_fts MATCH ?
            ORDER BY rank, m.timestamp, m.sort_index, mf.message_id
            {pagination_sql}
            """,
            (dataset_id, fts_query, *pagination_params),
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


def _collect_lane_results(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    dataset_id: int,
    query: str,
) -> dict[str, list[FtsHit]]:
    tokens = tokenize_query(query)
    if not tokens:
        return {"exact": [], "partial": [], "fuzzy": []}
    if len(tokens) == 1:
        return _search_token_variants(conn, logger, dataset_id, tokens[0])

    exact_hits: list[FtsHit] = []
    partial_hits: list[FtsHit] = []
    fuzzy_hits: list[FtsHit] = []
    seen_exact: set[str] = set()
    seen_partial: set[str] = set()
    seen_fuzzy: set[str] = set()
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
        for hit in token_results["fuzzy"]:
            if (
                hit.message_id not in seen_exact
                and hit.message_id not in seen_partial
                and hit.message_id not in seen_fuzzy
            ):
                seen_fuzzy.add(hit.message_id)
                fuzzy_hits.append(hit)
    return {"exact": exact_hits, "partial": partial_hits, "fuzzy": fuzzy_hits}


def _merge_lane_results(lanes: dict[str, list[FtsHit]]) -> list[FtsHit]:
    """Merge exact/partial/fuzzy lanes into one de-duplicated list (best match type wins)."""
    merged: dict[str, FtsHit] = {}
    for hit in lanes["exact"]:
        merged[hit.message_id] = hit
    for hit in lanes["partial"]:
        if hit.message_id not in merged:
            merged[hit.message_id] = hit
    for hit in lanes["fuzzy"]:
        if hit.message_id not in merged:
            merged[hit.message_id] = hit
    return list(merged.values())


def _sort_merged_hits(
    conn: sqlite3.Connection,
    dataset_id: int,
    hits: list[FtsHit],
) -> list[FtsHit]:
    order_keys = _fetch_message_order_keys(conn, dataset_id, [hit.message_id for hit in hits])

    def sort_key(hit: FtsHit) -> tuple[int, float, str, int, str]:
        timestamp, sort_index = order_keys.get(hit.message_id, ("", 0))
        return (
            MATCH_TYPE_ORDER.get(hit.match_type, 99),
            hit.rank,
            timestamp,
            sort_index,
            hit.message_id,
        )

    return sorted(hits, key=sort_key)


def _fetch_message_order_keys(
    conn: sqlite3.Connection,
    dataset_id: int,
    message_ids: list[str],
) -> dict[str, tuple[str, int]]:
    """Fetch only ordering columns for result sorting; do not hydrate bodies."""
    if not message_ids:
        return {}
    unique_ids = list(dict.fromkeys(message_ids))
    result: dict[str, tuple[str, int]] = {}
    for start in range(0, len(unique_ids), ORDER_KEY_CHUNK_SIZE):
        chunk = unique_ids[start : start + ORDER_KEY_CHUNK_SIZE]
        placeholders = ",".join("?" * len(chunk))
        rows = conn.execute(
            f"""
            SELECT message_id, timestamp, sort_index
            FROM message
            WHERE dataset_id = ? AND message_id IN ({placeholders})
            """,
            (dataset_id, *chunk),
        ).fetchall()
        for row in rows:
            result[str(row["message_id"])] = (str(row["timestamp"]), int(row["sort_index"]))
    return result


def _paginate_hits(
    hits: list[FtsHit],
    *,
    limit: int | None,
    offset: int,
) -> FtsSearchPage:
    total_count = len(hits)
    if limit is None:
        return FtsSearchPage(
            hits=hits,
            total_count=total_count,
            has_more=False,
            next_offset=None,
        )
    page_hits = hits[offset : offset + limit]
    next_offset = offset + len(page_hits)
    has_more = next_offset < total_count
    return FtsSearchPage(
        hits=page_hits,
        total_count=total_count,
        has_more=has_more,
        next_offset=next_offset if has_more else None,
    )


@dataclass(slots=True)
class _CandidateSpec:
    fts_query: str
    match_type: str
    match_priority: int


def _candidate_specs_for_query(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    dataset_id: int,
    query: str,
) -> list[_CandidateSpec]:
    from message_evidence_workstation.search.spellfix import expand_fuzzy_terms

    tokens = tokenize_query(query)
    if not tokens:
        return []
    specs: list[_CandidateSpec] = []
    seen_queries: set[tuple[str, str]] = set()

    def add_spec(fts_query: str, match_type: str, match_priority: int) -> None:
        if not fts_query.strip():
            return
        key = (match_type, fts_query)
        if key in seen_queries:
            return
        seen_queries.add(key)
        specs.append(_CandidateSpec(fts_query=fts_query, match_type=match_type, match_priority=match_priority))

    token_list = tokens if len(tokens) > 1 else [tokens[0]]
    for token in token_list:
        for variant in token_search_variants(token):
            add_spec(escape_fts_phrase(variant), "exact", 0)
            prefix = build_prefix_query(variant)
            add_spec(prefix, "partial", 1)
        for fuzzy_term in expand_fuzzy_terms(conn, logger, dataset_id, token):
            add_spec(escape_fts_phrase(fuzzy_term), "fuzzy", 2)
    return specs


def _candidate_specs_for_keyword_terms(terms: list[str]) -> list[_CandidateSpec]:
    specs: list[_CandidateSpec] = []
    seen: set[tuple[str, str]] = set()
    for chip_index, term in enumerate(terms):
        cleaned = term.strip()
        if not cleaned:
            continue
        fts_query = escape_fts_phrase(cleaned)
        key = ("keyword", fts_query)
        if key in seen:
            continue
        seen.add(key)
        specs.append(_CandidateSpec(fts_query=fts_query, match_type="keyword", match_priority=chip_index))
    return specs


def _search_candidates_sql(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    dataset_id: int,
    specs: list[_CandidateSpec],
    *,
    limit: int | None,
    offset: int,
) -> FtsSearchPage:
    if not specs:
        return FtsSearchPage(hits=[], total_count=0, has_more=False, next_offset=None)

    union_parts: list[str] = []
    params: list[Any] = []
    for spec in specs:
        union_parts.append(
            """
            SELECT mf.message_id,
                   mf.source_thread_id,
                   ? AS match_type,
                   ? AS match_priority,
                   bm25(message_fts) AS rank,
                   m.timestamp,
                   m.sort_index
            FROM message_fts mf
            JOIN message m
              ON m.message_id = mf.message_id AND m.dataset_id = mf.dataset_id
            WHERE mf.dataset_id = ? AND message_fts MATCH ?
            """
        )
        params.extend([spec.match_type, spec.match_priority, dataset_id, spec.fts_query])

    base_sql = f"""
        WITH candidates AS (
            {' UNION ALL '.join(union_parts)}
        ),
        deduped AS (
            SELECT message_id,
                   source_thread_id,
                   match_type,
                   match_priority,
                   rank,
                   timestamp,
                   sort_index,
                   ROW_NUMBER() OVER (
                       PARTITION BY message_id
                       ORDER BY match_priority, rank, timestamp, sort_index, message_id
                   ) AS rn
            FROM candidates
        ),
        ordered AS (
            SELECT message_id,
                   source_thread_id,
                   match_type,
                   match_priority,
                   rank,
                   timestamp,
                   sort_index
            FROM deduped
            WHERE rn = 1
        )
    """
    try:
        count_row = conn.execute(
            f"{base_sql} SELECT COUNT(*) AS total_count FROM ordered",
            params,
        ).fetchone()
        total_count = int(count_row["total_count"] if count_row is not None else 0)
        if limit is None:
            rows = conn.execute(
                f"""
                {base_sql}
                SELECT message_id, source_thread_id, match_type, rank
                FROM ordered
                ORDER BY match_priority, rank, timestamp, sort_index, message_id
                """,
                params,
            ).fetchall()
            hits = [
                FtsHit(
                    message_id=str(row["message_id"]),
                    source_thread_id=str(row["source_thread_id"]),
                    match_type=str(row["match_type"]),
                    rank=float(row["rank"]),
                )
                for row in rows
            ]
            return FtsSearchPage(hits=hits, total_count=total_count, has_more=False, next_offset=None)
        rows = conn.execute(
            f"""
            {base_sql}
            SELECT message_id, source_thread_id, match_type, rank
            FROM ordered
            ORDER BY match_priority, rank, timestamp, sort_index, message_id
            LIMIT ? OFFSET ?
            """,
            (*params, limit, offset),
        ).fetchall()
    except sqlite3.OperationalError as exc:
        logger.error(
            component="search.fts",
            operation="sql_pagination_failed",
            message="SQL FTS pagination failed",
            details={"dataset_id": dataset_id, "candidate_count": len(specs)},
            exc=exc,
            dataset_id=dataset_id,
        )
        if "syntax error" in str(exc).lower() or "fts5" in str(exc).lower():
            return FtsSearchPage(hits=[], total_count=0, has_more=False, next_offset=None)
        raise

    hits = [
        FtsHit(
            message_id=str(row["message_id"]),
            source_thread_id=str(row["source_thread_id"]),
            match_type=str(row["match_type"]),
            rank=float(row["rank"]),
        )
        for row in rows
    ]
    next_offset = offset + len(hits)
    has_more = next_offset < total_count
    return FtsSearchPage(
        hits=hits,
        total_count=total_count,
        has_more=has_more,
        next_offset=next_offset if has_more else None,
    )


def search_keyword_terms(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    dataset_id: int,
    terms: list[str],
    *,
    limit: int | None = None,
    offset: int = 0,
) -> dict[str, Any]:
    specs = _candidate_specs_for_keyword_terms(terms)
    page = _search_candidates_sql(conn, logger, dataset_id, specs, limit=limit, offset=offset)
    return {
        "hits": page.hits,
        "total_count": page.total_count,
        "has_more": page.has_more,
        "next_offset": page.next_offset,
    }


def search_messages(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    dataset_id: int,
    query: str,
    *,
    limit: int | None = None,
    offset: int = 0,
) -> dict[str, Any]:
    """Search messages with optional pagination.

    Returns ``hits``, ``total_count``, ``has_more``, and ``next_offset`` for the
    merged, de-duplicated result set. Pass ``limit=None`` to return all hits.
    """
    if limit is None:
        lanes = _collect_lane_results(conn, logger, dataset_id, query)
        merged = _merge_lane_results(lanes)
        ordered = _sort_merged_hits(conn, dataset_id, merged)
        page = _paginate_hits(ordered, limit=limit, offset=offset)
    else:
        specs = _candidate_specs_for_query(conn, logger, dataset_id, query)
        page = _search_candidates_sql(conn, logger, dataset_id, specs, limit=limit, offset=offset)
    logger.info(
        component="search.fts",
        operation="search_messages",
        message="Merged FTS search completed",
        details={
            "dataset_id": dataset_id,
            "query": query,
            "total_count": page.total_count,
            "page_size": limit,
            "offset": offset,
            "page_hit_count": len(page.hits),
            "has_more": page.has_more,
            "next_offset": page.next_offset,
        },
        dataset_id=dataset_id,
    )
    return {
        "hits": page.hits,
        "total_count": page.total_count,
        "has_more": page.has_more,
        "next_offset": page.next_offset,
    }
