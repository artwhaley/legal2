"""Domain dataclasses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from message_evidence_workstation.domain.search_scope import WorkingCorpusScope


@dataclass(slots=True)
class Dataset:
    dataset_id: int
    name: str
    created_at: str
    schema_version: int
    notes: str
    content_revision: int


@dataclass(slots=True)
class SourceThread:
    source_thread_id: str
    dataset_id: int
    source_platform: str
    platform_thread_id: str
    display_title: str
    participant_summary: str
    start_ts: str
    end_ts: str
    message_count: int
    metadata_json: dict[str, Any]


@dataclass(slots=True)
class Message:
    message_id: str
    dataset_id: int
    source_thread_id: str
    source_platform: str
    source_message_id: str
    timestamp: str
    sender_id: str
    sender_display: str
    body: str
    body_normalized: str
    has_attachment: bool
    attachment_summary: str
    sort_index: int
    source_metadata_json: dict[str, Any]
    thread_ordinal: int | None = None


@dataclass(slots=True)
class Category:
    category_id: int
    dataset_id: int
    name: str
    description: str
    color: str
    is_collapsed: bool
    created_at: str
    updated_at: str
    is_system: bool = False


@dataclass(slots=True)
class EvidenceBlock:
    evidence_block_id: int
    dataset_id: int
    category_id: int
    source_thread_id: str
    title: str
    summary: str
    context_start_message_id: str
    relevant_start_message_id: str
    core_message_id: str
    relevant_end_message_id: str
    context_end_message_id: str
    origin_kind: str
    origin_working_corpus_revision_id: int | None
    origin_scope_hash: str | None
    message_ids: tuple[str, ...]
    sections: tuple[str, ...]
    highlighted_message_ids: frozenset[str]
    created_by: str
    created_at: str
    updated_at: str

    @property
    def core_hit_message_id(self) -> str:
        return self.core_message_id

    @property
    def context_start_slot(self) -> int:
        return 0

    @property
    def relevant_start_slot(self) -> int:
        return self.message_ids.index(self.relevant_start_message_id)

    @property
    def relevant_end_slot(self) -> int:
        return self.message_ids.index(self.relevant_end_message_id) + 1

    @property
    def context_end_slot(self) -> int:
        return len(self.message_ids)

    def leading_context_message_ids(self, ordered_message_ids: list[str]) -> list[str]:
        del ordered_message_ids
        return [m for m, section in zip(self.message_ids, self.sections) if section == "leading_context"]

    def relevant_message_ids(self, ordered_message_ids: list[str]) -> list[str]:
        del ordered_message_ids
        return [m for m, section in zip(self.message_ids, self.sections) if section == "relevant"]

    def trailing_context_message_ids(self, ordered_message_ids: list[str]) -> list[str]:
        del ordered_message_ids
        return [m for m, section in zip(self.message_ids, self.sections) if section == "trailing_context"]


@dataclass(slots=True)
class DiagnosticEntry:
    event_id: int
    dataset_id: int | None
    timestamp: str
    severity: str
    component: str
    operation: str
    message: str
    details_json: dict[str, Any] | None
    exception_type: str | None
    stack_trace: str | None


@dataclass(slots=True)
class PrintableArtifactGroup:
    printable_artifact_group_id: int
    dataset_id: int
    name: str
    sort_order: int
    is_collapsed: bool
    created_at: str
    updated_at: str


@dataclass(slots=True)
class PrintableArtifact:
    printable_artifact_id: int
    dataset_id: int
    group_id: int
    title: str
    exhibit_number: str
    case_number: str
    sort_order: int
    created_at: str
    updated_at: str


@dataclass(slots=True)
class PrintableArtifactEvidenceBlock:
    printable_artifact_evidence_block_id: int
    printable_artifact_id: int
    evidence_block_id: int
    sort_order: int
    created_at: str


@dataclass(slots=True)
class PrintableArtifactBlockContext:
    join: PrintableArtifactEvidenceBlock
    evidence_block: EvidenceBlock
    block_label: str
    messages: list[Message]
    source_thread: SourceThread | None
    dataset_name: str


@dataclass(slots=True)
class PrintableArtifactContext:
    artifact: PrintableArtifact
    group_name: str
    dataset_name: str
    blocks: list[PrintableArtifactBlockContext]
