"""Explicit working-corpus revision construction."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Iterable

from message_evidence_workstation.db.corpus_repository import WorkingCorpusRepository
from message_evidence_workstation.domain.search_scope import WorkingCorpusScope
from message_evidence_workstation.logging_ui.diagnostic_logger import DiagnosticLogger


@dataclass(frozen=True, slots=True)
class CorpusBuildResult:
    working_corpus_id: int
    working_corpus_revision_id: int
    scope: WorkingCorpusScope
    message_count: int
    token_count: int


def build_working_corpus(
    conn: sqlite3.Connection,
    logger: DiagnosticLogger,
    *,
    dataset_id: int,
    name: str,
    selection_mode: str = "all",
    start_date: str | None = None,
    end_date: str | None = None,
    source_thread_ids: Iterable[str] = (),
    source_names: Iterable[str] = (),
) -> CorpusBuildResult:
    repo = WorkingCorpusRepository(conn, logger)
    corpus_id = repo.create_working_corpus(dataset_id=dataset_id, name=name)
    revision_id = repo.create_draft_revision(working_corpus_id=corpus_id, base_revision_id=None)
    repo.replace_draft_definition(
        working_corpus_revision_id=revision_id,
        selection_mode=selection_mode,
        start_date=start_date,
        end_date=end_date,
        source_names=source_names,
        source_thread_ids=source_thread_ids,
    )
    scope = repo.build_revision(revision_id)
    published = repo.publish_revision(working_corpus_id=corpus_id, working_corpus_revision_id=revision_id, excluded_evidence_block_ids=frozenset())
    return CorpusBuildResult(corpus_id, revision_id, published, published.message_count, published.estimated_tokens)
