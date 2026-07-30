"""Read-only structural validator for an EVW v14 file."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


def verify(path: Path) -> None:
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        if conn.execute("SELECT version FROM schema_version").fetchone()[0] != 14:
            raise RuntimeError("schema version is not 14")
        if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("quick_check failed")
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(f"foreign_key_check found {len(violations)} violations")
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','shadow')")}
        required = {"dataset", "source_thread", "message", "working_corpus", "working_corpus_message", "working_corpus_index", "conversation", "conversation_turn", "message_fts"}
        missing = required - tables
        if missing:
            raise RuntimeError(f"missing required tables: {sorted(missing)}")
        forbidden = {"model_run", "process_log", "prompt_template", "conversation_hit", "conversation_range", "workstation_conversation"}
        leaked = forbidden & tables
        if leaked:
            raise RuntimeError(f"development tables present: {sorted(leaked)}")
        required_columns = {
            "dataset": {"content_revision"},
            "working_corpus": {"message_count", "content_revision"},
            "working_corpus_index": {"status", "content_revision"},
            "message_fts": {"working_corpus_id", "index_generation"},
        }
        for table, columns in required_columns.items():
            actual = {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}
            missing = columns - actual
            if missing:
                raise RuntimeError(f"{table} is missing required columns: {sorted(missing)}")
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    verify(args.path)
    print("EVW v14: PASS")
