"""Strict read-only structural validator for an EVW v15 file."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


REQUIRED = {
    "schema_version", "workspace_state", "dataset", "source_thread", "message",
    "working_corpus", "working_corpus_revision", "working_corpus_revision_source",
    "working_corpus_revision_thread", "working_corpus_revision_message",
    "working_corpus_revision_index", "embedding_cache_state", "embedding_artifact",
    "message_chunk", "evidence_block", "evidence_block_message", "evidence_block_highlight",
    "working_corpus_revision_evidence_block", "conversation", "conversation_turn",
    "conversation_citation", "message_fts", "message_spellfix_term",
}
FORBIDDEN = {
    "working_corpus_message", "working_corpus_index", "working_corpus_source",
    "working_corpus_thread", "vector_store_metadata", "embedding_profile",
    "message_embedding_vec", "chunk_embedding_vec",
}


def validate(path: Path) -> None:
    if not path.is_file():
        raise RuntimeError(f"EVW not found: {path}")
    conn = sqlite3.connect(path)
    try:
        if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("quick_check failed")
        if conn.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("foreign_key_check failed")
        objects = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view','virtual table')")}
        version = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
        if version is None or int(version[0]) != 15:
            raise RuntimeError(f"expected schema v15, found {version[0] if version else None}")
        missing = sorted(REQUIRED - objects)
        forbidden = sorted(FORBIDDEN & objects)
        if missing or forbidden:
            raise RuntimeError(f"missing={missing} forbidden={forbidden}")
        bad_pointers = conn.execute("""SELECT wc.working_corpus_id FROM working_corpus wc
          LEFT JOIN working_corpus_revision r ON r.working_corpus_revision_id=wc.current_revision_id
          WHERE wc.current_revision_id IS NOT NULL AND (r.working_corpus_id IS NULL OR r.working_corpus_id<>wc.working_corpus_id)""").fetchall()
        if bad_pointers:
            raise RuntimeError(f"invalid corpus pointers: {bad_pointers}")
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        validate(Path(sys.argv[1]))
    except (IndexError, OSError, RuntimeError, sqlite3.Error) as exc:
        print(f"EVW v15: FAIL: {exc}")
        raise SystemExit(1)
    print("EVW v15: PASS")
