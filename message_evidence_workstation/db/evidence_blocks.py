"""Exact message-ID evidence-block persistence for EVW v15."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Iterable

from message_evidence_workstation.domain.models import EvidenceBlock
from message_evidence_workstation.domain.search_scope import WorkingCorpusScope
from message_evidence_workstation.logging_ui.diagnostic_logger import utc_now_iso


class EvidenceBlockError(RuntimeError):
    pass


def _message_hash(row: sqlite3.Row) -> str:
    payload = json.dumps([str(row["message_id"]), str(row["timestamp"]), str(row["sender_display"]), str(row["body"])], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _row_to_block(conn: sqlite3.Connection, row: sqlite3.Row) -> EvidenceBlock:
    messages = conn.execute("SELECT ebm.message_id,ebm.section FROM evidence_block_message ebm WHERE ebm.evidence_block_id=? ORDER BY ebm.ordinal", (row["evidence_block_id"],)).fetchall()
    highlights = frozenset(str(r[0]) for r in conn.execute("SELECT message_id FROM evidence_block_highlight WHERE evidence_block_id=?", (row["evidence_block_id"],)))
    return EvidenceBlock(
        evidence_block_id=int(row["evidence_block_id"]), dataset_id=int(row["dataset_id"]), category_id=int(row["category_id"]), source_thread_id=str(row["source_thread_id"]), title=str(row["title"]), summary=str(row["summary"]),
        context_start_message_id=str(row["context_start_message_id"]), relevant_start_message_id=str(row["relevant_start_message_id"]), core_message_id=str(row["core_message_id"]), relevant_end_message_id=str(row["relevant_end_message_id"]), context_end_message_id=str(row["context_end_message_id"]),
        origin_kind=str(row["origin_kind"]), origin_working_corpus_revision_id=int(row["origin_working_corpus_revision_id"]) if row["origin_working_corpus_revision_id"] is not None else None, origin_scope_hash=row["origin_scope_hash"],
        message_ids=tuple(str(r[0]) for r in messages), sections=tuple(str(r[1]) for r in messages), highlighted_message_ids=highlights,
        created_by=str(row["created_by"]), created_at=str(row["created_at"]), updated_at=str(row["updated_at"]),
    )


def _ordered_range(conn: sqlite3.Connection, scope: WorkingCorpusScope, source_thread_id: str, boundary_ids: tuple[str, str, str, str, str]) -> tuple[list[sqlite3.Row], tuple[int, int, int, int, int]]:
    rows = conn.execute("SELECT m.message_id,m.timestamp,m.sender_display,m.body,wcrm.ordinal FROM working_corpus_revision_message wcrm JOIN message m ON m.message_id=wcrm.message_id WHERE wcrm.working_corpus_revision_id=? AND wcrm.source_thread_id=? ORDER BY wcrm.ordinal", (scope.working_corpus_revision_id, source_thread_id)).fetchall()
    positions = {str(row["message_id"]): index for index, row in enumerate(rows)}
    if any(message_id not in positions for message_id in boundary_ids):
        missing = [m for m in boundary_ids if m not in positions]
        raise EvidenceBlockError(f"Evidence boundary messages are not in the captured revision: {missing}")
    indexes = tuple(positions[m] for m in boundary_ids)
    if not (indexes[0] <= indexes[1] <= indexes[2] <= indexes[3] <= indexes[4]):
        raise EvidenceBlockError("Evidence boundaries are out of source-thread order")
    if indexes[0] == indexes[4] or indexes[1] > indexes[3]:
        raise EvidenceBlockError("Evidence context and relevant ranges must be nonempty")
    if not (indexes[1] <= indexes[2] <= indexes[3]):
        raise EvidenceBlockError("Core message must be inside the relevant range")
    return rows[indexes[0] : indexes[4] + 1], indexes


def _insert_block_rows(conn: sqlite3.Connection, block_id: int, rows: list[sqlite3.Row], indexes: tuple[int, int, int, int, int], highlights: Iterable[str]) -> None:
    context_start, relevant_start, _core, relevant_end, context_end = indexes
    for offset, row in enumerate(rows):
        absolute = context_start + offset
        section = "leading_context" if absolute < relevant_start else "relevant" if absolute <= relevant_end else "trailing_context"
        conn.execute("INSERT INTO evidence_block_message(evidence_block_id,message_id,ordinal,section,message_content_hash) VALUES (?,?,?,?,?)", (block_id, row["message_id"], offset, section, _message_hash(row)))
    valid = {str(row["message_id"]) for row in rows}
    for message_id in highlights:
        if message_id not in valid:
            raise EvidenceBlockError(f"Highlight message {message_id} is outside the exact evidence range")
        conn.execute("INSERT INTO evidence_block_highlight(evidence_block_id,message_id) VALUES (?,?)", (block_id, message_id))


def create_evidence_block(*, conn: sqlite3.Connection, scope: WorkingCorpusScope, category_id: int, source_thread_id: str, title: str, summary: str, context_start_message_id: str, relevant_start_message_id: str, core_message_id: str, relevant_end_message_id: str, context_end_message_id: str, highlighted_message_ids: tuple[str, ...], created_by: str) -> EvidenceBlock:
    boundary_ids = (context_start_message_id, relevant_start_message_id, core_message_id, relevant_end_message_id, context_end_message_id)
    rows, indexes = _ordered_range(conn, scope, source_thread_id, boundary_ids)
    now = utc_now_iso()
    block_id = int(conn.execute("INSERT INTO evidence_block(dataset_id,category_id,source_thread_id,title,summary,context_start_message_id,relevant_start_message_id,core_message_id,relevant_end_message_id,context_end_message_id,origin_kind,origin_working_corpus_revision_id,origin_scope_hash,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (scope.dataset_id, category_id, source_thread_id, title, summary, *boundary_ids, "working_corpus_revision", scope.working_corpus_revision_id, scope.scope_hash, created_by, now, now)).lastrowid)
    _insert_block_rows(conn, block_id, rows, indexes, highlighted_message_ids)
    conn.execute("INSERT INTO working_corpus_revision_evidence_block(working_corpus_revision_id,evidence_block_id,associated_at) VALUES (?,?,?)", (scope.working_corpus_revision_id, block_id, now))
    return get_evidence_block(conn, block_id)


def get_evidence_block(conn: sqlite3.Connection, evidence_block_id: int) -> EvidenceBlock:
    row = conn.execute("SELECT * FROM evidence_block WHERE evidence_block_id=?", (evidence_block_id,)).fetchone()
    if row is None:
        raise EvidenceBlockError(f"Evidence block {evidence_block_id} not found")
    return _row_to_block(conn, row)


def list_evidence_blocks(conn: sqlite3.Connection, *, revision_id: int | None = None) -> list[EvidenceBlock]:
    if revision_id is None:
        rows = conn.execute("SELECT * FROM evidence_block ORDER BY evidence_block_id").fetchall()
    else:
        rows = conn.execute("SELECT eb.* FROM evidence_block eb JOIN working_corpus_revision_evidence_block x ON x.evidence_block_id=eb.evidence_block_id WHERE x.working_corpus_revision_id=? ORDER BY eb.evidence_block_id", (revision_id,)).fetchall()
    return [_row_to_block(conn, row) for row in rows]


def associate_evidence_block(*, conn: sqlite3.Connection, working_corpus_revision_id: int, evidence_block_id: int) -> None:
    block = get_evidence_block(conn, evidence_block_id)
    members = {str(row[0]) for row in conn.execute("SELECT message_id FROM working_corpus_revision_message WHERE working_corpus_revision_id=?", (working_corpus_revision_id,))}
    if not set(block.message_ids).issubset(members):
        raise EvidenceBlockError("Evidence block cannot be associated: its exact message range is not fully in the revision")
    conn.execute("INSERT INTO working_corpus_revision_evidence_block(working_corpus_revision_id,evidence_block_id,associated_at) VALUES (?,?,?)", (working_corpus_revision_id, evidence_block_id, utc_now_iso()))


def replace_evidence_block_range(*, conn: sqlite3.Connection, evidence_block_id: int, boundary_ids: tuple[str, str, str, str, str], highlighted_message_ids: tuple[str, ...], detach_revision_ids: frozenset[int]) -> EvidenceBlock:
    current = get_evidence_block(conn, evidence_block_id)
    associated = {int(row[0]) for row in conn.execute("SELECT working_corpus_revision_id FROM working_corpus_revision_evidence_block WHERE evidence_block_id=?", (evidence_block_id,))}
    if not associated.issubset(detach_revision_ids):
        raise EvidenceBlockError(f"Explicit detachment is required for all incompatible revision associations: {sorted(associated)}")
    revision_id = current.origin_working_corpus_revision_id
    if revision_id is None:
        raise EvidenceBlockError("Cannot replace a legacy evidence block without an explicit revision")
    scope_row = conn.execute("SELECT r.*,wc.dataset_id,i.index_generation FROM working_corpus_revision r JOIN working_corpus wc ON wc.working_corpus_id=r.working_corpus_id JOIN working_corpus_revision_index i ON i.working_corpus_revision_id=r.working_corpus_revision_id WHERE r.working_corpus_revision_id=? ORDER BY i.index_generation DESC LIMIT 1", (revision_id,)).fetchone()
    from message_evidence_workstation.db.corpus_repository import WorkingCorpusRepository
    scope = WorkingCorpusRepository(conn).require_ready_scope(working_corpus_revision_id=revision_id, dataset_id=int(scope_row["dataset_id"]))
    rows, indexes = _ordered_range(conn, scope, current.source_thread_id, boundary_ids)
    now = utc_now_iso()
    conn.execute("DELETE FROM evidence_block_message WHERE evidence_block_id=?", (evidence_block_id,))
    conn.execute("DELETE FROM evidence_block_highlight WHERE evidence_block_id=?", (evidence_block_id,))
    conn.execute("UPDATE evidence_block SET context_start_message_id=?,relevant_start_message_id=?,core_message_id=?,relevant_end_message_id=?,context_end_message_id=?,updated_at=? WHERE evidence_block_id=?", (*boundary_ids, now, evidence_block_id))
    _insert_block_rows(conn, evidence_block_id, rows, indexes, highlighted_message_ids)
    for revision in associated - detach_revision_ids:
        conn.execute("DELETE FROM working_corpus_revision_evidence_block WHERE working_corpus_revision_id=? AND evidence_block_id=?", (revision, evidence_block_id))
    return get_evidence_block(conn, evidence_block_id)


def assert_message_deletable(conn: sqlite3.Connection, message_id: str) -> None:
    refs = {int(row[0]) for row in conn.execute("SELECT evidence_block_id FROM evidence_block_message WHERE message_id=?", (message_id,))}
    refs.update(int(row[0]) for row in conn.execute("SELECT evidence_block_id FROM evidence_block WHERE context_start_message_id=? OR relevant_start_message_id=? OR core_message_id=? OR relevant_end_message_id=? OR context_end_message_id=?", (message_id,) * 5))
    citations = {int(row[0]) for row in conn.execute("SELECT conversation_turn_id FROM conversation_citation WHERE message_id=?", (message_id,))}
    if refs or citations:
        raise EvidenceBlockError(f"Message {message_id} is referenced by evidence blocks {sorted(refs)} and citations {sorted(citations)}")
