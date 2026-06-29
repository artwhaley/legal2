"""Spellfix-backed fuzzy term expansion for case-local message search."""

from __future__ import annotations

import re
import sqlite3
from difflib import SequenceMatcher
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from message_evidence_workstation.logging_ui.process_log import ProcessLogger

SPELLFIX_TABLE = "message_spellfix"
SPELLFIX_TERM_TABLE = "message_spellfix_term"
MIN_TERM_LENGTH = 4
MAX_FUZZY_CANDIDATES = 5
MAX_EDIT_DISTANCE = 220
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9']{3,}")

STOPWORDS = {
    "about",
    "after",
    "again",
    "also",
    "because",
    "been",
    "before",
    "being",
    "between",
    "could",
    "does",
    "doing",
    "done",
    "from",
    "have",
    "here",
    "into",
    "just",
    "like",
    "more",
    "need",
    "only",
    "over",
    "really",
    "said",
    "same",
    "should",
    "some",
    "than",
    "that",
    "their",
    "them",
    "then",
    "there",
    "they",
    "this",
    "very",
    "want",
    "were",
    "what",
    "when",
    "where",
    "which",
    "with",
    "would",
    "your",
}


def bundled_spellfix_path() -> Path:
    suffix = ".dll"
    if Path(__file__).anchor == "/":
        suffix = ".so"
    return Path(__file__).resolve().parents[1] / "native" / f"spellfix{suffix}"


def load_spellfix(conn: sqlite3.Connection, extension_path: str | None = None) -> str:
    path = Path(extension_path) if extension_path else bundled_spellfix_path()
    if not path.is_file():
        raise RuntimeError(f"spellfix extension not found: {path}")
    conn.enable_load_extension(True)
    conn.load_extension(str(path))
    return str(path)


def ensure_spellfix_schema(conn: sqlite3.Connection) -> None:
    load_spellfix(conn)
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SPELLFIX_TERM_TABLE} (
            dataset_id INTEGER NOT NULL,
            term TEXT NOT NULL,
            rank INTEGER NOT NULL DEFAULT 1,
            document_count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (dataset_id, term)
        )
        """
    )
    conn.execute(f"CREATE VIRTUAL TABLE IF NOT EXISTS {SPELLFIX_TABLE} USING spellfix1")
    conn.commit()


def normalize_term(term: str) -> str:
    return term.strip("'").casefold()


def iter_search_terms(text: str) -> set[str]:
    terms: set[str] = set()
    for match in TOKEN_RE.finditer(text):
        term = normalize_term(match.group(0))
        if len(term) < MIN_TERM_LENGTH or term in STOPWORDS:
            continue
        if len(set(term)) <= 2:
            continue
        terms.add(term)
    return terms


def levenshtein_distance(left: str, right: str) -> int:
    if left == right:
        return 0
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for i, left_char in enumerate(left, start=1):
        current = [i]
        for j, right_char in enumerate(right, start=1):
            insert_cost = current[j - 1] + 1
            delete_cost = previous[j] + 1
            replace_cost = previous[j - 1] + (0 if left_char == right_char else 1)
            current.append(min(insert_cost, delete_cost, replace_cost))
        previous = current
    return previous[-1]


def max_levenshtein_for_term(term: str) -> int:
    return 1 if len(term) <= 5 else 2


def _candidate_is_close(query: str, candidate: str) -> bool:
    if levenshtein_distance(query, candidate) > max_levenshtein_for_term(query):
        return False
    return SequenceMatcher(None, query, candidate).ratio() >= 0.75


def clear_spellfix_for_dataset(conn: sqlite3.Connection, dataset_id: int) -> None:
    ensure_spellfix_schema(conn)
    conn.execute(f"DELETE FROM {SPELLFIX_TABLE} WHERE langid = ?", (dataset_id,))
    conn.execute(f"DELETE FROM {SPELLFIX_TERM_TABLE} WHERE dataset_id = ?", (dataset_id,))


def rebuild_spellfix_for_dataset(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    dataset_id: int,
    *,
    progress_callback: Callable[[str, int, int], None] | None = None,
) -> int:
    ensure_spellfix_schema(conn)
    logger.info(
        component="search.spellfix",
        operation="rebuild_start",
        message="Rebuilding spellfix vocabulary",
        details={"dataset_id": dataset_id},
        dataset_id=dataset_id,
    )
    clear_spellfix_for_dataset(conn, dataset_id)
    rows = conn.execute(
        """
        SELECT message_id, body, body_normalized, sender_display, attachment_summary
        FROM message
        WHERE dataset_id = ?
        """,
        (dataset_id,),
    ).fetchall()
    term_messages: dict[str, set[str]] = {}
    for row in rows:
        text = " ".join(
            str(row[key] or "")
            for key in ("body", "body_normalized", "sender_display", "attachment_summary")
        )
        for term in iter_search_terms(text):
            term_messages.setdefault(term, set()).add(str(row["message_id"]))

    for term, message_ids in sorted(term_messages.items()):
        rank = len(message_ids)
        conn.execute(
            f"""
            INSERT INTO {SPELLFIX_TERM_TABLE} (dataset_id, term, rank, document_count)
            VALUES (?, ?, ?, ?)
            """,
            (dataset_id, term, rank, rank),
        )
        conn.execute(
            f"INSERT INTO {SPELLFIX_TABLE} (word, rank, langid) VALUES (?, ?, ?)",
            (term, rank, dataset_id),
        )
    conn.commit()
    term_count = len(term_messages)
    if progress_callback is not None:
        progress_callback("spellfix", term_count, term_count)
    logger.info(
        component="search.spellfix",
        operation="rebuild_complete",
        message="Spellfix vocabulary rebuild completed",
        details={"dataset_id": dataset_id, "term_count": term_count},
        dataset_id=dataset_id,
    )
    return term_count


def expand_fuzzy_terms(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    dataset_id: int,
    token: str,
    *,
    limit: int = MAX_FUZZY_CANDIDATES,
) -> list[str]:
    term = normalize_term(token)
    if len(term) < MIN_TERM_LENGTH or term in STOPWORDS:
        return []
    ensure_spellfix_schema(conn)
    exact = conn.execute(
        f"SELECT 1 FROM {SPELLFIX_TERM_TABLE} WHERE dataset_id = ? AND term = ? LIMIT 1",
        (dataset_id, term),
    ).fetchone()
    if exact:
        return []

    candidates: dict[str, tuple[int, int]] = {}
    for row in conn.execute(
        f"""
        SELECT word, distance, rank
        FROM {SPELLFIX_TABLE}
        WHERE word MATCH ? AND langid = ? AND top = ?
        """,
        (term, dataset_id, limit),
    ).fetchall():
        word = str(row["word"])
        distance = int(row["distance"])
        rank = int(row["rank"])
        if distance <= MAX_EDIT_DISTANCE and word != term and _candidate_is_close(term, word):
            candidates[word] = (distance, rank)

    for row in conn.execute(
        f"""
        SELECT term, rank, spellfix1_editdist(?, term) AS distance
        FROM {SPELLFIX_TERM_TABLE}
        WHERE dataset_id = ?
          AND ABS(length(term) - length(?)) <= 2
          AND substr(term, 1, 1) = substr(?, 1, 1)
        ORDER BY distance ASC, rank DESC, term ASC
        LIMIT ?
        """,
        (term, dataset_id, term, term, limit * 4),
    ).fetchall():
        word = str(row["term"])
        distance = int(row["distance"])
        rank = int(row["rank"])
        if distance <= MAX_EDIT_DISTANCE and word != term and _candidate_is_close(term, word):
            current = candidates.get(word)
            if current is None or (distance, -rank) < (current[0], -current[1]):
                candidates[word] = (distance, rank)

    ordered = sorted(candidates.items(), key=lambda item: (item[1][0], -item[1][1], item[0]))
    terms = [word for word, _meta in ordered[:limit]]
    if terms:
        logger.info(
            component="search.spellfix",
            operation="fuzzy_terms_expanded",
            message="Spellfix fuzzy terms expanded",
            details={"dataset_id": dataset_id, "token": term, "terms": terms},
            dataset_id=dataset_id,
        )
    return terms
