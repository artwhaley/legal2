"""Typed repository for durable named working corpora and immutable revisions."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from typing import Iterable

from message_evidence_workstation.domain.constants import WORKING_CORPUS_TOKEN_LIMIT
from message_evidence_workstation.domain.search_scope import (
    TOKENIZER_ID,
    WorkingCorpusScope,
    count_tokens,
    membership_digest_for_rows,
)
from message_evidence_workstation.logging_ui.diagnostic_logger import DiagnosticLogger, utc_now_iso


class WorkingCorpusError(RuntimeError):
    code = "WORKING_CORPUS_ERROR"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code:
            self.code = code


class WorkingCorpusNotFoundError(WorkingCorpusError):
    code = "WORKING_CORPUS_NOT_FOUND"


class WorkingCorpusRevisionNotFoundError(WorkingCorpusError):
    code = "WORKING_CORPUS_REVISION_NOT_FOUND"


class WorkingCorpusNoPublishedError(WorkingCorpusError):
    code = "WORKING_CORPUS_NO_PUBLISHED_REVISION"


class WorkingCorpusRevisionNotReadyError(WorkingCorpusError):
    code = "WORKING_CORPUS_REVISION_NOT_READY"


class WorkingCorpusRevisionStaleError(WorkingCorpusError):
    code = "WORKING_CORPUS_REVISION_STALE"


class WorkingCorpusIndexNotReadyError(WorkingCorpusError):
    code = "WORKING_CORPUS_INDEX_NOT_READY"


class WorkingCorpusDefinitionError(WorkingCorpusError):
    code = "WORKING_CORPUS_DEFINITION_INVALID"


class WorkingCorpusOverLimitError(WorkingCorpusError):
    code = "WORKING_CORPUS_OVER_LIMIT"


class WorkingCorpusEmptyError(WorkingCorpusError):
    code = "WORKING_CORPUS_EMPTY"


class WorkingCorpusBaseChangedError(WorkingCorpusError):
    code = "WORKING_CORPUS_BASE_CHANGED"


class EvidenceCompatibilityError(WorkingCorpusError):
    code = "EVIDENCE_COMPATIBILITY_REQUIRED"


@dataclass(frozen=True, slots=True)
class WorkingCorpusSummary:
    working_corpus_id: int
    dataset_id: int
    name: str
    current_revision_id: int | None
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class WorkingCorpusRevisionSummary:
    working_corpus_revision_id: int
    working_corpus_id: int
    revision_number: int
    base_revision_id: int | None
    selection_mode: str
    start_date: str | None
    end_date: str | None
    token_limit: int
    estimated_tokens: int
    message_count: int
    tokenizer_id: str
    scope_hash: str
    dataset_content_revision: int
    status: str
    last_error: str | None
    built_at: str | None
    is_current: bool
    lexical_generation: int | None
    message_embedding_status: str | None
    chunk_embedding_status: str | None


@dataclass(frozen=True, slots=True)
class WorkingCorpusDefinition:
    working_corpus_revision_id: int
    selection_mode: str
    start_date: str | None
    end_date: str | None
    source_names: tuple[str, ...]
    source_thread_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EvidenceCompatibilityConflict:
    evidence_block_id: int
    missing_message_ids: tuple[str, ...]
    changed_message_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EvidenceCompatibilityReport:
    base_revision_id: int | None
    candidate_revision_id: int
    incompatible_block_ids: frozenset[int]
    conflicts: tuple[EvidenceCompatibilityConflict, ...]


def _scope_hash(dataset_revision: int, definition: WorkingCorpusDefinition, rows: list[tuple[str, int]], tokenizer_id: str) -> str:
    digest = hashlib.sha256()
    values = (
        str(dataset_revision), definition.selection_mode, definition.start_date or "",
        definition.end_date or "", tokenizer_id, *definition.source_names,
        *definition.source_thread_ids, membership_digest_for_rows(rows),
    )
    for value in values:
        digest.update(value.encode("utf-8"))
        digest.update(b"\x1f")
    return digest.hexdigest()


class WorkingCorpusRepository:
    def __init__(self, conn: sqlite3.Connection, logger: DiagnosticLogger | None = None) -> None:
        self.conn = conn
        self.logger = logger

    def create_working_corpus(self, *, dataset_id: int, name: str) -> int:
        if not str(name).strip():
            raise WorkingCorpusDefinitionError("Working corpus name must be nonblank")
        if self.conn.execute("SELECT 1 FROM dataset WHERE dataset_id=?", (dataset_id,)).fetchone() is None:
            raise WorkingCorpusNotFoundError(f"Dataset {dataset_id} not found")
        now = utc_now_iso()
        return int(self.conn.execute(
            "INSERT INTO working_corpus(dataset_id,name,created_at,updated_at) VALUES (?,?,?,?)",
            (dataset_id, str(name).strip(), now, now),
        ).lastrowid)

    def rename_working_corpus(self, *, working_corpus_id: int, name: str) -> None:
        if not str(name).strip():
            raise WorkingCorpusDefinitionError("Working corpus name must be nonblank")
        self._require_corpus(working_corpus_id)
        self.conn.execute("UPDATE working_corpus SET name=?,updated_at=? WHERE working_corpus_id=?", (str(name).strip(), utc_now_iso(), working_corpus_id))

    def list_working_corpora(self, dataset_id: int) -> list[WorkingCorpusSummary]:
        rows = self.conn.execute("SELECT * FROM working_corpus WHERE dataset_id=? ORDER BY created_at,working_corpus_id", (dataset_id,)).fetchall()
        return [WorkingCorpusSummary(int(r["working_corpus_id"]), int(r["dataset_id"]), str(r["name"]), int(r["current_revision_id"]) if r["current_revision_id"] is not None else None, str(r["created_at"]), str(r["updated_at"])) for r in rows]

    def list_revisions(self, working_corpus_id: int) -> list[WorkingCorpusRevisionSummary]:
        self._require_corpus(working_corpus_id)
        rows = self.conn.execute(
            """SELECT r.*,wc.current_revision_id,
                      (SELECT MAX(index_generation) FROM working_corpus_revision_index i WHERE i.working_corpus_revision_id=r.working_corpus_revision_id) AS lexical_generation,
                      (SELECT i.message_embedding_status FROM working_corpus_revision_index i WHERE i.working_corpus_revision_id=r.working_corpus_revision_id ORDER BY i.index_generation DESC LIMIT 1) AS message_embedding_status,
                      (SELECT i.chunk_embedding_status FROM working_corpus_revision_index i WHERE i.working_corpus_revision_id=r.working_corpus_revision_id ORDER BY i.index_generation DESC LIMIT 1) AS chunk_embedding_status
                 FROM working_corpus_revision r JOIN working_corpus wc ON wc.working_corpus_id=r.working_corpus_id
                WHERE r.working_corpus_id=? ORDER BY r.revision_number""", (working_corpus_id,)
        ).fetchall()
        return [WorkingCorpusRevisionSummary(
            int(r["working_corpus_revision_id"]), int(r["working_corpus_id"]), int(r["revision_number"]), int(r["base_revision_id"]) if r["base_revision_id"] is not None else None,
            str(r["selection_mode"]), r["start_date"], r["end_date"], int(r["token_limit"]), int(r["estimated_tokens"]), int(r["message_count"]), str(r["tokenizer_id"]), str(r["scope_hash"]), int(r["dataset_content_revision"]), str(r["status"]), r["last_error"], r["built_at"], r["current_revision_id"] == r["working_corpus_revision_id"], int(r["lexical_generation"]) if r["lexical_generation"] is not None else None, r["message_embedding_status"], r["chunk_embedding_status"]
        ) for r in rows]

    def create_draft_revision(self, *, working_corpus_id: int, base_revision_id: int | None) -> int:
        corpus = self._require_corpus(working_corpus_id)
        if base_revision_id is not None:
            base = self._require_revision(base_revision_id)
            if int(base["working_corpus_id"]) != working_corpus_id or int(corpus["current_revision_id"] or 0) != base_revision_id:
                raise WorkingCorpusDefinitionError("A draft must be based on the corpus current revision")
        number = int(self.conn.execute("SELECT COALESCE(MAX(revision_number),0)+1 FROM working_corpus_revision WHERE working_corpus_id=?", (working_corpus_id,)).fetchone()[0])
        dataset_revision = int(self.conn.execute("SELECT content_revision FROM dataset WHERE dataset_id=?", (corpus["dataset_id"],)).fetchone()[0])
        now = utc_now_iso()
        cursor = self.conn.execute(
            """INSERT INTO working_corpus_revision(working_corpus_id,revision_number,base_revision_id,selection_mode,start_date,end_date,token_limit,estimated_tokens,message_count,tokenizer_id,scope_hash,dataset_content_revision,status,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (working_corpus_id, number, base_revision_id, "all", None, None, WORKING_CORPUS_TOKEN_LIMIT, 0, 0, TOKENIZER_ID, "", dataset_revision, "draft", now),
        )
        revision_id = int(cursor.lastrowid)
        if base_revision_id is not None:
            self.conn.execute("INSERT INTO working_corpus_revision_source SELECT ?,source_name FROM working_corpus_revision_source WHERE working_corpus_revision_id=?", (revision_id, base_revision_id))
            self.conn.execute("INSERT INTO working_corpus_revision_thread SELECT ?,source_thread_id FROM working_corpus_revision_thread WHERE working_corpus_revision_id=?", (revision_id, base_revision_id))
            self.conn.execute("UPDATE working_corpus_revision SET selection_mode=(SELECT selection_mode FROM working_corpus_revision WHERE working_corpus_revision_id=?),start_date=(SELECT start_date FROM working_corpus_revision WHERE working_corpus_revision_id=?),end_date=(SELECT end_date FROM working_corpus_revision WHERE working_corpus_revision_id=?),tokenizer_id=(SELECT tokenizer_id FROM working_corpus_revision WHERE working_corpus_revision_id=?) WHERE working_corpus_revision_id=?", (base_revision_id, base_revision_id, base_revision_id, base_revision_id, revision_id))
        return revision_id

    def replace_draft_definition(self, *, working_corpus_revision_id: int, selection_mode: str, start_date: str | None, end_date: str | None, source_names: Iterable[str], source_thread_ids: Iterable[str]) -> None:
        revision = self._require_revision(working_corpus_revision_id)
        if revision["status"] != "draft":
            raise WorkingCorpusDefinitionError("Only a draft revision definition is editable")
        if selection_mode not in {"all", "selected"}:
            raise WorkingCorpusDefinitionError("selection_mode must be all or selected")
        if start_date and end_date and end_date < start_date:
            raise WorkingCorpusDefinitionError("end_date cannot precede start_date")
        names = tuple(sorted({str(v).strip() for v in source_names if str(v).strip()}))
        threads = tuple(sorted({str(v).strip() for v in source_thread_ids if str(v).strip()}))
        if selection_mode == "all" and (names or threads):
            raise WorkingCorpusDefinitionError("all selection cannot include source filters")
        if selection_mode == "selected" and not (names or threads):
            raise WorkingCorpusDefinitionError("selected selection requires a source or thread")
        dataset_id = int(self.conn.execute("SELECT dataset_id FROM working_corpus WHERE working_corpus_id=?", (revision["working_corpus_id"],)).fetchone()[0])
        unknown = [v for v in threads if self.conn.execute("SELECT 1 FROM source_thread WHERE source_thread_id=? AND dataset_id=?", (v, dataset_id)).fetchone() is None]
        if unknown:
            raise WorkingCorpusDefinitionError(f"Unknown source thread IDs: {unknown}")
        self.conn.execute("DELETE FROM working_corpus_revision_source WHERE working_corpus_revision_id=?", (working_corpus_revision_id,))
        self.conn.execute("DELETE FROM working_corpus_revision_thread WHERE working_corpus_revision_id=?", (working_corpus_revision_id,))
        self.conn.executemany("INSERT INTO working_corpus_revision_source VALUES (?,?)", [(working_corpus_revision_id, v) for v in names])
        self.conn.executemany("INSERT INTO working_corpus_revision_thread VALUES (?,?)", [(working_corpus_revision_id, v) for v in threads])
        self.conn.execute("UPDATE working_corpus_revision SET selection_mode=?,start_date=?,end_date=? WHERE working_corpus_revision_id=?", (selection_mode, start_date, end_date, working_corpus_revision_id))

    def get_revision_definition(self, working_corpus_revision_id: int) -> WorkingCorpusDefinition:
        r = self._require_revision(working_corpus_revision_id)
        names = tuple(str(x[0]) for x in self.conn.execute("SELECT source_name FROM working_corpus_revision_source WHERE working_corpus_revision_id=? ORDER BY source_name", (working_corpus_revision_id,)))
        threads = tuple(str(x[0]) for x in self.conn.execute("SELECT source_thread_id FROM working_corpus_revision_thread WHERE working_corpus_revision_id=? ORDER BY source_thread_id", (working_corpus_revision_id,)))
        return WorkingCorpusDefinition(working_corpus_revision_id, str(r["selection_mode"]), r["start_date"], r["end_date"], names, threads)

    def build_revision(self, working_corpus_revision_id: int) -> WorkingCorpusScope:
        r = self._require_revision(working_corpus_revision_id)
        if r["status"] != "draft":
            raise WorkingCorpusDefinitionError("Only a draft revision can be built")
        corpus = self._require_corpus(int(r["working_corpus_id"]))
        dataset_id = int(corpus["dataset_id"])
        definition = self.get_revision_definition(working_corpus_revision_id)
        self.conn.execute("UPDATE working_corpus_revision SET status='building',last_error=NULL WHERE working_corpus_revision_id=?", (working_corpus_revision_id,))
        now = utc_now_iso()
        generation = int(self.conn.execute("SELECT COALESCE(MAX(index_generation),0)+1 FROM working_corpus_revision_index WHERE working_corpus_revision_id=?", (working_corpus_revision_id,)).fetchone()[0])
        self.conn.execute("INSERT INTO working_corpus_revision_index(working_corpus_revision_id,index_generation,dataset_content_revision,status,created_at,updated_at) VALUES (?,?,?,?,?,?)", (working_corpus_revision_id, generation, int(self.conn.execute("SELECT content_revision FROM dataset WHERE dataset_id=?", (dataset_id,)).fetchone()[0]), "building", now, now))
        try:
            clauses = ["m.dataset_id=?"]
            params: list[object] = [dataset_id]
            if definition.start_date:
                clauses.append("date(m.timestamp) >= date(?)"); params.append(definition.start_date)
            if definition.end_date:
                clauses.append("date(m.timestamp) <= date(?)"); params.append(definition.end_date)
            if definition.source_names:
                placeholders = ",".join("?" for _ in definition.source_names)
                clauses.append(f"m.source_platform IN ({placeholders})"); params.extend(definition.source_names)
            if definition.source_thread_ids:
                placeholders = ",".join("?" for _ in definition.source_thread_ids)
                clauses.append(f"m.source_thread_id IN ({placeholders})"); params.extend(definition.source_thread_ids)
            rows = self.conn.execute("SELECT m.message_id,m.source_thread_id,m.token_count FROM message m WHERE " + " AND ".join(clauses) + " ORDER BY m.timestamp,m.sort_index,m.message_id", params).fetchall()
            token_rows = [(str(row["message_id"]), int(row["token_count"])) for row in rows]
            total = sum(v for _, v in token_rows)
            if total > WORKING_CORPUS_TOKEN_LIMIT:
                self.conn.execute("DELETE FROM working_corpus_revision_index WHERE working_corpus_revision_id=? AND index_generation=?", (working_corpus_revision_id, generation))
                self.conn.execute("UPDATE working_corpus_revision SET status='failed',estimated_tokens=?,message_count=?,last_error=? WHERE working_corpus_revision_id=?", (total, len(rows), f"WORKING_CORPUS_OVER_LIMIT: {total:,} > {WORKING_CORPUS_TOKEN_LIMIT:,}", working_corpus_revision_id))
                raise WorkingCorpusOverLimitError(f"Working corpus revision contains {total:,} tokens; limit is {WORKING_CORPUS_TOKEN_LIMIT:,}")
            self.conn.executemany("INSERT INTO working_corpus_revision_message(working_corpus_revision_id,message_id,source_thread_id,ordinal,token_count,embedding_input_hash) SELECT ?,m.message_id,m.source_thread_id,?,?,m.embedding_input_hash FROM message m WHERE m.message_id=?", [(working_corpus_revision_id, ordinal, token_count, message_id) for ordinal, (message_id, token_count) in enumerate(token_rows)])
            dataset_revision = int(self.conn.execute("SELECT content_revision FROM dataset WHERE dataset_id=?", (dataset_id,)).fetchone()[0])
            scope_hash = _scope_hash(dataset_revision, definition, token_rows, str(r["tokenizer_id"]))
            from message_evidence_workstation.search.scoped_search import rebuild_fts, rebuild_spellfix
            scope = WorkingCorpusScope(int(r["working_corpus_id"]), working_corpus_revision_id, int(r["revision_number"]), dataset_id, generation, dataset_revision, scope_hash, len(rows), total, str(r["tokenizer_id"]))
            rebuild_fts(self.conn, self.logger, scope)
            rebuild_spellfix(self.conn, self.logger, scope)
            self.conn.execute("UPDATE working_corpus_revision_index SET status='ready',updated_at=? WHERE working_corpus_revision_id=? AND index_generation=?", (utc_now_iso(), working_corpus_revision_id, generation))
            self.conn.execute("UPDATE working_corpus_revision SET status='ready',estimated_tokens=?,message_count=?,scope_hash=?,built_at=?,last_error=NULL WHERE working_corpus_revision_id=?", (total, len(rows), scope_hash, utc_now_iso(), working_corpus_revision_id))
            return scope
        except Exception as exc:
            if not isinstance(exc, WorkingCorpusOverLimitError):
                self.conn.execute("UPDATE working_corpus_revision_index SET status='failed',last_error=?,updated_at=? WHERE working_corpus_revision_id=? AND index_generation=?", (str(exc), utc_now_iso(), working_corpus_revision_id, generation))
                self.conn.execute("UPDATE working_corpus_revision SET status='failed',last_error=? WHERE working_corpus_revision_id=?", (str(exc), working_corpus_revision_id))
            raise

    def require_current_scope(self, *, working_corpus_id: int, dataset_id: int) -> WorkingCorpusScope:
        row = self.conn.execute("SELECT current_revision_id FROM working_corpus WHERE working_corpus_id=? AND dataset_id=?", (working_corpus_id, dataset_id)).fetchone()
        if row is None:
            raise WorkingCorpusNotFoundError(f"Working corpus {working_corpus_id} not found")
        if row[0] is None:
            raise WorkingCorpusNoPublishedError(f"Working corpus {working_corpus_id} has no published revision")
        return self.require_ready_scope(working_corpus_revision_id=int(row[0]), dataset_id=dataset_id)

    def require_ready_scope(self, *, working_corpus_revision_id: int, dataset_id: int) -> WorkingCorpusScope:
        row = self._scope_row(working_corpus_revision_id, dataset_id)
        if row is None:
            raise WorkingCorpusRevisionNotFoundError(f"Working corpus revision {working_corpus_revision_id} not found")
        if int(row["dataset_content_revision"]) != int(row["current_dataset_revision"]):
            raise WorkingCorpusRevisionStaleError("Working corpus revision is stale against canonical dataset content")
        if str(row["status"]) != "ready":
            raise WorkingCorpusRevisionNotReadyError(f"Working corpus revision is {row['status']}")
        if str(row["index_status"]) != "ready" or str(row["fts_status"]) != "ready" or str(row["spellfix_status"]) != "ready":
            raise WorkingCorpusIndexNotReadyError("Working corpus lexical index is not ready")
        scope = self._scope_from_row(row)
        self.validate_ready_scope(scope)
        return scope

    def validate_ready_scope(self, scope: WorkingCorpusScope) -> None:
        row = self._scope_row(scope.working_corpus_revision_id, scope.dataset_id)
        if row is None or str(row["scope_hash"]) != scope.scope_hash or int(row["index_generation"]) != scope.index_generation or int(row["message_count"]) != scope.message_count or int(row["estimated_tokens"]) != scope.estimated_tokens:
            raise WorkingCorpusRevisionNotReadyError("Captured working corpus scope no longer validates")

    def assess_evidence_compatibility(self, *, base_revision_id: int | None, candidate_revision_id: int) -> EvidenceCompatibilityReport:
        if base_revision_id is None:
            return EvidenceCompatibilityReport(None, candidate_revision_id, frozenset(), ())
        blocks = self.conn.execute("SELECT evidence_block_id FROM working_corpus_revision_evidence_block WHERE working_corpus_revision_id=?", (base_revision_id,)).fetchall()
        conflicts: list[EvidenceCompatibilityConflict] = []
        for block in blocks:
            block_id = int(block[0])
            missing = tuple(str(x[0]) for x in self.conn.execute("SELECT message_id FROM evidence_block_message WHERE evidence_block_id=? AND message_id NOT IN (SELECT message_id FROM working_corpus_revision_message WHERE working_corpus_revision_id=?)", (block_id, candidate_revision_id)))
            if missing:
                conflicts.append(EvidenceCompatibilityConflict(block_id, missing))
        return EvidenceCompatibilityReport(base_revision_id, candidate_revision_id, frozenset(c.evidence_block_id for c in conflicts), tuple(conflicts))

    def publish_revision(self, *, working_corpus_id: int, working_corpus_revision_id: int, excluded_evidence_block_ids: frozenset[int]) -> WorkingCorpusScope:
        row = self._require_revision(working_corpus_revision_id)
        corpus = self._require_corpus(working_corpus_id)
        if int(row["working_corpus_id"]) != working_corpus_id or row["status"] != "ready":
            raise WorkingCorpusRevisionNotReadyError("Candidate revision is not ready for publication")
        if corpus["current_revision_id"] != row["base_revision_id"]:
            raise WorkingCorpusBaseChangedError("Working corpus current revision changed while candidate was built")
        report = self.assess_evidence_compatibility(base_revision_id=int(row["base_revision_id"]) if row["base_revision_id"] is not None else None, candidate_revision_id=working_corpus_revision_id)
        if excluded_evidence_block_ids != report.incompatible_block_ids:
            raise EvidenceCompatibilityError(f"Explicit evidence exclusions must equal {sorted(report.incompatible_block_ids)}")
        for block_id in report.incompatible_block_ids:
            self.conn.execute("INSERT INTO workspace_event(event_type,dataset_id,details_json,created_at) VALUES (?,?,?,?)", ("working_corpus_revision_evidence_excluded", corpus["dataset_id"], json.dumps({"working_corpus_id": working_corpus_id, "candidate_revision_id": working_corpus_revision_id, "evidence_block_id": block_id}), utc_now_iso()))
        self.conn.execute("INSERT OR IGNORE INTO working_corpus_revision_evidence_block(working_corpus_revision_id,evidence_block_id,inherited_from_revision_id,associated_at) SELECT ?,evidence_block_id,?,? FROM working_corpus_revision_evidence_block WHERE working_corpus_revision_id=? AND evidence_block_id NOT IN ({})".format(",".join("?" for _ in excluded_evidence_block_ids) or "NULL"), (working_corpus_revision_id, row["base_revision_id"], utc_now_iso(), row["base_revision_id"], *excluded_evidence_block_ids)) if row["base_revision_id"] is not None else None
        self.conn.execute("UPDATE working_corpus SET current_revision_id=?,updated_at=? WHERE working_corpus_id=?", (working_corpus_revision_id, utc_now_iso(), working_corpus_id))
        return self.require_ready_scope(working_corpus_revision_id=working_corpus_revision_id, dataset_id=int(corpus["dataset_id"]))

    def _require_corpus(self, working_corpus_id: int) -> sqlite3.Row:
        row = self.conn.execute("SELECT * FROM working_corpus WHERE working_corpus_id=?", (working_corpus_id,)).fetchone()
        if row is None:
            raise WorkingCorpusNotFoundError(f"Working corpus {working_corpus_id} not found")
        return row

    def _require_revision(self, revision_id: int) -> sqlite3.Row:
        row = self.conn.execute("SELECT * FROM working_corpus_revision WHERE working_corpus_revision_id=?", (revision_id,)).fetchone()
        if row is None:
            raise WorkingCorpusRevisionNotFoundError(f"Working corpus revision {revision_id} not found")
        return row

    def _scope_row(self, revision_id: int, dataset_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            """SELECT r.*,wc.dataset_id AS dataset_id,wc.current_revision_id,d.content_revision AS current_dataset_revision,
                      i.index_generation,i.status AS index_status,i.fts_status,i.spellfix_status
                 FROM working_corpus_revision r JOIN working_corpus wc ON wc.working_corpus_id=r.working_corpus_id
                 JOIN dataset d ON d.dataset_id=wc.dataset_id
                 LEFT JOIN working_corpus_revision_index i ON i.working_corpus_revision_id=r.working_corpus_revision_id
                    AND i.index_generation=(SELECT MAX(index_generation) FROM working_corpus_revision_index WHERE working_corpus_revision_id=r.working_corpus_revision_id)
                WHERE r.working_corpus_revision_id=? AND wc.dataset_id=?""", (revision_id, dataset_id)).fetchone()

    @staticmethod
    def _scope_from_row(row: sqlite3.Row) -> WorkingCorpusScope:
        return WorkingCorpusScope(int(row["working_corpus_id"]), int(row["working_corpus_revision_id"]), int(row["revision_number"]), int(row["dataset_id"]), int(row["index_generation"]), int(row["dataset_content_revision"]), str(row["scope_hash"]), int(row["message_count"]), int(row["estimated_tokens"]), str(row["tokenizer_id"]))
