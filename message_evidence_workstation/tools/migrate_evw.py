"""Explicit v12/v13/v14 -> v15 EVW compact-copy migration."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from message_evidence_workstation.db.schema import CREATE_TABLES_SQL
from message_evidence_workstation.domain.constants import SCHEMA_VERSION, WORKING_CORPUS_TOKEN_LIMIT
from message_evidence_workstation.domain.search_scope import TOKENIZER_ID, count_tokens
from message_evidence_workstation.logging_ui.diagnostic_logger import DiagnosticLogger
from message_evidence_workstation.search.scoped_search import rebuild_fts, rebuild_spellfix


class MigrationError(RuntimeError):
    pass


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}


def _exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type IN ('table','virtual table') AND name=?", (table,)).fetchone() is not None


def _read_conn(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        conn.enable_load_extension(True)
        import sqlite_vec
        sqlite_vec.load(conn)
    except (ImportError, sqlite3.OperationalError):
        pass
    return conn


def _write_conn(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def _hash_body(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _copy_table(source: sqlite3.Connection, target: sqlite3.Connection, table: str, columns: list[str]) -> None:
    if not _exists(source, table):
        return
    source_cols = _columns(source, table)
    usable = [c for c in columns if c in source_cols]
    if not usable:
        return
    rows = source.execute(f"SELECT {','.join(usable)} FROM {table}").fetchall()
    if rows:
        placeholders = ",".join("?" for _ in usable)
        target.executemany(f"INSERT INTO {table}({','.join(usable)}) VALUES ({placeholders})", [tuple(row[c] for c in usable) for row in rows])


def _old_corpus_rows(source: sqlite3.Connection) -> list[sqlite3.Row]:
    if not _exists(source, "working_corpus"):
        return []
    return source.execute("SELECT * FROM working_corpus ORDER BY working_corpus_id").fetchall()


def _old_membership(source: sqlite3.Connection, corpus_id: int) -> list[sqlite3.Row]:
    if not _exists(source, "working_corpus_message"):
        return []
    return source.execute("SELECT * FROM working_corpus_message WHERE working_corpus_id=? ORDER BY ordinal", (corpus_id,)).fetchall()


def _migrate_corpora(source: sqlite3.Connection, target: sqlite3.Connection, dataset_id: int, now: str) -> dict[int, tuple[int, int]]:
    old_rows = _old_corpus_rows(source)
    result: dict[int, tuple[int, int]] = {}
    if not old_rows:
        return result
    for old in old_rows:
        old_id = int(old["working_corpus_id"])
        target.execute("INSERT INTO working_corpus(working_corpus_id,dataset_id,name,created_at,updated_at) VALUES (?,?,?,?,?)", (old_id, dataset_id, old["name"], old["created_at"], old["updated_at"]))
        current_revision = int(old["content_revision"]) if "content_revision" in old.keys() else 1
        status = str(old["status"] or "failed")
        if status == "indexing":
            status = "building"
        if status not in {"draft", "building", "ready", "stale", "failed"}:
            status = "failed"
        membership = _old_membership(source, old_id)
        revision_id = int(target.execute(
            """INSERT INTO working_corpus_revision(working_corpus_id,revision_number,base_revision_id,selection_mode,start_date,end_date,token_limit,estimated_tokens,message_count,tokenizer_id,scope_hash,dataset_content_revision,status,last_error,created_at,built_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (old_id, 1, None, old["selection_mode"] if "selection_mode" in old.keys() else "all", old["start_date"] if "start_date" in old.keys() else None, old["end_date"] if "end_date" in old.keys() else None, WORKING_CORPUS_TOKEN_LIMIT, int(old["estimated_tokens"] or 0) if "estimated_tokens" in old.keys() else 0, len(membership), str(old["tokenizer_id"] if "tokenizer_id" in old.keys() and old["tokenizer_id"] else TOKENIZER_ID), str(old["scope_hash"] if "scope_hash" in old.keys() else ""), current_revision, "draft", old["last_error"] if "last_error" in old.keys() else None, old["created_at"] or now, None),
        ).lastrowid)
        result[old_id] = (revision_id, old_id)
        if _exists(source, "working_corpus_source"):
            target.executemany("INSERT INTO working_corpus_revision_source VALUES (?,?)", [(revision_id, row[0]) for row in source.execute("SELECT source_name FROM working_corpus_source WHERE working_corpus_id=?", (old_id,))])
        if _exists(source, "working_corpus_thread"):
            target.executemany("INSERT INTO working_corpus_revision_thread VALUES (?,?)", [(revision_id, row[0]) for row in source.execute("SELECT source_thread_id FROM working_corpus_thread WHERE working_corpus_id=?", (old_id,))])
        target.execute("UPDATE working_corpus_revision SET status=? WHERE working_corpus_revision_id=?", ("building" if status in {"ready", "stale", "building"} else status, revision_id))
        if status in {"ready", "stale", "building"}:
            target.execute("UPDATE working_corpus_revision SET status='building' WHERE working_corpus_revision_id=?", (revision_id,))
            for ordinal, row in enumerate(membership):
                message = target.execute("SELECT source_thread_id,token_count,embedding_input_hash FROM message WHERE message_id=?", (row["message_id"],)).fetchone()
                if message is None:
                    raise MigrationError(f"Corpus {old_id} membership references missing message {row['message_id']}")
                target.execute("INSERT INTO working_corpus_revision_message(working_corpus_revision_id,message_id,source_thread_id,ordinal,token_count,embedding_input_hash) VALUES (?,?,?,?,?,?)", (revision_id, row["message_id"], message["source_thread_id"], ordinal, int(row["token_count"] or message["token_count"]), message["embedding_input_hash"]))
            index_generation = int(source.execute("SELECT COALESCE(MAX(index_generation),0) FROM working_corpus_index WHERE working_corpus_id=?", (old_id,)).fetchone()[0]) if _exists(source, "working_corpus_index") else 1
            index_generation = max(index_generation, 1)
            target.execute("INSERT INTO working_corpus_revision_index(working_corpus_revision_id,index_generation,dataset_content_revision,status,created_at,updated_at) VALUES (?,?,?,?,?,?)", (revision_id, index_generation, current_revision, "building", str(old["created_at"] or now), str(old["updated_at"] or now)))
            scope = _scope_for_migration(target, revision_id, old_id, dataset_id, index_generation, current_revision, old)
            rebuild_fts(target, DiagnosticLogger(log_bus=None), scope)
            rebuild_spellfix(target, DiagnosticLogger(log_bus=None), scope)
            if _exists(source, "message_chunk"):
                chunk_columns = _columns(source, "message_chunk")
                if {"chunk_id", "working_corpus_id", "index_generation", "source_thread_id", "start_message_id", "end_message_id", "message_count", "char_count", "text_checksum", "body_text"}.issubset(chunk_columns):
                    for chunk in source.execute("SELECT chunk_id,index_generation,source_thread_id,start_message_id,end_message_id,message_count,char_count,text_checksum,body_text FROM message_chunk WHERE working_corpus_id=?", (old_id,)):
                        body_text = str(chunk["body_text"])
                        target.execute("INSERT INTO message_chunk(chunk_id,working_corpus_revision_id,index_generation,source_thread_id,start_message_id,end_message_id,message_count,char_count,text_checksum,embedding_input_hash,body_text) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (int(chunk["chunk_id"]), revision_id, int(chunk["index_generation"]), str(chunk["source_thread_id"]), str(chunk["start_message_id"]), str(chunk["end_message_id"]), int(chunk["message_count"]), int(chunk["char_count"]), str(chunk["text_checksum"]), _hash_body(body_text), body_text))
            target.execute("UPDATE working_corpus_revision_index SET status=? WHERE working_corpus_revision_id=? AND index_generation=?", (status if status in {"ready", "stale"} else "building", revision_id, index_generation))
            target.execute("UPDATE working_corpus_revision SET status=?,built_at=? WHERE working_corpus_revision_id=?", (status, str(old["updated_at"] or now) if status in {"ready", "stale"} else None, revision_id))
            if status in {"ready", "stale"}:
                target.execute("UPDATE working_corpus SET current_revision_id=? WHERE working_corpus_id=?", (revision_id, old_id))
        elif status == "failed":
            target.execute("UPDATE working_corpus_revision SET last_error=COALESCE(last_error,'Preserved failed source revision') WHERE working_corpus_revision_id=?", (revision_id,))
    return result


def _scope_for_migration(target: sqlite3.Connection, revision_id: int, corpus_id: int, dataset_id: int, generation: int, dataset_revision: int, old: sqlite3.Row):
    from message_evidence_workstation.domain.search_scope import WorkingCorpusScope
    rows = [(str(r[0]), int(r[1])) for r in target.execute("SELECT message_id,token_count FROM working_corpus_revision_message WHERE working_corpus_revision_id=? ORDER BY ordinal", (revision_id,))]
    digest = hashlib.sha256((str(dataset_revision) + "\x1f" + hashlib.sha256(repr(rows).encode()).hexdigest()).encode()).hexdigest()
    target.execute("UPDATE working_corpus_revision SET scope_hash=?,estimated_tokens=?,message_count=? WHERE working_corpus_revision_id=?", (str(old["scope_hash"] or digest), sum(v for _, v in rows), len(rows), revision_id))
    revision_number = int(target.execute("SELECT revision_number FROM working_corpus_revision WHERE working_corpus_revision_id=?", (revision_id,)).fetchone()[0])
    return WorkingCorpusScope(corpus_id, revision_id, revision_number, dataset_id, generation, dataset_revision, str(old["scope_hash"] or digest), len(rows), sum(v for _, v in rows), str(old["tokenizer_id"] or TOKENIZER_ID))


def _migrate_vectors(source: sqlite3.Connection, target: sqlite3.Connection, *, discard: bool) -> dict[str, int]:
    counts = {"message_artifacts": 0, "chunk_artifacts": 0, "discarded": 0}
    tables = [("message_embedding_vec", "message_id", "message"), ("chunk_embedding_vec", "chunk_id", "chunk")]
    for table, id_column, kind in tables:
        if not _exists(source, table):
            continue
        rows = source.execute(f"SELECT embedding,{id_column} FROM {table}").fetchall()
        if not rows:
            continue
        if discard:
            counts["discarded"] += len(rows)
            continue
        for row in rows:
            blob = bytes(row[0])
            if len(blob) % 4:
                raise MigrationError(f"{table} contains a vector with invalid byte length")
            if kind == "message":
                text_row = target.execute("SELECT body FROM message WHERE message_id=?", (row[1],)).fetchone()
            else:
                text_row = target.execute("SELECT body_text FROM message_chunk WHERE chunk_id=?", (row[1],)).fetchone()
            if text_row is None:
                raise MigrationError(f"{table} references missing {kind} {row[1]}")
            input_hash = _hash_body(str(text_row[0]))
            dimensions = len(blob) // 4
            existing = target.execute("SELECT dimensions,vector FROM embedding_artifact WHERE input_hash=?", (input_hash,)).fetchone()
            if existing is not None:
                if int(existing[0]) != dimensions or bytes(existing[1]) != blob:
                    raise MigrationError(f"Conflicting vectors for input hash {input_hash} from {table} row {row[1]}")
                continue
            state = target.execute("SELECT dimensions,normalization FROM embedding_cache_state WHERE cache_id=1").fetchone()
            if state is None:
                target.execute("INSERT INTO embedding_cache_state(cache_id,dimensions,normalization,created_at,updated_at) VALUES (1,?,?,datetime('now'),datetime('now'))", (dimensions, "unit_l2"))
            elif int(state[0]) != dimensions:
                raise MigrationError(f"Vector geometry conflict: {dimensions} versus {state[0]}")
            target.execute("INSERT INTO embedding_artifact(input_hash,dimensions,vector,created_at) VALUES (?,?,?,datetime('now'))", (input_hash, dimensions, blob))
            counts[f"{kind}_artifacts"] += 1
    return counts


def _legacy_order(source: sqlite3.Connection, corpus_id: int | None, thread_id: str) -> list[str]:
    if corpus_id is None:
        rows = source.execute("SELECT message_id FROM message WHERE source_thread_id=? ORDER BY timestamp,sort_index,message_id", (thread_id,)).fetchall()
    else:
        rows = source.execute("""SELECT w.message_id FROM working_corpus_message w JOIN message m ON m.message_id=w.message_id
            WHERE w.working_corpus_id=? AND m.source_thread_id=? ORDER BY w.ordinal""", (corpus_id, thread_id)).fetchall()
    return [str(row[0]) for row in rows]


def _legacy_evidence_candidates(source: sqlite3.Connection) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    if not _exists(source, "evidence_block"):
        return candidates
    for row in source.execute("SELECT * FROM evidence_block ORDER BY evidence_block_id"):
        thread = str(row["source_thread_id"])
        slots = [int(row[key]) for key in ("context_start_slot", "relevant_start_slot", "relevant_end_slot", "context_end_slot")]
        possible: list[int] = []
        for corpus in _old_corpus_rows(source):
            ordered = _legacy_order(source, int(corpus["working_corpus_id"]), thread)
            if len(ordered) >= slots[-1] and 0 <= slots[0] < slots[1] < slots[2] <= slots[3] <= len(ordered):
                possible.append(int(corpus["working_corpus_id"]))
        candidates.append({"evidence_block_id": int(row["evidence_block_id"]), "source_thread_id": thread, "slots": slots, "core_message_id": str(row["core_hit_message_id"]), "highlight_message_ids": [str(r[0]) for r in source.execute("SELECT message_id FROM evidence_block_highlight WHERE evidence_block_id=?", (row["evidence_block_id"],))] if _exists(source, "evidence_block_highlight") else [], "candidate_working_corpus_ids": possible})
    return candidates


def _migrate_legacy_evidence(source: sqlite3.Connection, target: sqlite3.Connection, corpora: dict[int, tuple[int, int]], scope_map: Path | None, dataset_id: int) -> int:
    if not _exists(source, "evidence_block"):
        return 0
    blocks = _legacy_evidence_candidates(source)
    if not blocks:
        return 0
    if scope_map is None:
        raise MigrationError("Legacy evidence scope map is required")
    try:
        mapping = json.loads(scope_map.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MigrationError(f"Invalid legacy evidence scope map: {exc}") from exc
    if not isinstance(mapping, dict):
        raise MigrationError("Legacy evidence scope map must be a JSON object")
    converted = 0
    for info in blocks:
        source_row = source.execute("SELECT * FROM evidence_block WHERE evidence_block_id=?", (info["evidence_block_id"],)).fetchone()
        entry = mapping.get(str(info["evidence_block_id"]))
        if not isinstance(entry, dict) or entry.get("kind") not in {"working_corpus", "canonical_thread"}:
            raise MigrationError(f"Missing or invalid evidence scope map entry for block {info['evidence_block_id']}")
        corpus_id = int(entry["working_corpus_id"]) if entry["kind"] == "working_corpus" and "working_corpus_id" in entry else None
        if entry["kind"] == "working_corpus" and corpus_id not in corpora:
            raise MigrationError(f"Evidence block {info['evidence_block_id']} maps to unknown working corpus {corpus_id}")
        ordered = _legacy_order(source, corpus_id, info["source_thread_id"])
        context_start, relevant_start, relevant_end, context_end = info["slots"]
        if not (0 <= context_start < relevant_start < relevant_end <= context_end <= len(ordered)):
            raise MigrationError(f"Evidence block {info['evidence_block_id']} has invalid positional boundaries")
        ids = ordered[context_start:context_end]
        relevant_ids = ordered[relevant_start:relevant_end]
        if str(source_row["core_hit_message_id"]) not in relevant_ids or any(mid not in ids for mid in info["highlight_message_ids"]):
            raise MigrationError(f"Evidence block {info['evidence_block_id']} core/highlight is outside its resolved range")
        revision_id = corpora[corpus_id][0] if corpus_id is not None else None
        scope_hash = target.execute("SELECT scope_hash FROM working_corpus_revision WHERE working_corpus_revision_id=?", (revision_id,)).fetchone()[0] if revision_id is not None else None
        now = str(source_row["updated_at"] or source_row["created_at"])
        target.execute("""INSERT INTO evidence_block(evidence_block_id,dataset_id,category_id,source_thread_id,title,summary,context_start_message_id,relevant_start_message_id,core_message_id,relevant_end_message_id,context_end_message_id,origin_kind,origin_working_corpus_revision_id,origin_scope_hash,created_by,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (int(source_row["evidence_block_id"]), dataset_id, int(source_row["category_id"]), info["source_thread_id"], source_row["title"], source_row["summary"], ids[0], relevant_ids[0], source_row["core_hit_message_id"], relevant_ids[-1], ids[-1], "working_corpus_revision" if revision_id is not None else "legacy_dataset", revision_id, scope_hash, source_row["created_by"], source_row["created_at"], now))
        for ordinal, message_id in enumerate(ids):
            section = "leading_context" if ordinal < relevant_start - context_start else "relevant" if ordinal < relevant_end - context_start else "trailing_context"
            body = target.execute("SELECT body FROM message WHERE message_id=?", (message_id,)).fetchone()[0]
            target.execute("INSERT INTO evidence_block_message VALUES (?,?,?,?,?)", (int(source_row["evidence_block_id"]), message_id, ordinal, section, _hash_body(str(body))))
        for message_id in info["highlight_message_ids"]:
            target.execute("INSERT INTO evidence_block_highlight VALUES (?,?)", (int(source_row["evidence_block_id"]), message_id))
        for candidate_old_id, (candidate_revision, _) in corpora.items():
            candidate_ids = set(_legacy_order(source, candidate_old_id, info["source_thread_id"]))
            if set(ids).issubset(candidate_ids):
                target.execute("INSERT INTO working_corpus_revision_evidence_block VALUES (?,?,?,?)", (candidate_revision, int(source_row["evidence_block_id"]), revision_id if candidate_revision != revision_id else None, now))
        converted += 1
    return converted


def migrate_evw(source_path: Path, destination_path: Path | None = None, *, keep_source: bool = True, discard_derived_embeddings: bool = False, legacy_evidence_scope_map: Path | None = None) -> Path:
    source_path = source_path.resolve()
    destination_path = (destination_path or source_path).resolve()
    if not source_path.is_file():
        raise MigrationError(f"Source EVW not found: {source_path}")
    with _read_conn(source_path) as source:
        version_row = source.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
        version = int(version_row[0]) if version_row else None
        if version not in {12, 13, 14}:
            raise MigrationError(f"Expected v12, v13, or v14 source, found {version!r}")
        if source.execute("PRAGMA quick_check").fetchone()[0] != "ok" or source.execute("PRAGMA foreign_key_check").fetchall():
            raise MigrationError("Source integrity validation failed")
        if _exists(source, "evidence_block") and int(source.execute("SELECT COUNT(*) FROM evidence_block").fetchone()[0]) and legacy_evidence_scope_map is None:
            report = destination_path.with_suffix(destination_path.suffix + ".legacy-evidence-scope-report.json")
            report.write_text(json.dumps({"error": "LEGACY_EVIDENCE_SCOPE_MAP_REQUIRED", "source": str(source_path), "blocks": _legacy_evidence_candidates(source)}, indent=2), encoding="utf-8")
            raise MigrationError(f"Legacy evidence requires --legacy-evidence-scope-map; report written to {report}")
        tmp = destination_path.with_name(destination_path.stem + ".v15-migrating.evw")
        tmp.unlink(missing_ok=True)
        target = _write_conn(tmp)
        try:
            target.executescript(CREATE_TABLES_SQL)
            target.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))
            now = str(source.execute("SELECT datetime('now')").fetchone()[0])
            metadata_table = "workspace_state" if _exists(source, "workspace_state") else "workspace_metadata"
            metadata = {str(row[0]): str(row[1]) for row in source.execute(f"SELECT key,value FROM {metadata_table}").fetchall()} if _exists(source, metadata_table) else {}
            metadata.update({"format_id": "message_evidence_workstation.evw", "format_version": "1", "updated_at": now, "workspace_open": "0"})
            target.executemany("INSERT INTO workspace_state(key,value) VALUES (?,?)", metadata.items())
            datasets = source.execute("SELECT * FROM dataset ORDER BY dataset_id").fetchall()
            if len(datasets) != 1:
                raise MigrationError(f"Expected exactly one dataset, found {len(datasets)}")
            d = datasets[0]
            dataset_id = int(d["dataset_id"])
            dataset_revision = int(d["content_revision"] if "content_revision" in d.keys() else 1)
            target.execute("INSERT INTO dataset(dataset_id,name,created_at,schema_version,notes,content_revision,import_validity,import_error,normalized_format_version) VALUES (?,?,?,?,?,?,?,?,?)", (dataset_id, d["name"], d["created_at"], 15, d["notes"] if "notes" in d.keys() else "", dataset_revision, d["import_validity"] if "import_validity" in d.keys() else "ready", d["import_error"] if "import_error" in d.keys() else "", d["normalized_format_version"] if "normalized_format_version" in d.keys() else None))
            _copy_table(source, target, "source_thread", ["source_thread_id","dataset_id","source_platform","platform_thread_id","display_title","participant_summary","start_ts","end_ts","message_count","metadata_json"])
            for row in source.execute("SELECT * FROM message ORDER BY source_thread_id,timestamp,sort_index,message_id").fetchall():
                body = str(row["body"] or "")
                serialized = f"[{row['message_id']}] {row['timestamp']} | {row['sender_display']}: {body.strip() or '(empty message)'}"
                target.execute("INSERT INTO message(message_id,dataset_id,source_thread_id,source_platform,source_message_id,timestamp,sender_id,sender_display,body,body_normalized,embedding_input_hash,has_attachment,attachment_summary,sort_index,source_metadata_json,thread_ordinal,token_count) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (row["message_id"], dataset_id, row["source_thread_id"], row["source_platform"], row["source_message_id"], row["timestamp"], row["sender_id"], row["sender_display"], body, row["body_normalized"], _hash_body(body), row["has_attachment"], row["attachment_summary"], row["sort_index"], row["source_metadata_json"], row["thread_ordinal"] if "thread_ordinal" in row.keys() else 0, count_tokens(serialized)))
            _copy_table(source, target, "category", ["category_id","dataset_id","name","description","color","is_collapsed","created_at","updated_at"])
            _copy_table(source, target, "printable_artifact_group", ["printable_artifact_group_id","dataset_id","name","sort_order","is_collapsed","created_at","updated_at"])
            _copy_table(source, target, "printable_artifact", ["printable_artifact_id","dataset_id","group_id","title","exhibit_number","case_number","sort_order","created_at","updated_at"])
            _copy_table(source, target, "printable_artifact_evidence_block", ["printable_artifact_evidence_block_id","printable_artifact_id","evidence_block_id","sort_order","created_at"])
            corpora = _migrate_corpora(source, target, dataset_id, now)
            if not corpora:
                from message_evidence_workstation.db.corpus_repository import WorkingCorpusRepository
                repo = WorkingCorpusRepository(target)
                corpus_id = repo.create_working_corpus(dataset_id=dataset_id, name="Full Corpus")
                revision_id = repo.create_draft_revision(working_corpus_id=corpus_id, base_revision_id=None)
                repo.replace_draft_definition(working_corpus_revision_id=revision_id, selection_mode="all", start_date=None, end_date=None, source_names=(), source_thread_ids=())
                repo.build_revision(revision_id)
                repo.publish_revision(working_corpus_id=corpus_id, working_corpus_revision_id=revision_id, excluded_evidence_block_ids=frozenset())
            _migrate_legacy_evidence(source, target, corpora, legacy_evidence_scope_map, dataset_id)
            vector_counts = _migrate_vectors(source, target, discard=discard_derived_embeddings)
            target.commit()
            if target.execute("PRAGMA quick_check").fetchone()[0] != "ok" or target.execute("PRAGMA foreign_key_check").fetchall():
                raise MigrationError("Target integrity validation failed")
            target.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            target.close(); target = None  # type: ignore[assignment]
            if destination_path == source_path:
                backup = source_path.with_name(source_path.stem + ".pre-v15.evw")
                if not keep_source:
                    backup.unlink(missing_ok=True)
                os.replace(source_path, backup)
                os.replace(tmp, destination_path)
            else:
                os.replace(tmp, destination_path)
            return destination_path
        finally:
            if target is not None:
                target.close()
            tmp.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a validated EVW v15 file from v12/v13/v14")
    parser.add_argument("source", type=Path)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--discard-derived-embeddings", action="store_true")
    parser.add_argument("--legacy-evidence-scope-map", type=Path)
    parser.add_argument("--discard-source-backup", action="store_true")
    args = parser.parse_args(argv)
    print(migrate_evw(args.source, args.destination, keep_source=not args.discard_source_backup, discard_derived_embeddings=args.discard_derived_embeddings, legacy_evidence_scope_map=args.legacy_evidence_scope_map))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
