"""Local EVW workflows and the stateless remote gateway boundary."""

from __future__ import annotations

import hashlib
import math
import sqlite3
import struct
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Iterator

from message_evidence_workstation.client_api.gateway import (
    RemoteGateway,
    RemoteGatewayError,
    RequestCancellation,
)
from message_evidence_workstation.client_api.contracts import (
    validate_analysis_context,
    validate_analysis_plan,
)
from message_evidence_workstation.db.corpus_repository import WorkingCorpusRepository
from message_evidence_workstation.db.workspace_store import WorkspaceStore
from message_evidence_workstation.domain.search_scope import NarrowedSearchScope, WorkingCorpusScope
from message_evidence_workstation.logging_ui.diagnostic_logger import DiagnosticLogger, utc_now_iso
from message_evidence_workstation.search.scoped_search import search_fts, search_keyword_terms


@dataclass(frozen=True, slots=True)
class EmbeddingBuildResult:
    required_inputs: int
    covered_members: int
    reused_artifacts: int
    generated_artifacts: int
    dimensions: int
    normalization: str
    granularity: str = "message"

    @property
    def message_count(self) -> int:
        return self.covered_members if self.granularity == "message" else 0

    @property
    def chunk_count(self) -> int:
        return self.covered_members if self.granularity == "chunk" else 0


@dataclass(frozen=True, slots=True)
class EmbeddingBuildProgress:
    phase: str
    completed: int
    total: int
    batch_number: int
    batch_count: int
    message: str


@dataclass(frozen=True, slots=True)
class EmbeddingCacheClearResult:
    artifacts_deleted: int
    revision_indexes_marked_missing: int


@dataclass(frozen=True, slots=True)
class ConversationalSearchProgress:
    phase: str
    completed: int
    total: int
    message: str


@dataclass(frozen=True, slots=True)
class ConversationalExecutionResult:
    result: dict[str, Any]
    persistence_warning: str | None = None


class StaleConversationScope(RuntimeError):
    pass


def format_conversational_result(result: dict[str, Any]) -> str:
    """Render the strict server result as readable test equipment output."""
    status = str(result["completion_status"])
    source = str(result["answer_source"])
    lines = [f"STATUS: {status.upper()}"]

    if source == "structured_synthesis":
        lines.extend(["", "ANSWER", str(result["overview"])])
    elif source == "raw_synthesis_output":
        lines.extend(["", "RAW MODEL RESPONSE", str(result["raw_answer"])])
    else:
        lines.extend([
            "",
            "ANSWER UNAVAILABLE",
            "Narrative synthesis was unavailable. The validated evidence ledger remains below.",
        ])

    if source != "raw_synthesis_output":
        high = [
            item for item in result["results"]
            if item["probability"] == "high_probability"
        ]
        lower = [
            item for item in result["results"]
            if item["probability"] == "lower_probability"
        ]
        model_unclassified = [
            item for item in result["results"]
            if item["classification_status"] == "unclassified"
        ]

        def append_results(title: str, items: list[dict[str, Any]]) -> None:
            lines.extend(["", title])
            if not items:
                lines.append("(none)")
                return
            for number, item in enumerate(items, 1):
                lines.append(f"{number}. {item['statement']}")
                if item["verified_range_ids"]:
                    lines.append("   Verified ranges: " + ", ".join(item["verified_range_ids"]))
                if item["unverified_range_ids"]:
                    lines.append("   Unverified references: " + ", ".join(item["unverified_range_ids"]))
                if item["uncertainty"]:
                    lines.append(f"   Uncertainty: {item['uncertainty']}")

        append_results("HIGH PROBABILITY", high)
        lines.extend(["", "---------------- LOWER-PROBABILITY / REVIEW MATERIAL ----------------"])
        append_results("LOWER PROBABILITY", lower)
        append_results("MODEL RESULTS WITHOUT A VALID PROBABILITY LABEL", model_unclassified)

    lines.extend(["", "UNCLASSIFIED VALIDATED EVIDENCE"])
    if result["unclassified_evidence"]:
        for item in result["unclassified_evidence"]:
            description = item["summary"] or item["relevance"] or "(no model description)"
            lines.append(f"- {item['range_id']}: {description}")
    else:
        lines.append("(none)")

    lines.extend(["", "UNVERIFIED MODEL STATEMENTS"])
    if result["unverified_model_statements"]:
        for item in result["unverified_model_statements"]:
            references = ", ".join(item["reported_range_ids"]) or "(none)"
            lines.append(f"- {item['statement']}")
            lines.append(f"  Reported references: {references}")
    else:
        lines.append("(none)")

    warnings = result["synthesis_validation"]["warnings"]
    lines.extend(["", "WARNINGS"])
    if warnings:
        for warning in warnings:
            lines.append(f"- {warning['code']}")
    else:
        lines.append("(none)")

    coverage = result["coverage"]
    lines.extend([
        "",
        "COVERAGE",
        (
            f"{coverage['usable_window_count']}/{coverage['planned_window_count']} windows usable; "
            f"{coverage['evidence_range_count']} validated evidence ranges."
        ),
    ])
    return "\n".join(lines)


def _blob(vector: list[float]) -> bytes:
    return struct.pack("<" + "f" * len(vector), *(float(value) for value in vector))


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _require_scope(conn: sqlite3.Connection, scope: WorkingCorpusScope) -> None:
    WorkingCorpusRepository(conn).validate_ready_scope(scope)


class ClientWorkflowService:
    def __init__(self, conn: sqlite3.Connection, logger: DiagnosticLogger | None, gateway: RemoteGateway) -> None:
        self.conn, self.logger, self.gateway = conn, logger, gateway

    def fts5_search(self, scope: NarrowedSearchScope, query: str, *, limit: int = 200, offset: int = 0) -> dict[str, Any]:
        return _page_dict(search_fts(self.conn, self.logger, scope, query, limit=limit, offset=offset))

    def keyword_terms_search(self, scope: NarrowedSearchScope, terms: list[str], *, limit: int = 200) -> dict[str, Any]:
        return _page_dict(search_keyword_terms(self.conn, self.logger, scope, terms, limit=limit))

    def embedding_search_with_vector(self, scope: NarrowedSearchScope, vector: list[float], dimensions: int, *, top_k: int = 20, granularity: str = "message") -> list[dict[str, Any]]:
        _require_scope(self.conn, scope.working_corpus)
        if granularity not in {"message", "chunk"}:
            raise ValueError("granularity must be message or chunk")
        required_status = "message_embedding_status" if granularity == "message" else "chunk_embedding_status"
        row = self.conn.execute("SELECT message_embedding_status,chunk_embedding_status FROM working_corpus_revision_index WHERE working_corpus_revision_id=? AND index_generation=?", (scope.working_corpus_revision_id, scope.index_generation)).fetchone()
        state = self.conn.execute("SELECT dimensions FROM embedding_cache_state WHERE cache_id=1").fetchone()
        if row is None or str(row[required_status]) != "ready":
            raise RuntimeError(f"{granularity} embedding index is not ready")
        if state is None or int(state[0]) != dimensions:
            raise RuntimeError("EMBEDDING_CACHE_GEOMETRY_MISMATCH")
        query_blob = _blob(vector)
        import sqlite_vec
        self.conn.enable_load_extension(True)
        sqlite_vec.load(self.conn)
        if granularity == "message":
            rows = self.conn.execute(
                """SELECT m.message_id,m.source_thread_id,m.timestamp,m.body,
                          vec_distance_L2(e.vector, ?) AS distance
                     FROM working_corpus_revision_message wcrm
                     JOIN message m ON m.message_id=wcrm.message_id
                     JOIN embedding_artifact e ON e.input_hash=wcrm.embedding_input_hash
                    WHERE wcrm.working_corpus_revision_id=?
                    ORDER BY distance,m.timestamp,m.sort_index,m.message_id LIMIT ?""",
                (query_blob, scope.working_corpus_revision_id, top_k),
            ).fetchall()
            return [{"message_id": str(r["message_id"]), "source_thread_id": str(r["source_thread_id"]), "timestamp": str(r["timestamp"]), "body": str(r["body"]), "distance": float(r["distance"])} for r in rows]
        rows = self.conn.execute(
            """SELECT c.chunk_id,c.source_thread_id,c.start_message_id,c.end_message_id,c.body_text,
                      vec_distance_L2(e.vector, ?) AS distance
                 FROM message_chunk c JOIN embedding_artifact e ON e.input_hash=c.embedding_input_hash
                WHERE c.working_corpus_revision_id=? AND c.index_generation=?
                ORDER BY distance,c.chunk_id LIMIT ?""",
            (query_blob, scope.working_corpus_revision_id, scope.index_generation, top_k),
        ).fetchall()
        return [{"chunk_id": int(r["chunk_id"]), "source_thread_id": str(r["source_thread_id"]), "start_message_id": str(r["start_message_id"]), "end_message_id": str(r["end_message_id"]), "body_text": str(r["body_text"]), "distance": float(r["distance"])} for r in rows]

    def message_embedding_candidates_with_vector(
        self,
        scope: NarrowedSearchScope,
        vector: list[float],
        dimensions: int,
        *,
        top_k: int,
    ) -> list[dict[str, Any]]:
        """Return only the strict candidate fields used by conversation retrieval."""
        _require_scope(self.conn, scope.working_corpus)
        if not 1 <= top_k <= 1000:
            raise ValueError("top_k must be between 1 and 1000")
        row = self.conn.execute(
            """SELECT message_embedding_status
                 FROM working_corpus_revision_index
                WHERE working_corpus_revision_id=? AND index_generation=?""",
            (scope.working_corpus_revision_id, scope.index_generation),
        ).fetchone()
        state = self.conn.execute(
            "SELECT dimensions,normalization FROM embedding_cache_state WHERE cache_id=1"
        ).fetchone()
        if row is None or str(row[0]) != "ready":
            raise RuntimeError("message embedding index is not ready")
        if state is None or int(state[0]) != dimensions:
            raise RuntimeError("EMBEDDING_CACHE_GEOMETRY_MISMATCH")
        query_blob = _blob(vector)
        import sqlite_vec

        self.conn.enable_load_extension(True)
        sqlite_vec.load(self.conn)
        scope_sql, scope_params = scope.sql_predicate(message_alias="m")
        rows = self.conn.execute(
            """SELECT m.message_id,
                          vec_distance_L2(e.vector, ?) AS distance
                     FROM working_corpus_revision_message wcrm
                     JOIN message m ON m.message_id=wcrm.message_id
                     JOIN embedding_artifact e ON e.input_hash=wcrm.embedding_input_hash
                    WHERE wcrm.working_corpus_revision_id=? AND """
            + scope_sql
            + """
                    ORDER BY distance,m.timestamp,m.sort_index,m.message_id
                    LIMIT ?""",
            (query_blob, scope.working_corpus_revision_id, *scope_params, top_k),
        ).fetchall()
        return [
            {
                "message_id": str(row["message_id"]),
                "rank": index,
                "distance": float(row["distance"]),
            }
            for index, row in enumerate(rows, start=1)
        ]


def _page_dict(page: Any) -> dict[str, Any]:
    return {"hits": [{"message_id": h.message_id, "source_thread_id": h.source_thread_id, "match_type": h.match_type, "rank": h.rank} for h in page.hits], "total_count": page.total_count, "has_more": page.has_more, "next_offset": page.next_offset, "invalid_query_reason": page.invalid_query_reason}


class KeywordSearchWorkflow:
    def __init__(self, store: WorkspaceStore, logger: DiagnosticLogger, gateway: RemoteGateway) -> None:
        self.store, self.logger, self.gateway = store, logger, gateway

    def execute(self, scope: NarrowedSearchScope, query: str, *, limit: int = 200) -> dict[str, Any]:
        if not query.strip():
            raise ValueError("Keyword search requires a query")
        terms = list(self.gateway.keyword_expansion(query))
        result = self.store.read(lambda conn: ClientWorkflowService(conn, self.logger, self.gateway).keyword_terms_search(scope, terms, limit=limit))
        result["terms"] = terms
        return result


def _ensure_chunks(conn: sqlite3.Connection, scope: WorkingCorpusScope) -> None:
    if conn.execute("SELECT 1 FROM message_chunk WHERE working_corpus_revision_id=? AND index_generation=? LIMIT 1", (scope.working_corpus_revision_id, scope.index_generation)).fetchone() is not None:
        return
    rows = conn.execute(
        """SELECT m.message_id,m.source_thread_id,m.timestamp,m.sender_display,m.body
             FROM working_corpus_revision_message w JOIN message m ON m.message_id=w.message_id
            WHERE w.working_corpus_revision_id=? ORDER BY w.ordinal""",
        (scope.working_corpus_revision_id,),
    ).fetchall()
    batch: list[sqlite3.Row] = []
    chars = 0
    for row in rows:
        text = f"[{row['timestamp']}] {row['sender_display']}: {row['body']}"
        if batch and (row["source_thread_id"] != batch[0]["source_thread_id"] or len(batch) >= 40 or chars + len(text) > 12000):
            _insert_chunk(conn, scope, batch)
            batch = []
            chars = 0
        batch.append(row)
        chars += len(text)
    if batch:
        _insert_chunk(conn, scope, batch)


def _insert_chunk(conn: sqlite3.Connection, scope: WorkingCorpusScope, rows: list[sqlite3.Row]) -> None:
    body = "\n".join(f"[{row['timestamp']}] {row['sender_display']}: {row['body']}" for row in rows)
    conn.execute(
        """INSERT INTO message_chunk(working_corpus_revision_id,index_generation,source_thread_id,start_message_id,end_message_id,message_count,char_count,text_checksum,embedding_input_hash,body_text)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (scope.working_corpus_revision_id, scope.index_generation, rows[0]["source_thread_id"], rows[0]["message_id"], rows[-1]["message_id"], len(rows), len(body), _hash_text(body), _hash_text(body), body),
    )


class EmbeddingBuildCoordinator:
    def __init__(self, store: WorkspaceStore, logger: DiagnosticLogger, gateway: RemoteGateway) -> None:
        self.store, self.logger, self.gateway = store, logger, gateway

    def _all_items(self, conn: sqlite3.Connection, scope: WorkingCorpusScope, granularity: str) -> list[dict[str, str]]:
        if granularity == "chunk":
            _ensure_chunks(conn, scope)
            rows = conn.execute("SELECT DISTINCT embedding_input_hash,body_text FROM message_chunk WHERE working_corpus_revision_id=? AND index_generation=? ORDER BY chunk_id", (scope.working_corpus_revision_id, scope.index_generation)).fetchall()
            return [{"message_id": f"cache:{row['embedding_input_hash']}", "text": str(row["body_text"])} for row in rows]
        rows = conn.execute("SELECT DISTINCT wcrm.embedding_input_hash,m.body FROM working_corpus_revision_message wcrm JOIN message m ON m.message_id=wcrm.message_id WHERE wcrm.working_corpus_revision_id=? ORDER BY wcrm.ordinal", (scope.working_corpus_revision_id,)).fetchall()
        return [{"message_id": f"cache:{row['embedding_input_hash']}", "text": str(row["body"])} for row in rows]

    @staticmethod
    def _existing_hashes(
        conn: sqlite3.Connection,
        hashes: set[str],
        report: Callable[[EmbeddingBuildProgress], None],
    ) -> set[str]:
        ordered = sorted(hashes)
        existing: set[str] = set()
        batch_size = 900
        for start in range(0, len(ordered), batch_size):
            batch = ordered[start:start + batch_size]
            placeholders = ",".join("?" for _ in batch)
            existing.update(
                str(row[0])
                for row in conn.execute(
                    f"SELECT input_hash FROM embedding_artifact WHERE input_hash IN ({placeholders})",
                    tuple(batch),
                )
            )
            completed = min(start + len(batch), len(ordered))
            report(
                EmbeddingBuildProgress(
                    "inventory",
                    completed,
                    len(ordered),
                    0,
                    0,
                    f"Checking local vector cache: {completed:,}/{len(ordered):,} unique inputs",
                )
            )
        return existing

    @staticmethod
    def _consume_geometry_probe(
        events: Iterator[Any],
        probe_id: str,
        dimensions: int,
    ) -> None:
        vector_seen = False
        terminal_seen = False
        for event in events:
            value = event.value
            if value["event"] == "vector_batch":
                items = value["data"]["items"]
                if (
                    len(items) != 1
                    or items[0]["message_id"] != probe_id
                    or len(items[0]["vector"]) != dimensions
                    or any(not math.isfinite(float(number)) for number in items[0]["vector"])
                ):
                    raise RuntimeError("server returned an invalid embedding geometry probe")
                vector_seen = True
            elif value["event"] == "failed":
                raise RemoteGatewayError(
                    str(value["error"]["message"]),
                    error_code=str(value["error"]["code"]),
                )
            elif value["event"] == "completed":
                if int(value["result"]["total_items"]) != 1:
                    raise RuntimeError("embedding geometry probe returned the wrong terminal count")
                terminal_seen = True
        if not vector_seen or not terminal_seen:
            raise RuntimeError("embedding geometry probe ended without a vector and completion")

    def build(self, scope: WorkingCorpusScope, progress: Callable[[EmbeddingBuildProgress], None] | None = None, *, granularity: str = "message") -> EmbeddingBuildResult:
        if granularity not in {"message", "chunk"}:
            raise ValueError("granularity must be message or chunk")
        report = progress or (lambda _value: None)
        report(
            EmbeddingBuildProgress(
                "inventory",
                0,
                scope.message_count,
                0,
                0,
                f"Reading {scope.message_count:,} messages from the selected revision",
            )
        )
        self.store.read(lambda conn: _require_scope(conn, scope))
        if granularity == "chunk":
            all_items = self.store.write(
                lambda conn: self._all_items(conn, scope, granularity)
            )
            covered_members = len(all_items)
        else:
            all_items = self.store.read(
                lambda conn: self._all_items(conn, scope, granularity)
            )
            covered_members = scope.message_count
        if not all_items:
            raise ValueError("working corpus revision contains no messages")
        hashes = {item["message_id"][len("cache:"):] for item in all_items}
        existing = self.store.read(
            lambda conn: self._existing_hashes(conn, hashes, report)
        )
        pending = [item for item in all_items if item["message_id"][len("cache:"):] not in existing]
        state = self.store.read(lambda conn: conn.execute("SELECT dimensions,normalization FROM embedding_cache_state WHERE cache_id=1").fetchone())
        if not pending:
            if state is None:
                raise RuntimeError("embedding cache has coverage but no geometry")
            report(
                EmbeddingBuildProgress(
                    "verifying",
                    0,
                    1,
                    0,
                    0,
                    "Verifying cached vector geometry against the active server",
                )
            )
            probe = all_items[0]
            events = self.gateway.embeddings([probe])
            try:
                accepted = next(events).value["data"]
                dimensions = int(accepted["dimensions"])
                normalization = str(accepted["normalization"])
                if int(state[0]) != dimensions or str(state[1]) != normalization:
                    raise RuntimeError(
                        "EMBEDDING_CACHE_GEOMETRY_MISMATCH: "
                        f"local cache is {int(state[0])} dimensions/{state[1]}, "
                        f"active server is {dimensions} dimensions/{normalization}. "
                        "Use Clear local embeddings, then build again."
                    )
                self._consume_geometry_probe(
                    events, str(probe["message_id"]), dimensions
                )
                self.store.write(self._mark_ready, scope, granularity)
            except Exception as exc:
                self.store.write(self._mark_failed, scope, granularity, str(exc))
                raise
            report(
                EmbeddingBuildProgress(
                    "completed",
                    len(all_items),
                    len(all_items),
                    0,
                    0,
                    f"Complete: reused {len(existing):,} vectors covering {covered_members:,} messages",
                )
            )
            return EmbeddingBuildResult(
                len(all_items),
                covered_members,
                len(existing),
                0,
                dimensions,
                normalization,
                granularity,
            )
        report(EmbeddingBuildProgress("submitting", 0, len(pending), 0, 0, f"Submitting {len(pending):,} cache misses"))
        events = self.gateway.embeddings(pending)
        try:
            accepted = next(events).value["data"]
            dimensions = int(accepted["dimensions"])
            normalization = str(accepted["normalization"])
            if state is not None and (int(state[0]) != dimensions or str(state[1]) != normalization):
                raise RuntimeError(
                    "EMBEDDING_CACHE_GEOMETRY_MISMATCH: "
                    f"local cache is {int(state[0])} dimensions/{state[1]}, "
                    f"active server is {dimensions} dimensions/{normalization}. "
                    "Use Clear local embeddings, then build again."
                )
            submitted = {item["message_id"] for item in pending}
            completed = 0
            batch_number = 0
            batch_count = 0
            for event in events:
                value = event.value
                if value["event"] == "embedding_batch_started":
                    batch_number = int(value["data"]["batch_index"]) + 1
                    batch_count = int(value["data"]["batch_count"])
                    report(EmbeddingBuildProgress("encoding", completed, len(pending), batch_number, batch_count, f"Server encoding batch {batch_number:,}/{batch_count:,}"))
                if value["event"] == "vector_batch":
                    vectors = value["data"]["items"]
                    if len({item["message_id"] for item in vectors}) != len(vectors) or any(item["message_id"] not in submitted or len(item["vector"]) != dimensions or any(not math.isfinite(float(n)) for n in item["vector"]) for item in vectors):
                        raise RuntimeError("server returned an invalid vector batch")
                    self.store.write(self._commit_vectors, vectors, dimensions, normalization)
                    completed += len(vectors)
                    report(EmbeddingBuildProgress("committed", completed, len(pending), batch_number, batch_count, f"Committed {completed:,}/{len(pending):,} vectors"))
                if value["event"] == "failed":
                    raise RemoteGatewayError(str(value["error"]["message"]), error_code=str(value["error"]["code"]))
                if value["event"] == "completed":
                    if int(value["result"]["total_items"]) != len(pending) or completed != len(pending):
                        raise RuntimeError("embedding terminal counts do not match committed vectors")
                    self.store.write(self._mark_ready, scope, granularity)
                    report(
                        EmbeddingBuildProgress(
                            "completed",
                            len(all_items),
                            len(all_items),
                            batch_count,
                            batch_count,
                            f"Complete: generated {completed:,} and reused {len(existing):,} vectors covering {covered_members:,} messages",
                        )
                    )
                    return EmbeddingBuildResult(
                        len(all_items),
                        covered_members,
                        len(existing),
                        completed,
                        dimensions,
                        normalization,
                        granularity,
                    )
            raise RemoteGatewayError("embedding stream ended without completion", interrupted=True)
        except Exception as exc:
            self.store.write(self._mark_failed, scope, granularity, str(exc))
            raise

    @staticmethod
    def _commit_vectors(conn: sqlite3.Connection, vectors: list[dict[str, Any]], dimensions: int, normalization: str) -> None:
        now = utc_now_iso()
        state = conn.execute("SELECT dimensions,normalization FROM embedding_cache_state WHERE cache_id=1").fetchone()
        if state is None:
            conn.execute("INSERT INTO embedding_cache_state(cache_id,dimensions,normalization,created_at,updated_at) VALUES (1,?,?,?,?)", (dimensions, normalization, now, now))
        elif int(state[0]) != dimensions or str(state[1]) != normalization:
            raise RuntimeError("EMBEDDING_CACHE_GEOMETRY_MISMATCH")
        for item in vectors:
            input_hash = str(item["message_id"])[len("cache:"):]
            blob = _blob([float(v) for v in item["vector"]])
            existing = conn.execute("SELECT dimensions,vector FROM embedding_artifact WHERE input_hash=?", (input_hash,)).fetchone()
            if existing is not None and (int(existing[0]) != dimensions or bytes(existing[1]) != blob):
                raise RuntimeError(f"Conflicting embedding artifact for {input_hash}")
            if existing is None:
                conn.execute("INSERT INTO embedding_artifact(input_hash,dimensions,vector,created_at) VALUES (?,?,?,?)", (input_hash, dimensions, blob, now))

    @staticmethod
    def _mark_ready(conn: sqlite3.Connection, scope: WorkingCorpusScope, granularity: str) -> None:
        if granularity == "chunk":
            row = conn.execute("SELECT COUNT(*) AS required,COUNT(e.input_hash) AS covered FROM message_chunk w LEFT JOIN embedding_artifact e ON e.input_hash=w.embedding_input_hash WHERE w.working_corpus_revision_id=? AND w.index_generation=?", (scope.working_corpus_revision_id, scope.index_generation)).fetchone()
            column = "chunk_embedding_status"
            error_column = "chunk_embedding_last_error"
        else:
            row = conn.execute("SELECT COUNT(*) AS required,COUNT(e.input_hash) AS covered FROM working_corpus_revision_message w LEFT JOIN embedding_artifact e ON e.input_hash=w.embedding_input_hash WHERE w.working_corpus_revision_id=?", (scope.working_corpus_revision_id,)).fetchone()
            column = "message_embedding_status"
            error_column = "message_embedding_last_error"
        if int(row["required"]) != int(row["covered"]):
            raise RuntimeError(f"embedding coverage incomplete: {row['covered']}/{row['required']}")
        conn.execute(f"UPDATE working_corpus_revision_index SET {column}='ready',{error_column}=NULL WHERE working_corpus_revision_id=? AND index_generation=?", (scope.working_corpus_revision_id, scope.index_generation))

    @staticmethod
    def _mark_failed(conn: sqlite3.Connection, scope: WorkingCorpusScope, granularity: str, error: str) -> None:
        column = "chunk_embedding_status" if granularity == "chunk" else "message_embedding_status"
        error_column = "chunk_embedding_last_error" if granularity == "chunk" else "message_embedding_last_error"
        conn.execute(f"UPDATE working_corpus_revision_index SET {column}='failed',{error_column}=? WHERE working_corpus_revision_id=? AND index_generation=?", (error, scope.working_corpus_revision_id, scope.index_generation))


class EmbeddingSearchWorkflow:
    def __init__(self, store: WorkspaceStore, logger: DiagnosticLogger, gateway: RemoteGateway) -> None:
        self.store, self.logger, self.gateway = store, logger, gateway

    def execute(self, scope: NarrowedSearchScope, query: str, *, top_k: int = 20, granularity: str = "message") -> list[dict[str, Any]]:
        if not query.strip():
            raise ValueError("Embedding search requires a query")
        state = self.store.read(lambda conn: self._state(conn, scope, granularity))
        events = self.gateway.embeddings([{"message_id": "query", "text": query}])
        accepted = next(events).value["data"]
        dimensions = int(accepted["dimensions"])
        if dimensions != state["dimensions"] or str(accepted["normalization"]) != state["normalization"]:
            raise RuntimeError("EMBEDDING_CACHE_GEOMETRY_MISMATCH")
        vector: list[float] | None = None
        terminal = None
        for event in events:
            if event.event == "vector_batch":
                items = event.value["data"]["items"]
                if len(items) != 1 or items[0]["message_id"] != "query":
                    raise RemoteGatewayError("query embedding stream returned the wrong identity")
                vector = [float(v) for v in items[0]["vector"]]
            if event.terminal:
                terminal = event.value
        if terminal is None or terminal["event"] != "completed" or vector is None:
            raise RemoteGatewayError("query embedding did not complete")
        return self.store.read(lambda conn: ClientWorkflowService(conn, self.logger, self.gateway).embedding_search_with_vector(scope, vector, dimensions, top_k=top_k, granularity=granularity))

    @staticmethod
    def _state(conn: sqlite3.Connection, scope: NarrowedSearchScope, granularity: str) -> dict[str, Any]:
        if granularity not in {"message", "chunk"}:
            raise ValueError("granularity must be message or chunk")
        _require_scope(conn, scope.working_corpus)
        status = "message_embedding_status" if granularity == "message" else "chunk_embedding_status"
        row = conn.execute(f"SELECT {status} FROM working_corpus_revision_index WHERE working_corpus_revision_id=? AND index_generation=?", (scope.working_corpus_revision_id, scope.index_generation)).fetchone()
        state = conn.execute("SELECT dimensions,normalization FROM embedding_cache_state WHERE cache_id=1").fetchone()
        if row is None or str(row[0]) != "ready" or state is None:
            raise RuntimeError(f"{granularity} embedding index is not ready")
        return {"dimensions": int(state[0]), "normalization": str(state[1])}


class EmbeddingCacheService:
    @staticmethod
    def clear_local_embeddings(conn: sqlite3.Connection) -> EmbeddingCacheClearResult:
        artifacts = int(conn.execute("SELECT COUNT(*) FROM embedding_artifact").fetchone()[0])
        affected = int(conn.execute("SELECT COUNT(*) FROM working_corpus_revision_index WHERE message_embedding_status<>'missing' OR chunk_embedding_status<>'missing' OR message_embedding_last_error IS NOT NULL OR chunk_embedding_last_error IS NOT NULL").fetchone()[0])
        conn.execute("DELETE FROM embedding_artifact")
        conn.execute("DELETE FROM embedding_cache_state")
        conn.execute("UPDATE working_corpus_revision_index SET message_embedding_status='missing',chunk_embedding_status='missing',message_embedding_last_error=NULL,chunk_embedding_last_error=NULL")
        return EmbeddingCacheClearResult(artifacts, affected)


def clear_local_embeddings(store: WorkspaceStore) -> EmbeddingCacheClearResult:
    return store.write(EmbeddingCacheService.clear_local_embeddings)


class ConversationalWorkflow:
    def __init__(self, store: WorkspaceStore, logger: DiagnosticLogger, gateway: RemoteGateway) -> None:
        self.store, self.logger, self.gateway = store, logger, gateway

    def execute(
        self,
        scope: NarrowedSearchScope,
        question: str,
        progress: Callable[[ConversationalSearchProgress], None] | None = None,
        *,
        cancellation: RequestCancellation | None = None,
    ) -> ConversationalExecutionResult:
        if not question.strip():
            raise ValueError("Conversational search requires a question")
        messages = self.store.read(lambda conn: self._messages(conn, scope))
        if not messages:
            raise RuntimeError("WORKING_CORPUS_EMPTY")
        report = progress or (lambda _value: None)
        if cancellation is not None:
            cancellation.checkpoint()
        report(ConversationalSearchProgress("analysis_plan", 0, 1, "Requesting the conversational analysis plan"))
        analysis_context = self._prepare_analysis_context(
            scope,
            question,
            cancellation=cancellation,
            progress=report,
        )
        report(ConversationalSearchProgress("submitting", 0, 1, f"Submitting {len(messages):,} scoped messages"))
        result: dict[str, Any] | None = None
        window_total = 1
        completed_window_ids: set[str] = set()
        gateway_arguments = {
            "question": question,
            "scope_id": self._remote_scope_id(scope.working_corpus),
            "messages": messages,
            "analysis_context": analysis_context,
        }
        if cancellation is not None:
            gateway_arguments["cancellation"] = cancellation
        for event in self.gateway.conversational_analysis(**gateway_arguments):
            if event.event == "failed":
                error = event.value["error"]
                raise RemoteGatewayError(
                    str(error["message"]),
                    error_code=str(error["code"]),
                    request_id=str(error["request_id"]),
                    stage=str(error["stage"]),
                    retryable=bool(error["retryable"]),
                    details=dict(error["details"]),
                )
            if event.event == "completed":
                result = dict(event.value["result"])
                continue
            data = event.value.get("data", {})
            if event.event == "window_plan_created":
                window_total = int(data.get("window_count", 1))
            if event.event == "window_completed":
                completed_window_ids.add(str(data["window_id"]))
            if event.event == "window_unavailable":
                completed_window_ids.add(str(data["window_id"]))
            completed = len(completed_window_ids)
            if event.event == "window_started":
                message = (
                    f"Server started window {int(data['window_index']) + 1:,}/"
                    f"{int(data['window_count']):,}; "
                    f"{completed:,}/{window_total:,} complete"
                )
            elif event.event == "window_completed":
                message = (
                    f"Server completed a window; "
                    f"{completed:,}/{window_total:,} complete"
                )
            elif event.event == "retry_wait":
                window_number = data.get("window_index")
                window_text = (
                    f" for window {int(window_number) + 1:,}/{int(data['window_count']):,}"
                    if window_number is not None
                    else ""
                )
                message = (
                    f"Transient provider failure{window_text}; retrying attempt "
                    f"{int(data['next_attempt']):,} after "
                    f"{int(data['delay_ms']) / 1000:g}s"
                )
            elif event.event == "heartbeat":
                heartbeat_completed = int(data.get("completed_windows", completed))
                if int(data.get("window_count", 0)) > 0:
                    completed = heartbeat_completed
                    message = (
                        f"Server is working; {completed:,}/{window_total:,} "
                        f"windows complete, {int(data['active_windows']):,} active"
                    )
                else:
                    message = f"Server is working on {data['operation']}"
            elif event.event == "window_output_unusable":
                message = (
                    f"Window {int(data['window_index']) + 1:,}/{int(data['window_count']):,} "
                    f"returned unusable output after {int(data['attempt']):,} provider attempt(s)"
                )
            elif event.event == "window_unavailable":
                message = (
                    f"Window {int(data['window_index']) + 1:,}/{int(data['window_count']):,} "
                    f"is unavailable ({data['code']}); retained results remain visible"
                )
            elif event.event == "warning":
                message = f"Server warning: {data['code']}"
            elif event.event == "synthesis_validation_completed":
                message = f"Synthesis validation: {data['status']}"
            else:
                message = f"Server: {event.event}"
            report(
                ConversationalSearchProgress(
                    event.event,
                    completed,
                    window_total,
                    message,
                )
            )
        if result is None:
            raise RemoteGatewayError("conversation stream ended without completion", interrupted=True)
        self.store.write(self._persist_visible_result, scope, question, result)
        report(
            ConversationalSearchProgress(
                "completed",
                window_total,
                window_total,
                "Conversational search completed",
            )
        )
        return ConversationalExecutionResult(result)

    def _prepare_analysis_context(
        self,
        scope: NarrowedSearchScope,
        question: str,
        *,
        cancellation: RequestCancellation | None,
        progress: Callable[[ConversationalSearchProgress], None],
    ) -> dict[str, Any]:
        """Execute the frozen server plan and return the complete analysis context."""
        if cancellation is not None:
            cancellation.checkpoint()
        plan_kwargs: dict[str, Any] = {}
        if cancellation is not None:
            plan_kwargs["cancellation"] = cancellation
        plan = self.gateway.conversational_plan(question, **plan_kwargs)
        try:
            validate_analysis_plan(plan)
        except ValueError as exc:
            raise RemoteGatewayError("Server returned an invalid analysis plan") from exc
        plan_queries = plan["retrieval_queries"]
        policy = plan["search_policy"]
        if policy["mode"] == "none":
            context = {
                "analysis_plan_id": plan["analysis_plan_id"],
                "plan_config_version": plan["config_version"],
                "compatibility_fingerprint": plan["compatibility_fingerprint"],
                "analysis_plan": plan["analysis_plan"],
                "retrieval_queries": plan_queries,
                "embedding": None,
                "search_policy": policy,
                "hits": [],
            }
            try:
                validate_analysis_context(context)
            except ValueError as exc:
                raise RemoteGatewayError("Client constructed an invalid none-mode analysis context") from exc
            return context
        plan_embedding = plan["embedding"]
        if plan_embedding is None:
            raise RemoteGatewayError("Semantic analysis plan omitted embedding metadata")
        local_geometry = self.store.read(
            lambda conn: self._message_embedding_geometry(conn, scope)
        )
        if cancellation is not None:
            cancellation.checkpoint()
        progress(
            ConversationalSearchProgress(
                "query_embeddings",
                0,
                len(plan_queries),
                f"Embedding {len(plan_queries):,} retrieval queries in one workload",
            )
        )
        items = [
            {"message_id": str(query["query_id"]), "text": str(query["text"])}
            for query in plan_queries
        ]
        embedding_kwargs: dict[str, Any] = {}
        if cancellation is not None:
            embedding_kwargs["cancellation"] = cancellation
        events = self.gateway.embeddings(items, **embedding_kwargs)
        try:
            accepted_event = next(events)
        except StopIteration as exc:
            raise RemoteGatewayError("Query embedding stream ended before acceptance") from exc
        if accepted_event.event == "failed":
            self._raise_stream_failure(accepted_event)
        if accepted_event.event != "accepted":
            raise RemoteGatewayError("Query embedding stream did not begin with acceptance")
        accepted = dict(accepted_event.value["data"])
        self._verify_embedding_geometry(accepted, plan_embedding, local_geometry)
        vectors: dict[str, list[float]] = {}
        expected_query_ids = {str(query["query_id"]) for query in plan_queries}
        terminal_seen = False
        for event in events:
            if event.event == "vector_batch":
                for item in event.value["data"]["items"]:
                    query_id = str(item["message_id"])
                    if query_id not in expected_query_ids:
                        raise RemoteGatewayError("Query embedding stream returned an unknown query ID")
                    if query_id in vectors:
                        raise RemoteGatewayError("Query embedding stream returned a duplicate query ID")
                    vector = [float(value) for value in item["vector"]]
                    if len(vector) != int(plan_embedding["dimensions"]) or any(not math.isfinite(value) for value in vector):
                        raise RemoteGatewayError("Query embedding stream returned invalid geometry")
                    vectors[query_id] = vector
                    progress(
                        ConversationalSearchProgress(
                            "query_embeddings",
                            len(vectors),
                            len(plan_queries),
                            f"Received {len(vectors):,}/{len(plan_queries):,} query vectors",
                        )
                    )
            elif event.event == "failed":
                self._raise_stream_failure(event)
            elif event.event == "completed":
                if int(event.value["result"]["total_items"]) != len(plan_queries):
                    raise RemoteGatewayError("Query embedding terminal count does not match the plan")
                terminal_seen = True
        if not terminal_seen or set(vectors) != expected_query_ids:
            raise RemoteGatewayError("Query embedding stream did not return every planned query")
        progress(ConversationalSearchProgress("local_candidates", 0, len(plan_queries), "Searching the selected EVW revision"))
        hits: list[dict[str, Any]] = []
        for index, query in enumerate(plan_queries, start=1):
            if cancellation is not None:
                cancellation.checkpoint()
            query_id = str(query["query_id"])
            query_hits = self.store.read(
                lambda conn, vector=vectors[query_id]: ClientWorkflowService(
                    conn, self.logger, self.gateway
                ).message_embedding_candidates_with_vector(
                    scope,
                    vector,
                    int(plan_embedding["dimensions"]),
                    top_k=int(policy["top_k_per_query"]),
                )
            )
            hits.extend(
                {
                    "query_id": query_id,
                    "message_id": str(hit["message_id"]),
                    "rank": int(hit["rank"]),
                    "distance": float(hit["distance"]),
                }
                for hit in query_hits
            )
            progress(
                ConversationalSearchProgress(
                    "local_candidates",
                    index,
                    len(plan_queries),
                    f"Retrieved candidates for query {index:,}/{len(plan_queries):,}",
                )
            )
        context = {
            "analysis_plan_id": plan["analysis_plan_id"],
            "plan_config_version": plan["config_version"],
            "compatibility_fingerprint": plan["compatibility_fingerprint"],
            "analysis_plan": plan["analysis_plan"],
            "retrieval_queries": plan_queries,
            "embedding": plan_embedding,
            "search_policy": policy,
            "hits": hits,
        }
        try:
            validate_analysis_context(context)
        except ValueError as exc:
            raise RemoteGatewayError("Client constructed an invalid semantic analysis context") from exc
        return context

    @staticmethod
    def _message_embedding_geometry(
        conn: sqlite3.Connection,
        scope: NarrowedSearchScope,
    ) -> dict[str, Any]:
        _require_scope(conn, scope.working_corpus)
        row = conn.execute(
            """SELECT message_embedding_status
                 FROM working_corpus_revision_index
                WHERE working_corpus_revision_id=? AND index_generation=?""",
            (scope.working_corpus_revision_id, scope.index_generation),
        ).fetchone()
        state = conn.execute(
            "SELECT dimensions,normalization FROM embedding_cache_state WHERE cache_id=1"
        ).fetchone()
        if row is None or str(row[0]) != "ready":
            raise RuntimeError("message embedding index is not ready")
        if state is None:
            raise RuntimeError("EMBEDDING_CACHE_GEOMETRY_MISMATCH")
        return {"dimensions": int(state[0]), "normalization": str(state[1])}

    @staticmethod
    def _verify_embedding_geometry(
        accepted: dict[str, Any],
        plan_embedding: dict[str, Any],
        local_geometry: dict[str, Any],
    ) -> None:
        expected = {
            "embedding_profile_id": str(plan_embedding["embedding_profile_id"]),
            "artifact_fingerprint": str(plan_embedding["artifact_fingerprint"]),
            "dimensions": int(plan_embedding["dimensions"]),
            "normalization": str(plan_embedding["normalization"]),
        }
        actual = {
            "embedding_profile_id": str(accepted.get("embedding_profile_id", "")),
            "artifact_fingerprint": str(accepted.get("artifact_fingerprint", "")),
            "dimensions": int(accepted.get("dimensions", -1)),
            "normalization": str(accepted.get("normalization", "")),
        }
        if actual != expected or local_geometry != {
            "dimensions": expected["dimensions"],
            "normalization": expected["normalization"],
        }:
            raise RuntimeError("EMBEDDING_CACHE_GEOMETRY_MISMATCH")

    @staticmethod
    def _raise_stream_failure(event: Any) -> None:
        error = event.value.get("error", {})
        raise RemoteGatewayError(
            str(error.get("message", "query embedding failed")),
            error_code=str(error.get("code", "EMBEDDING_ERROR")),
        )

    @staticmethod
    def _remote_scope_id(scope: WorkingCorpusScope) -> str:
        return f"evw15:{scope.working_corpus_id}:{scope.working_corpus_revision_id}:{scope.index_generation}:{scope.scope_hash}"

    @staticmethod
    def _messages(conn: sqlite3.Connection, scope: NarrowedSearchScope) -> list[dict[str, str]]:
        _require_scope(conn, scope.working_corpus)
        predicate, params = scope.sql_predicate(message_alias="m")
        rows = conn.execute(f"SELECT m.message_id,m.source_thread_id,m.timestamp,m.sender_display,m.body FROM message m WHERE m.dataset_id=? AND {predicate} ORDER BY m.timestamp,m.sort_index,m.message_id", (scope.dataset_id, *params)).fetchall()
        return [{"message_id": str(r["message_id"]), "thread_id": str(r["source_thread_id"]), "timestamp": str(r["timestamp"]), "sender": str(r["sender_display"]), "text": str(r["body"])} for r in rows]

    @staticmethod
    def _persist_visible_result(conn: sqlite3.Connection, scope: NarrowedSearchScope, prompt: str, result: dict[str, Any]) -> None:
        repo = WorkingCorpusRepository(conn)
        repo.validate_ready_scope(scope.working_corpus)
        now = utc_now_iso()
        completion_status = str(result["completion_status"])
        presented_answer = format_conversational_result(result)
        conversation_id = int(conn.execute(
            "INSERT INTO conversation(dataset_id,working_corpus_id,working_corpus_revision_id,index_generation,scope_hash,created_at,status) VALUES (?,?,?,?,?,?,?)",
            (
                scope.dataset_id,
                scope.working_corpus_id,
                scope.working_corpus_revision_id,
                scope.index_generation,
                scope.working_corpus.scope_hash,
                now,
                completion_status,
            ),
        ).lastrowid)
        turn_id = int(conn.execute(
            "INSERT INTO conversation_turn(conversation_id,working_corpus_id,working_corpus_revision_id,index_generation,scope_hash,user_prompt,presented_answer,mode,status,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                conversation_id,
                scope.working_corpus_id,
                scope.working_corpus_revision_id,
                scope.index_generation,
                scope.working_corpus.scope_hash,
                prompt,
                presented_answer,
                str(result.get("strategy", "conversation")),
                completion_status,
                now,
            ),
        ).lastrowid)
        for item in result.get("evidence_ranges", result.get("evidence_ledger", [])) or []:
            message_id = item.get("start_message_id")
            if message_id and conn.execute("SELECT 1 FROM working_corpus_revision_message WHERE working_corpus_revision_id=? AND message_id=?", (scope.working_corpus_revision_id, message_id)).fetchone():
                conn.execute("INSERT INTO conversation_citation(conversation_turn_id,message_id,citation_type) VALUES (?,?,?)", (turn_id, message_id, "range_start"))
