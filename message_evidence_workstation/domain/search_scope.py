"""Explicit immutable corpus-revision scopes."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

WORKING_CORPUS_TOKEN_LIMIT = 768_000
TOKENIZER_ID = "cl100k_base"


@dataclass(frozen=True, slots=True)
class WorkingCorpusScope:
    working_corpus_id: int
    working_corpus_revision_id: int
    revision_number: int
    dataset_id: int
    index_generation: int
    dataset_content_revision: int
    scope_hash: str
    message_count: int
    estimated_tokens: int
    tokenizer_id: str = TOKENIZER_ID

    def require_within_limit(self) -> None:
        if self.estimated_tokens > WORKING_CORPUS_TOKEN_LIMIT:
            raise ValueError(
                f"Working corpus revision {self.working_corpus_revision_id} contains "
                f"{self.estimated_tokens:,} tokens; the limit is "
                f"{WORKING_CORPUS_TOKEN_LIMIT:,}."
            )


@dataclass(frozen=True, slots=True)
class NarrowedSearchScope:
    working_corpus: WorkingCorpusScope
    start_date: date | None = None
    end_date: date | None = None
    source_thread_ids: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.start_date is not None and self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("Search scope end_date cannot precede start_date")
        object.__setattr__(self, "source_thread_ids", tuple(dict.fromkeys(self.source_thread_ids)))
        self.working_corpus.require_within_limit()

    @property
    def working_corpus_id(self) -> int:
        return self.working_corpus.working_corpus_id

    @property
    def working_corpus_revision_id(self) -> int:
        return self.working_corpus.working_corpus_revision_id

    @property
    def dataset_id(self) -> int:
        return self.working_corpus.dataset_id

    @property
    def index_generation(self) -> int:
        return self.working_corpus.index_generation

    def sql_predicate(self, *, message_alias: str = "m") -> tuple[str, tuple[object, ...]]:
        clauses = [
            f"EXISTS (SELECT 1 FROM working_corpus_revision_message wcrm "
            f"WHERE wcrm.working_corpus_revision_id = ? AND wcrm.message_id = {message_alias}.message_id)",
        ]
        params: list[object] = [self.working_corpus_revision_id]
        if self.start_date is not None:
            clauses.append(f"date({message_alias}.timestamp) >= date(?)")
            params.append(self.start_date.isoformat())
        if self.end_date is not None:
            clauses.append(f"date({message_alias}.timestamp) <= date(?)")
            params.append(self.end_date.isoformat())
        if self.source_thread_ids:
            placeholders = ",".join("?" for _ in self.source_thread_ids)
            clauses.append(f"{message_alias}.source_thread_id IN ({placeholders})")
            params.extend(self.source_thread_ids)
        return " AND ".join(clauses), tuple(params)


def count_tokens(text: str) -> int:
    import tiktoken

    return len(tiktoken.get_encoding(TOKENIZER_ID).encode(text, disallowed_special=()))


def membership_digest_for_rows(rows: list[tuple[str, int]]) -> str:
    import hashlib

    digest = hashlib.sha256()
    for message_id, token_count in rows:
        digest.update(message_id.encode("utf-8"))
        digest.update(b"\x1f")
        digest.update(str(token_count).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()
