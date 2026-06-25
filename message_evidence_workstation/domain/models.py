"""Domain dataclasses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class Dataset:
    dataset_id: int
    name: str
    created_at: str
    schema_version: int
    notes: str


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
    core_hit_message_id: str
    context_start_slot: int
    relevant_start_slot: int
    relevant_end_slot: int
    context_end_slot: int
    highlighted_message_ids: frozenset[str]
    created_by: str
    created_at: str
    updated_at: str

    def leading_context_message_ids(self, ordered_message_ids: list[str]) -> list[str]:
        from message_evidence_workstation.domain.slots import message_ids_for_slot_range

        return message_ids_for_slot_range(
            ordered_message_ids,
            self.context_start_slot,
            self.relevant_start_slot,
        )

    def relevant_message_ids(self, ordered_message_ids: list[str]) -> list[str]:
        from message_evidence_workstation.domain.slots import message_ids_for_slot_range

        return message_ids_for_slot_range(
            ordered_message_ids,
            self.relevant_start_slot,
            self.relevant_end_slot,
        )

    def trailing_context_message_ids(self, ordered_message_ids: list[str]) -> list[str]:
        from message_evidence_workstation.domain.slots import message_ids_for_slot_range

        return message_ids_for_slot_range(
            ordered_message_ids,
            self.relevant_end_slot,
            self.context_end_slot,
        )


@dataclass(slots=True)
class WorkstationConversation:
    workstation_conversation_id: int
    dataset_id: int
    category_id: int
    source_thread_id: str
    primary_hit_message_id: str
    title: str
    user_notes: str
    status: str
    created_by: str
    created_at: str
    updated_at: str


@dataclass(slots=True)
class ConversationHit:
    conversation_hit_id: int
    workstation_conversation_id: int
    message_id: str
    retrieval_method: str
    query_text: str
    matched_term: str
    score: float | None
    rank: int | None
    distance: float | None
    explanation: str
    metadata_json: dict[str, Any]


@dataclass(slots=True)
class ConversationRange:
    conversation_range_id: int
    workstation_conversation_id: int
    lead_in_start_message_id: str | None
    relevant_start_message_id: str | None
    relevant_end_message_id: str | None
    lead_out_end_message_id: str | None
    llm_suggested_json: dict[str, Any]
    user_modified: bool
    locked: bool


@dataclass(slots=True)
class ModelRunSummary:
    model_run_id: int
    dataset_id: int | None
    run_type: str
    model: str
    prompt_template_id: int | None
    prompt_version: int | None
    input_summary: str
    created_at: str
    latency_ms: int | None
    error_type: str | None
    error_message: str | None


@dataclass(slots=True)
class OutputConversationContext:
    conversation: WorkstationConversation
    category_name: str
    thread_display_title: str
    source_platform: str
    messages: list[Message]
    hits: list[ConversationHit]
    hit_message_ids: set[str]
    conversation_range: ConversationRange | None = None
    highlight_overrides: dict[str, str] | None = None
    display_states: dict[str, str] | None = None
    boundary_labels: dict[str, str] | None = None


@dataclass(slots=True)
class ProcessLogEntry:
    process_log_id: int
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
