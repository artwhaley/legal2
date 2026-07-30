"""Search/index operations that require an explicit v15 revision scope."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from message_evidence_workstation.domain.search_scope import NarrowedSearchScope, WorkingCorpusScope
from message_evidence_workstation.logging_ui.diagnostic_logger import DiagnosticLogger


@dataclass(slots=True)
class FtsHit:
    message_id: str
    source_thread_id: str
    match_type: str
    rank: float


@dataclass(slots=True)
class FtsSearchPage:
    hits: list[FtsHit]
    total_count: int
    has_more: bool
    next_offset: int | None
    invalid_query_reason: str | None = None


def _scope_predicate(scope: NarrowedSearchScope, alias: str = "m") -> tuple[str, tuple[Any, ...]]:
    return scope.sql_predicate(message_alias=alias)


def _require_ready(conn: sqlite3.Connection, scope: WorkingCorpusScope) -> None:
    row = conn.execute(
        """SELECT r.status,r.dataset_content_revision,i.index_generation,
                  i.status AS index_status,i.fts_status,i.spellfix_status,d.content_revision
             FROM working_corpus_revision r
             JOIN working_corpus wc ON wc.working_corpus_id=r.working_corpus_id
             JOIN dataset d ON d.dataset_id=wc.dataset_id
             JOIN working_corpus_revision_index i ON i.working_corpus_revision_id=r.working_corpus_revision_id
                AND i.index_generation=?
            WHERE r.working_corpus_revision_id=? AND wc.dataset_id=?""",
        (scope.index_generation, scope.working_corpus_revision_id, scope.dataset_id),
    ).fetchone()
    if (
        row is None
        or str(row["status"]) != "ready"
        or int(row["dataset_content_revision"]) != int(row["content_revision"])
        or str(row["index_status"]) != "ready"
        or str(row["fts_status"]) != "ready"
        or str(row["spellfix_status"]) != "ready"
    ):
        raise RuntimeError(f"Working corpus revision {scope.working_corpus_revision_id} is not ready")


def _require_indexable(conn: sqlite3.Connection, scope: WorkingCorpusScope) -> None:
    row = conn.execute(
        """SELECT r.status,r.dataset_content_revision,i.status AS index_status,d.content_revision
           FROM working_corpus_revision r JOIN working_corpus wc ON wc.working_corpus_id=r.working_corpus_id
           JOIN dataset d ON d.dataset_id=wc.dataset_id
           JOIN working_corpus_revision_index i ON i.working_corpus_revision_id=r.working_corpus_revision_id AND i.index_generation=?
           WHERE r.working_corpus_revision_id=? AND wc.dataset_id=?""",
        (scope.index_generation, scope.working_corpus_revision_id, scope.dataset_id),
    ).fetchone()
    if row is None or str(row["status"]) != "building" or int(row["dataset_content_revision"]) != int(row["content_revision"]) or str(row["index_status"]) != "building":
        raise RuntimeError(f"Working corpus revision {scope.working_corpus_revision_id} is not available for index construction")


def rebuild_fts(conn: sqlite3.Connection, logger: DiagnosticLogger, scope: WorkingCorpusScope) -> int:
    _require_indexable(conn, scope)
    conn.execute("DELETE FROM message_fts WHERE working_corpus_revision_id=? AND index_generation=?", (scope.working_corpus_revision_id, scope.index_generation))
    rows = conn.execute(
        """SELECT m.message_id,m.source_thread_id,m.body,m.body_normalized,m.sender_display
           FROM message m JOIN working_corpus_revision_message wcrm ON wcrm.message_id=m.message_id
           WHERE wcrm.working_corpus_revision_id=? ORDER BY wcrm.ordinal""",
        (scope.working_corpus_revision_id,),
    ).fetchall()
    conn.executemany(
        "INSERT INTO message_fts(message_id,working_corpus_revision_id,index_generation,source_thread_id,body,body_normalized,sender_display) VALUES (?,?,?,?,?,?,?)",
        [(row["message_id"], scope.working_corpus_revision_id, scope.index_generation, row["source_thread_id"], row["body"], row["body_normalized"], row["sender_display"]) for row in rows],
    )
    conn.execute("UPDATE working_corpus_revision_index SET fts_status='ready',updated_at=datetime('now') WHERE working_corpus_revision_id=? AND index_generation=?", (scope.working_corpus_revision_id, scope.index_generation))
    logger.info(component="search.scoped", operation="fts_rebuild", message="Scoped FTS rebuild completed", details={"working_corpus_revision_id": scope.working_corpus_revision_id, "index_generation": scope.index_generation, "rows": len(rows)})
    return len(rows)


def rebuild_spellfix(conn: sqlite3.Connection, logger: DiagnosticLogger, scope: WorkingCorpusScope) -> int:
    _require_indexable(conn, scope)
    conn.execute("DELETE FROM message_spellfix_term WHERE working_corpus_revision_id=? AND index_generation=?", (scope.working_corpus_revision_id, scope.index_generation))
    rows = conn.execute(
        """SELECT m.body,m.body_normalized,m.sender_display,m.attachment_summary
           FROM message m JOIN working_corpus_revision_message wcrm ON wcrm.message_id=m.message_id
           WHERE wcrm.working_corpus_revision_id=?""",
        (scope.working_corpus_revision_id,),
    ).fetchall()
    words: dict[str, int] = {}
    for row in rows:
        for term in re.findall(r"[A-Za-z][A-Za-z0-9']{3,}", " ".join(str(row[key] or "") for key in ("body", "body_normalized", "sender_display", "attachment_summary"))):
            words[term.casefold().strip("'")] = words.get(term.casefold().strip("'"), 0) + 1
    conn.executemany("INSERT INTO message_spellfix_term(working_corpus_revision_id,index_generation,term,rank,document_count) VALUES (?,?,?,?,?)", [(scope.working_corpus_revision_id, scope.index_generation, term, count, count) for term, count in sorted(words.items())])
    conn.execute("UPDATE working_corpus_revision_index SET spellfix_status='ready',updated_at=datetime('now') WHERE working_corpus_revision_id=? AND index_generation=?", (scope.working_corpus_revision_id, scope.index_generation))
    logger.info(component="search.scoped", operation="spellfix_rebuild", message="Scoped spellfix vocabulary rebuild completed", details={"working_corpus_revision_id": scope.working_corpus_revision_id, "index_generation": scope.index_generation, "terms": len(words)})
    return len(words)


def _fts_query(query: str) -> str:
    terms = [part.strip('"') for part in re.findall(r"[\w']+", query, flags=re.UNICODE) if part.strip()]
    if not terms:
        raise ValueError("Search query contains no searchable terms")
    return " AND ".join('"' + term.replace('"', '""') + '"' for term in terms)


def _search_fts_query(conn: sqlite3.Connection, scope: NarrowedSearchScope, fts_query: str, *, limit: int, offset: int) -> FtsSearchPage:
    _require_ready(conn, scope.working_corpus)
    scope_sql, scope_params = _scope_predicate(scope)
    base = """FROM message_fts mf JOIN message m ON m.message_id=mf.message_id
              WHERE mf.working_corpus_revision_id=? AND mf.index_generation=? AND message_fts MATCH ? AND """ + scope_sql
    params: tuple[Any, ...] = (scope.working_corpus_revision_id, scope.index_generation, fts_query, *scope_params)
    total = int(conn.execute("SELECT COUNT(*) " + base, params).fetchone()[0])
    rows = conn.execute("SELECT mf.message_id,mf.source_thread_id,bm25(message_fts) AS rank " + base + " ORDER BY rank,m.timestamp,m.sort_index,m.message_id LIMIT ? OFFSET ?", (*params, limit, offset)).fetchall()
    hits = [FtsHit(message_id=str(row["message_id"]), source_thread_id=str(row["source_thread_id"]), match_type="exact", rank=float(row["rank"])) for row in rows]
    next_offset = offset + len(hits)
    return FtsSearchPage(hits=hits, total_count=total, has_more=next_offset < total, next_offset=next_offset if next_offset < total else None)


def search_fts(conn: sqlite3.Connection, logger: DiagnosticLogger, scope: NarrowedSearchScope, query: str, *, limit: int = 200, offset: int = 0) -> FtsSearchPage:
    del logger
    return _search_fts_query(conn, scope, _fts_query(query), limit=limit, offset=offset)


def search_keyword_terms(conn: sqlite3.Connection, logger: DiagnosticLogger, scope: NarrowedSearchScope, terms: list[str], *, limit: int = 200, offset: int = 0) -> FtsSearchPage:
    del logger
    clauses: list[str] = []
    for term in terms:
        words = [part.strip('"') for part in re.findall(r"[\w']+", term, flags=re.UNICODE) if part.strip()]
        if words:
            phrase = " ".join(words).replace('"', '""')
            clauses.append(f'"{phrase}"')
    if not clauses:
        return FtsSearchPage(hits=[], total_count=0, has_more=False, next_offset=None, invalid_query_reason="no keyword terms")
    return _search_fts_query(conn, scope, " OR ".join(clauses), limit=limit, offset=offset)


def expand_spellfix_terms(conn: sqlite3.Connection, scope: WorkingCorpusScope, token: str, *, limit: int = 5) -> list[str]:
    _require_ready(conn, scope)
    token = token.casefold().strip("'")
    rows = conn.execute("SELECT term FROM message_spellfix_term WHERE working_corpus_revision_id=? AND index_generation=?", (scope.working_corpus_revision_id, scope.index_generation)).fetchall()
    def distance(candidate: str) -> int:
        if candidate == token:
            return 0
        previous = list(range(len(token) + 1))
        for i, char in enumerate(candidate, 1):
            current = [i]
            for j, other in enumerate(token, 1):
                current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (char != other)))
            previous = current
        return previous[-1]
    candidates = [(distance(str(row[0])), str(row[0])) for row in rows]
    candidates = [item for item in candidates if item[0] <= (1 if len(token) <= 5 else 2) and item[1] != token]
    candidates.sort(key=lambda item: (item[0], item[1]))
    return [term for _, term in candidates[:limit] if SequenceMatcher(None, token, term).ratio() >= 0.75]
