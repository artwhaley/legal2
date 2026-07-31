"""Strict v4 product, planning, evidence, result, and stream contracts."""

from __future__ import annotations

import math
import re
import uuid
from datetime import datetime
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


MAX_ID_LENGTH = 512
MAX_QUERY_LENGTH = 512
MAX_QUESTION_LENGTH = 20_000
MAX_QUERY_COUNT = 20
FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def _bounded(value: str, *, maximum: int, name: str, nonblank: bool = True, trimmed: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    if nonblank and not value.strip():
        raise ValueError(f"{name} must be nonblank")
    if len(value) > maximum:
        raise ValueError(f"{name} exceeds its length limit")
    if trimmed and value != value.strip():
        raise ValueError(f"{name} must already be trimmed")
    return value


def _nonblank(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonblank string")
    return value


def _fingerprint(value: str, name: str = "fingerprint") -> str:
    if not isinstance(value, str) or FINGERPRINT_RE.fullmatch(value) is None:
        raise ValueError(f"{name} must be 64 lowercase hexadecimal characters")
    return value


def _uuid(value: str, name: str) -> str:
    _bounded(value, maximum=MAX_ID_LENGTH, name=name)
    try:
        uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"{name} must be a UUID") from exc
    return value


def _unique_strings(values: list[str], *, maximum: int, name: str, minimum: int = 0) -> list[str]:
    if len(values) < minimum or len(values) > maximum:
        raise ValueError(f"{name} count is outside its limit")
    for value in values:
        _bounded(value, maximum=maximum if name == "retrieval_queries" else MAX_QUESTION_LENGTH, name=name, trimmed=True)
    if len({value.casefold() for value in values}) != len(values):
        raise ValueError(f"{name} must be unique case-insensitively")
    return values


class RequestModel(StrictModel):
    request_id: str

    @field_validator("request_id")
    @classmethod
    def valid_request_id(cls, value: str) -> str:
        return _uuid(value, "request_id")


class KeywordExpansionRequest(RequestModel):
    query: str

    @field_validator("query")
    @classmethod
    def valid_query(cls, value: str) -> str:
        return _bounded(value, maximum=MAX_QUESTION_LENGTH, name="query")


class ConversationMessage(StrictModel):
    message_id: str
    thread_id: str
    timestamp: str
    sender: str
    text: str

    @field_validator("message_id", "thread_id")
    @classmethod
    def valid_ids(cls, value: str) -> str:
        return _bounded(value, maximum=MAX_ID_LENGTH, name="message ID")

    @field_validator("timestamp", "sender")
    @classmethod
    def valid_display_strings(cls, value: str) -> str:
        return _bounded(value, maximum=MAX_ID_LENGTH, name="message display value")

    @field_validator("text")
    @classmethod
    def valid_text(cls, value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("message text must be a string")
        return value


class WorkingCorpus(StrictModel):
    scope_id: str
    messages: list[ConversationMessage] = Field(min_length=1)

    @field_validator("scope_id")
    @classmethod
    def valid_scope(cls, value: str) -> str:
        return _bounded(value, maximum=MAX_ID_LENGTH, name="scope_id")

    @model_validator(mode="after")
    def unique_message_ids(self) -> "WorkingCorpus":
        ids = [message.message_id for message in self.messages]
        if len(ids) != len(set(ids)):
            raise ValueError("message IDs must be unique")
        return self


class AnalysisPlanningRequest(RequestModel):
    question: str

    @field_validator("question")
    @classmethod
    def valid_question(cls, value: str) -> str:
        return _bounded(value, maximum=MAX_QUESTION_LENGTH, name="question")


class AnalysisConcept(StrictModel):
    label: str
    definition: str
    manifestations: list[str] = Field(min_length=1, max_length=12)

    @field_validator("label", "definition")
    @classmethod
    def valid_concept_text(cls, value: str) -> str:
        return _bounded(value, maximum=MAX_QUESTION_LENGTH, name="concept text", trimmed=True)

    @field_validator("manifestations")
    @classmethod
    def valid_manifestations(cls, value: list[str]) -> list[str]:
        return _unique_strings(value, maximum=12, name="manifestations", minimum=1)


class AnalysisPlanningOutput(StrictModel):
    analysis_question: str
    answer_objective: str
    concepts: list[AnalysisConcept] = Field(min_length=1, max_length=12)
    inclusion_criteria: list[str] = Field(min_length=1, max_length=20)
    exclusion_criteria: list[str] = Field(max_length=20)
    retrieval_queries: list[str] = Field(min_length=1, max_length=20)
    answer_requirements: list[str] = Field(min_length=1, max_length=12)
    interpretive_assumptions: list[str] = Field(max_length=12)

    @field_validator("analysis_question", "answer_objective")
    @classmethod
    def valid_plan_text(cls, value: str) -> str:
        return _bounded(value, maximum=MAX_QUESTION_LENGTH, name="planning text", trimmed=True)

    @field_validator("inclusion_criteria", "exclusion_criteria", "answer_requirements", "interpretive_assumptions")
    @classmethod
    def valid_plan_lists(cls, value: list[str], info) -> list[str]:
        maximum = {"inclusion_criteria": 20, "exclusion_criteria": 20, "answer_requirements": 12, "interpretive_assumptions": 12}[info.field_name]
        minimum = 1 if info.field_name in {"inclusion_criteria", "answer_requirements"} else 0
        return _unique_strings(value, maximum=maximum, name=info.field_name, minimum=minimum)

    @field_validator("retrieval_queries")
    @classmethod
    def valid_retrieval_queries(cls, value: list[str]) -> list[str]:
        if len(value) < 1 or len(value) > MAX_QUERY_COUNT:
            raise ValueError("retrieval_queries count is outside its limit")
        for query in value:
            _bounded(query, maximum=MAX_QUERY_LENGTH, name="retrieval query", trimmed=True)
        if len({query.casefold() for query in value}) != len(value):
            raise ValueError("retrieval_queries must be unique case-insensitively")
        return value


class FrozenAnalysisPlan(StrictModel):
    analysis_question: str
    answer_objective: str
    concepts: list[AnalysisConcept] = Field(min_length=1, max_length=12)
    inclusion_criteria: list[str] = Field(min_length=1, max_length=20)
    exclusion_criteria: list[str] = Field(max_length=20)
    answer_requirements: list[str] = Field(min_length=1, max_length=12)
    interpretive_assumptions: list[str] = Field(max_length=12)

    @field_validator("analysis_question", "answer_objective")
    @classmethod
    def valid_plan_text(cls, value: str) -> str:
        return _bounded(value, maximum=MAX_QUESTION_LENGTH, name="planning text", trimmed=True)

    @field_validator("inclusion_criteria", "exclusion_criteria", "answer_requirements", "interpretive_assumptions")
    @classmethod
    def valid_plan_lists(cls, value: list[str], info) -> list[str]:
        maximum = {"inclusion_criteria": 20, "exclusion_criteria": 20, "answer_requirements": 12, "interpretive_assumptions": 12}[info.field_name]
        minimum = 1 if info.field_name in {"inclusion_criteria", "answer_requirements"} else 0
        return _unique_strings(value, maximum=maximum, name=info.field_name, minimum=minimum)


class RetrievalQuery(StrictModel):
    query_id: str
    text: str

    @field_validator("query_id")
    @classmethod
    def valid_query_id(cls, value: str) -> str:
        return _bounded(value, maximum=MAX_ID_LENGTH, name="query_id")

    @field_validator("text")
    @classmethod
    def valid_query_text(cls, value: str) -> str:
        return _bounded(value, maximum=MAX_QUERY_LENGTH, name="query text", trimmed=True)


def _validate_unique_queries(queries: list[RetrievalQuery]) -> list[RetrievalQuery]:
    ids = [query.query_id for query in queries]
    if len(ids) != len(set(ids)):
        raise ValueError("query IDs must be unique")
    return queries


class EmbeddingMetadata(StrictModel):
    embedding_profile_id: str
    artifact_fingerprint: str
    dimensions: int = Field(gt=0)
    normalization: Literal["unit_l2", "none"]

    @field_validator("embedding_profile_id")
    @classmethod
    def valid_profile_id(cls, value: str) -> str:
        return _bounded(value, maximum=MAX_ID_LENGTH, name="embedding_profile_id")

    @field_validator("artifact_fingerprint")
    @classmethod
    def valid_artifact_fingerprint(cls, value: str) -> str:
        return _fingerprint(value, "artifact_fingerprint")


class SearchPolicy(StrictModel):
    mode: Literal["none", "semantic_ranges"]
    top_k_per_query: int = Field(ge=1, le=1000)
    fusion_method: Literal["reciprocal_rank_fusion"]
    rrf_constant: int = Field(ge=1, le=1000)
    maximum_prompt_suggestion_messages: int = Field(ge=1, le=500)


class AnalysisPlanResponse(StrictModel):
    request_id: str
    config_version: int = Field(ge=1)
    analysis_plan_id: str
    compatibility_fingerprint: str
    analysis_plan: FrozenAnalysisPlan
    retrieval_queries: list[RetrievalQuery] = Field(min_length=1, max_length=MAX_QUERY_COUNT)
    embedding: EmbeddingMetadata | None
    search_policy: SearchPolicy
    usage: "UsageSummary"

    @field_validator("request_id", "analysis_plan_id")
    @classmethod
    def valid_response_ids(cls, value: str, info) -> str:
        return _uuid(value, info.field_name)

    @field_validator("compatibility_fingerprint")
    @classmethod
    def valid_compatibility_fingerprint(cls, value: str) -> str:
        return _fingerprint(value, "compatibility_fingerprint")

    @field_validator("retrieval_queries")
    @classmethod
    def unique_response_queries(cls, value: list[RetrievalQuery]) -> list[RetrievalQuery]:
        return _validate_unique_queries(value)

    @model_validator(mode="after")
    def mode_embedding_invariant(self) -> "AnalysisPlanResponse":
        if self.search_policy.mode == "none" and self.embedding is not None:
            raise ValueError("none analysis plans must have null embedding")
        if self.search_policy.mode == "semantic_ranges" and self.embedding is None:
            raise ValueError("semantic analysis plans require embedding metadata")
        return self


class RetrievalHit(StrictModel):
    query_id: str
    message_id: str
    rank: int = Field(ge=1)
    distance: float

    @field_validator("query_id", "message_id")
    @classmethod
    def valid_hit_ids(cls, value: str) -> str:
        return _bounded(value, maximum=MAX_ID_LENGTH, name="retrieval ID")

    @field_validator("distance")
    @classmethod
    def valid_distance(cls, value: float) -> float:
        if not math.isfinite(value) or value < 0:
            raise ValueError("distance must be finite and nonnegative")
        return value


class AnalysisContext(StrictModel):
    analysis_plan_id: str
    plan_config_version: int = Field(ge=1)
    compatibility_fingerprint: str
    analysis_plan: FrozenAnalysisPlan
    retrieval_queries: list[RetrievalQuery] = Field(min_length=1, max_length=MAX_QUERY_COUNT)
    embedding: EmbeddingMetadata | None
    search_policy: SearchPolicy
    hits: list[RetrievalHit]

    @field_validator("analysis_plan_id")
    @classmethod
    def valid_plan_id(cls, value: str) -> str:
        return _uuid(value, "analysis_plan_id")

    @field_validator("compatibility_fingerprint")
    @classmethod
    def valid_context_fingerprint(cls, value: str) -> str:
        return _fingerprint(value, "compatibility_fingerprint")

    @field_validator("retrieval_queries")
    @classmethod
    def unique_context_queries(cls, value: list[RetrievalQuery]) -> list[RetrievalQuery]:
        return _validate_unique_queries(value)

    @model_validator(mode="after")
    def mode_context_invariant(self) -> "AnalysisContext":
        if self.search_policy.mode == "none":
            if self.embedding is not None or self.hits:
                raise ValueError("none analysis context requires null embedding and empty hits")
        elif self.embedding is None:
            raise ValueError("semantic analysis context requires embedding metadata")
        query_ids = {query.query_id for query in self.retrieval_queries}
        pairs: set[tuple[str, str]] = set()
        by_query: dict[str, list[int]] = {}
        for hit in self.hits:
            if hit.query_id not in query_ids:
                raise ValueError("retrieval hit references an unknown query")
            pair = (hit.query_id, hit.message_id)
            if pair in pairs:
                raise ValueError("retrieval query/message pairs must be unique")
            pairs.add(pair)
            by_query.setdefault(hit.query_id, []).append(hit.rank)
        for query_id, ranks in by_query.items():
            if sorted(ranks) != list(range(1, len(ranks) + 1)):
                raise ValueError(f"ranks for {query_id} must be contiguous from 1")
        if self.search_policy.mode == "semantic_ranges" and not self.hits:
            raise ValueError("semantic analysis context requires hits")
        return self


class ConversationalAnalysisRequest(RequestModel):
    question: str
    working_corpus: WorkingCorpus
    analysis_context: AnalysisContext

    @field_validator("question")
    @classmethod
    def valid_question(cls, value: str) -> str:
        return _bounded(value, maximum=MAX_QUESTION_LENGTH, name="question")


class EmbeddingItem(StrictModel):
    message_id: str
    text: str

    @field_validator("message_id")
    @classmethod
    def valid_item_id(cls, value: str) -> str:
        return _bounded(value, maximum=MAX_ID_LENGTH, name="message_id")

    @field_validator("text")
    @classmethod
    def valid_item_text(cls, value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("embedding text must be a string")
        return value


class EmbeddingsRequest(RequestModel):
    items: list[EmbeddingItem] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_item_ids(self) -> "EmbeddingsRequest":
        ids = [item.message_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("embedding message IDs must be unique")
        return self


class UsageSummary(StrictModel):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    source: Literal["provider_reported", "mixed", "estimated"]
    estimated_cost: float | None = Field(default=None, ge=0)
    cost_complete: bool
    currency: Literal["USD"]


class WindowEvidenceEnvelope(StrictModel):
    window_id: str
    evidence_ranges: list[Any]
    uncertainties: list[str]

    @field_validator("window_id")
    @classmethod
    def valid_window_id(cls, value: str) -> str:
        return _bounded(value, maximum=MAX_ID_LENGTH, name="window_id")

    @field_validator("uncertainties")
    @classmethod
    def valid_uncertainties(cls, value: list[str]) -> list[str]:
        for item in value:
            _bounded(item, maximum=MAX_QUESTION_LENGTH, name="uncertainty", trimmed=True)
        return value


class RejectedRangeDiagnostic(StrictModel):
    window_id: str
    range_index: int = Field(ge=0)
    code: Literal[
        "RANGE_NOT_OBJECT", "RANGE_SCHEMA_INVALID", "UNKNOWN_START_MESSAGE_ID",
        "UNKNOWN_END_MESSAGE_ID", "CROSS_THREAD_RANGE", "THREAD_ID_MISMATCH",
        "NONCONTIGUOUS_THREAD_RANGE", "DUPLICATE_RANGE",
    ]
    message: str
    declared_thread_id: str | None
    start_message_id: str | None
    end_message_id: str | None


class RangeNormalization(StrictModel):
    code: Literal["ENDPOINT_ORDER_SWAPPED"]
    window_id: str
    range_index: int = Field(ge=0)
    original_start_message_id: str
    original_end_message_id: str


class EvidenceValidationSummary(StrictModel):
    planned_window_count: int = Field(ge=0)
    usable_window_count: int = Field(ge=0)
    unavailable_window_count: int = Field(ge=0)
    unavailable_windows: list["WindowUnavailableDiagnostic"]
    status: Literal["complete", "partial"]
    accepted_range_count: int = Field(ge=0)
    rejected_range_count: int = Field(ge=0)
    normalized_range_count: int = Field(ge=0)
    rejected_ranges: list[RejectedRangeDiagnostic]
    warnings: list["WarningRecord"] = Field(default_factory=list)

    @model_validator(mode="after")
    def counts_and_status_agree(self) -> "EvidenceValidationSummary":
        if self.usable_window_count + self.unavailable_window_count != self.planned_window_count:
            raise ValueError("window counts must add up to planned_window_count")
        if self.unavailable_window_count != len(self.unavailable_windows):
            raise ValueError("unavailable_window_count must equal unavailable_windows length")
        if self.rejected_range_count != len(self.rejected_ranges):
            raise ValueError("rejected_range_count must equal rejected_ranges length")
        expected_status = "partial" if self.rejected_range_count or self.unavailable_window_count else "complete"
        if self.status != expected_status:
            raise ValueError("validation status must agree with rejected ranges")
        if self.normalized_range_count > self.accepted_range_count:
            raise ValueError("normalized ranges cannot exceed accepted ranges")
        return self


WarningCode = Literal[
    "UNKNOWN_RANGE_ID", "UNKNOWN_MESSAGE_ID", "RANGE_ENDPOINTS_REVERSED",
    "THREAD_ID_CORRECTED", "CROSS_THREAD_RANGE", "AMBIGUOUS_RANGE",
    "DUPLICATE_CITATION", "CITATION_PARTIALLY_VERIFIED", "CITATION_UNVERIFIED",
    "UNKNOWN_PROBABILITY", "SYNTHESIS_OUTPUT_NONCONFORMANT",
    "SYNTHESIS_RESULT_UNCLASSIFIED", "SYNTHESIS_OMITTED_LEDGER_RANGE",
    "WINDOW_OUTPUT_UNUSABLE", "WINDOW_UNAVAILABLE", "COMPACTION_UNAVAILABLE",
    "COMPACTION_RANGE_ORDER_CORRECTED", "SYNTHESIS_UNAVAILABLE",
]


class WarningRecord(StrictModel):
    code: WarningCode
    details: dict[str, Any]


class WindowUnavailableDiagnostic(StrictModel):
    window_id: str
    window_index: int = Field(ge=0)
    window_count: int = Field(gt=0)
    attempts: int = Field(ge=0)
    code: str

    @field_validator("window_id", "code")
    @classmethod
    def valid_diagnostic_text(cls, value: str) -> str:
        return _bounded(value, maximum=MAX_ID_LENGTH, name="window diagnostic value")


class SynthesisResult(StrictModel):
    probability: Literal["high_probability", "lower_probability"]
    statement: str
    range_ids: list[str] = Field(min_length=1)
    uncertainty: str | None

    @field_validator("statement")
    @classmethod
    def valid_statement(cls, value: str) -> str:
        return _nonblank(value, "synthesis statement")

    @field_validator("range_ids")
    @classmethod
    def valid_range_ids(cls, values: list[str]) -> list[str]:
        for value in values:
            _bounded(value, maximum=MAX_ID_LENGTH, name="range_id")
        return values

    @field_validator("uncertainty")
    @classmethod
    def valid_uncertainty(cls, value: str | None) -> str | None:
        if value is not None:
            _nonblank(value, "result uncertainty")
        return value


class LedgerSynthesisOutput(StrictModel):
    overview: str
    results: list[SynthesisResult]
    uncertainties: list[str]

    @field_validator("overview")
    @classmethod
    def valid_synthesis_text(cls, value: str) -> str:
        return _nonblank(value, "synthesis overview")

    @field_validator("uncertainties")
    @classmethod
    def valid_synthesis_uncertainties(cls, values: list[str]) -> list[str]:
        for value in values:
            _nonblank(value, "synthesis uncertainty")
        return values


class LedgerCompactionOutput(StrictModel):
    group_id: str
    summary: str
    covered_range_ids: list[str]
    uncertainties: list[str]

    @field_validator("group_id")
    @classmethod
    def valid_group_id(cls, value: str) -> str:
        return _bounded(value, maximum=MAX_ID_LENGTH, name="group_id")

    @field_validator("summary")
    @classmethod
    def valid_compaction_summary(cls, value: str) -> str:
        return _bounded(value, maximum=MAX_QUESTION_LENGTH, name="compaction summary")


class KeywordExpansionOutput(StrictModel):
    terms: list[str] = Field(min_length=1, max_length=MAX_QUERY_COUNT)

    @field_validator("terms")
    @classmethod
    def valid_terms(cls, values: list[str]) -> list[str]:
        if any(not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > MAX_QUERY_LENGTH for value in values):
            raise ValueError("terms must be trimmed nonblank strings within the query limit")
        if len({value.casefold() for value in values}) != len(values):
            raise ValueError("terms must be unique case-insensitively")
        return values


class ConversationalEvidenceLedgerItem(StrictModel):
    range_id: str
    window_id: str
    source_range_index: int = Field(ge=0)
    thread_id: str
    start_message_id: str
    end_message_id: str
    summary: str | None
    relevance: str | None
    normalizations: list[Literal["endpoint_order_swapped"]]
    uncertainties: list[str]
    warnings: list[WarningRecord]

    @field_validator("range_id", "window_id", "thread_id", "start_message_id", "end_message_id")
    @classmethod
    def valid_ledger_ids(cls, value: str) -> str:
        return _bounded(value, maximum=MAX_ID_LENGTH, name="ledger ID")

    @field_validator("summary", "relevance")
    @classmethod
    def valid_ledger_text(cls, value: str | None) -> str | None:
        if value is not None:
            _nonblank(value, "ledger text")
        return value

    @field_validator("uncertainties")
    @classmethod
    def valid_ledger_uncertainties(cls, values: list[str]) -> list[str]:
        for value in values:
            _nonblank(value, "ledger uncertainty")
        return values


class PublicResultItem(StrictModel):
    probability: Literal["high_probability", "lower_probability"] | None
    classification_status: Literal["model_classified", "unclassified"]
    statement: str
    reported_range_ids: list[str]
    verified_range_ids: list[str]
    unverified_range_ids: list[str]
    citation_status: Literal["verified", "partial", "unverified"]
    uncertainty: str | None
    warnings: list[WarningRecord]

    @field_validator("statement")
    @classmethod
    def valid_public_statement(cls, value: str) -> str:
        return _nonblank(value, "result statement")

    @field_validator("reported_range_ids", "verified_range_ids", "unverified_range_ids")
    @classmethod
    def valid_public_range_ids(cls, values: list[str]) -> list[str]:
        for value in values:
            _nonblank(value, "result range ID")
        return values


class UnclassifiedEvidence(StrictModel):
    range_id: str
    summary: str | None
    relevance: str | None
    reason: Literal["not_referenced_by_synthesis"]

    @field_validator("range_id")
    @classmethod
    def valid_unclassified_range_id(cls, value: str) -> str:
        return _bounded(value, maximum=MAX_ID_LENGTH, name="unclassified range ID")


class UnverifiedModelStatement(StrictModel):
    statement: str
    reported_range_ids: list[str]
    probability: Literal["high_probability", "lower_probability"] | None
    uncertainty: str | None
    warnings: list[WarningRecord]

    @field_validator("statement")
    @classmethod
    def valid_unverified_statement(cls, value: str) -> str:
        return _nonblank(value, "unverified statement")

    @field_validator("reported_range_ids")
    @classmethod
    def valid_unverified_ids(cls, values: list[str]) -> list[str]:
        for value in values:
            _nonblank(value, "reported range ID")
        return values


class SynthesisValidation(StrictModel):
    status: Literal["conformant", "warnings", "unparseable", "unavailable"]
    raw_output_preserved: bool
    warnings: list[WarningRecord]

    @model_validator(mode="after")
    def conformant_has_no_warnings(self) -> "SynthesisValidation":
        if self.status == "conformant" and self.warnings:
            raise ValueError("conformant synthesis validation cannot contain warnings")
        return self


class Coverage(StrictModel):
    message_count: int = Field(ge=0)
    planned_window_count: int = Field(ge=0)
    usable_window_count: int = Field(ge=0)
    unavailable_window_count: int = Field(ge=0)
    evidence_range_count: int = Field(ge=0)

    @model_validator(mode="after")
    def window_counts_agree(self) -> "Coverage":
        if self.usable_window_count + self.unavailable_window_count != self.planned_window_count:
            raise ValueError("coverage window counts must add up to planned_window_count")
        return self


class RetrievalDiagnostics(StrictModel):
    mode: Literal["none", "semantic_ranges"]
    query_count: int = Field(ge=0)
    raw_hit_count: int = Field(ge=0)
    unique_candidate_message_count: int = Field(ge=0)
    selected_suggestion_message_count: int = Field(ge=0)
    suggestion_range_count: int = Field(ge=0)
    final_ranges_overlapping_suggestions: int = Field(ge=0)
    final_ranges_outside_suggestions: int = Field(ge=0)
    answer_relevant_ranges_overlapping_suggestions: int = Field(ge=0)
    answer_relevant_ranges_outside_suggestions: int = Field(ge=0)
    suggestions_without_final_evidence: int = Field(ge=0)


class LedgerProcessing(StrictModel):
    direct_synthesis_input_tokens: int = Field(ge=0)
    synthesis_usable_input_tokens: int = Field(ge=0)
    compaction_applied: bool
    compaction_levels: int = Field(ge=0)
    compaction_group_calls: int = Field(ge=0)


class ConversationalResult(StrictModel):
    completion_status: Literal["complete", "complete_with_warnings", "partial"]
    answer_source: Literal["structured_synthesis", "raw_synthesis_output", "synthesis_unavailable"]
    results: list[PublicResultItem]
    unclassified_evidence: list[UnclassifiedEvidence]
    unverified_model_statements: list[UnverifiedModelStatement]
    evidence_ledger: list[ConversationalEvidenceLedgerItem]
    evidence_validation: EvidenceValidationSummary
    synthesis_validation: SynthesisValidation
    coverage: Coverage
    retrieval_diagnostics: RetrievalDiagnostics
    ledger_processing: LedgerProcessing
    usage: UsageSummary
    uncertainties: list[str]
    overview: str | None = None
    raw_answer: str | None = None
    strategy: Literal["single_window_ledger", "multi_window_ledger"]

    @model_validator(mode="after")
    def result_variant_and_status_agree(self) -> "ConversationalResult":
        if self.answer_source == "structured_synthesis":
            if self.overview is None or not self.overview.strip() or self.raw_answer is not None:
                raise ValueError("structured synthesis requires overview and forbids raw_answer")
        elif self.answer_source == "raw_synthesis_output":
            if self.raw_answer is None or not self.raw_answer.strip() or self.overview is not None:
                raise ValueError("raw synthesis output requires raw_answer and forbids overview")
        elif self.overview is not None or self.raw_answer is not None:
            raise ValueError("synthesis_unavailable forbids overview and raw_answer")
        if self.completion_status == "complete" and (
            self.evidence_validation.status != "complete"
            or self.synthesis_validation.status != "conformant"
            or any(item.warnings for item in self.results)
            or self.unclassified_evidence
            or self.unverified_model_statements
        ):
            raise ValueError("complete result contains warning or partial facts")
        if self.completion_status == "partial" and self.answer_source == "structured_synthesis" and not (
            self.overview and self.overview.strip()
        ):
            raise ValueError("partial structured result requires a readable overview")
        return self


class KeywordExpansionResponse(StrictModel):
    request_id: str
    config_version: int = Field(ge=1)
    terms: list[str] = Field(min_length=1, max_length=MAX_QUERY_COUNT)
    usage: UsageSummary

    @field_validator("request_id")
    @classmethod
    def valid_response_request_id(cls, value: str) -> str:
        return _uuid(value, "request_id")


class CommonError(StrictModel):
    request_id: str | None
    code: str
    message: str
    stage: str
    retryable: bool
    details: dict[str, Any]


class ErrorResponse(CommonError):
    pass


class EventBase(StrictModel):
    request_id: str
    sequence: int = Field(ge=1)
    event: str
    timestamp: str
    config_version: int = Field(ge=1)

    @field_validator("request_id")
    @classmethod
    def valid_event_request_id(cls, value: str) -> str:
        return _uuid(value, "request_id")

    @field_validator("timestamp")
    @classmethod
    def valid_timestamp(cls, value: str) -> str:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("timestamp must be RFC 3339") from exc
        if parsed.tzinfo is None:
            raise ValueError("timestamp must include timezone")
        return value


class AcceptedConversationData(StrictModel):
    endpoint: Literal["/v1/conversational-analysis"]
    scope_id: str
    message_count: int = Field(ge=1)


class AcceptedEmbeddingsData(StrictModel):
    endpoint: Literal["/v1/embeddings"]
    total_items: int = Field(ge=1)
    embedding_profile_id: str
    model: str
    requested_revision: str
    artifact_fingerprint: str
    dimensions: int = Field(gt=0)
    normalization: Literal["unit_l2", "none"]


class AcceptedConversationEvent(EventBase):
    event: Literal["accepted"]
    data: AcceptedConversationData


class AcceptedEmbeddingsEvent(EventBase):
    event: Literal["accepted"]
    data: AcceptedEmbeddingsData


class QueuedData(StrictModel):
    operation: str
    queued_count: int = Field(ge=0)
    wait_timeout_ms: int = Field(ge=0)
    window_id: str | None = None
    window_index: int | None = Field(default=None, ge=0)
    window_count: int | None = Field(default=None, gt=0)


class RetryWaitData(StrictModel):
    operation: str
    failed_attempt: int = Field(ge=1)
    next_attempt: int = Field(ge=1)
    delay_ms: int = Field(ge=0)
    error_code: str
    window_id: str | None = None
    window_index: int | None = Field(default=None, ge=0)
    window_count: int | None = Field(default=None, gt=0)


class HeartbeatData(StrictModel):
    operation: str
    elapsed_ms: int = Field(ge=0)
    completed_windows: int = Field(ge=0)
    active_windows: int = Field(ge=0)
    window_count: int = Field(ge=0)


class AccountingData(StrictModel):
    corpus_tokens: int = Field(ge=0)
    analysis_input_tokens: int = Field(ge=0)
    context_window_tokens: int = Field(gt=0)
    reserved_output_tokens: int = Field(ge=0)
    safety_margin_tokens: int = Field(ge=0)
    strategy: Literal["single_window_ledger", "multi_window_ledger"]


class AnalysisPlanAcceptedData(StrictModel):
    analysis_plan_id: str
    compatibility_fingerprint: str
    concept_count: int = Field(ge=1)
    retrieval_query_count: int = Field(ge=1)
    retrieval_mode: Literal["none", "semantic_ranges"]


class RetrievalSuggestionsBuiltData(StrictModel):
    unique_candidate_message_count: int = Field(ge=0)
    selected_suggestion_message_count: int = Field(ge=0)
    suggestion_range_count: int = Field(ge=0)
    unselected_candidate_message_count: int = Field(ge=0)


class WindowCompletedData(StrictModel):
    window_id: str
    window_index: int = Field(ge=0)
    window_count: int = Field(gt=0)
    accepted_range_count: int = Field(ge=0)
    rejected_range_count: int = Field(ge=0)
    normalized_range_count: int = Field(ge=0)
    validation_status: Literal["complete", "partial"]
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    usage_source: Literal["provider_reported", "estimated"]
    estimated_cost: float | None = Field(ge=0)

    @model_validator(mode="after")
    def validation_status_agrees(self) -> "WindowCompletedData":
        expected = "partial" if self.rejected_range_count else "complete"
        if self.validation_status != expected:
            raise ValueError("window validation status must agree with rejected count")
        if self.normalized_range_count > self.accepted_range_count:
            raise ValueError("normalized ranges cannot exceed accepted ranges")
        return self


class EvidenceValidationCompletedData(StrictModel):
    planned_window_count: int = Field(ge=0)
    usable_window_count: int = Field(ge=0)
    unavailable_window_count: int = Field(ge=0)
    accepted_range_count: int = Field(ge=0)
    rejected_range_count: int = Field(ge=0)
    normalized_range_count: int = Field(ge=0)
    status: Literal["complete", "partial"]

    @model_validator(mode="after")
    def validation_status_agrees(self) -> "EvidenceValidationCompletedData":
        if self.usable_window_count + self.unavailable_window_count != self.planned_window_count:
            raise ValueError("event window counts must add up to planned_window_count")
        expected = "partial" if self.rejected_range_count or self.unavailable_window_count else "complete"
        if self.status != expected:
            raise ValueError("validation status must agree with rejected count")
        if self.normalized_range_count > self.accepted_range_count:
            raise ValueError("normalized ranges cannot exceed accepted ranges")
        return self


class WindowPlanData(StrictModel):
    strategy: Literal["single_window_ledger", "multi_window_ledger"]
    window_count: int = Field(ge=1)
    message_count: int = Field(ge=1)
    hard_input_tokens: int = Field(gt=0)
    target_input_tokens: int = Field(gt=0)
    utilization_percent: float = Field(ge=1, le=100)
    retrieval_reserve_tokens: int = Field(ge=0)
    window_plan_hash: str


class WindowStartedData(StrictModel):
    window_id: str
    window_index: int = Field(ge=0)
    window_count: int = Field(gt=0)
    message_count: int = Field(ge=1)
    suggestion_range_count: int = Field(ge=0)


class LedgerBuiltData(StrictModel):
    window_count: int = Field(ge=1)
    evidence_range_count: int = Field(ge=0)


class LedgerSynthesisPreflightData(StrictModel):
    evidence_range_count: int = Field(ge=0)
    evidence_message_count: int = Field(ge=0)
    required_input_tokens: int = Field(ge=0)
    usable_input_tokens: int = Field(ge=0)
    excess_input_tokens: int = Field(ge=0)
    direct_fit: bool


class LedgerCompactionRequiredData(LedgerSynthesisPreflightData):
    maximum_depth: int = Field(ge=1)


class LedgerCompactionGroupStartedData(StrictModel):
    level: int = Field(ge=1)
    group_id: str
    group_index: int = Field(ge=0)
    group_count: int = Field(gt=0)
    covered_range_count: int = Field(ge=0)


class LedgerCompactionGroupCompletedData(LedgerCompactionGroupStartedData):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    usage_source: Literal["provider_reported", "estimated"]
    estimated_cost: float | None = Field(ge=0)


class LedgerCompactionLevelCompletedData(StrictModel):
    level: int = Field(ge=1)
    group_count: int = Field(gt=0)
    covered_range_count: int = Field(ge=0)


class LedgerCompactionCompletedData(StrictModel):
    levels: int = Field(ge=1)
    group_calls: int = Field(ge=1)
    original_range_count: int = Field(ge=0)
    covered_range_count: int = Field(ge=0)
    final_synthesis_input_tokens: int = Field(ge=0)


class LedgerSynthesisStartedData(StrictModel):
    evidence_range_count: int = Field(ge=0)


class LedgerSynthesisReceivedData(StrictModel):
    evidence_range_count: int = Field(ge=0)
    content_nonblank: bool
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    usage_source: Literal["provider_reported", "estimated"]
    estimated_cost: float | None = Field(ge=0)


class SynthesisValidationCompletedData(StrictModel):
    status: Literal["conformant", "warnings", "unparseable", "unavailable"]
    result_count: int = Field(ge=0)
    verified_citation_count: int = Field(ge=0)
    unverified_citation_count: int = Field(ge=0)
    omitted_range_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)


class WarningData(StrictModel):
    code: WarningCode
    details: dict[str, Any]
    stage: str
    operation: str | None = None
    window_id: str | None = None


class WindowOutputUnusableData(StrictModel):
    window_id: str
    window_index: int = Field(ge=0)
    window_count: int = Field(gt=0)
    attempt: int = Field(ge=1)
    code: str


class WindowUnavailableData(StrictModel):
    window_id: str
    window_index: int = Field(ge=0)
    window_count: int = Field(gt=0)
    attempts: int = Field(ge=0)
    code: str


class RetrievalOverlapCompletedData(StrictModel):
    final_ranges_overlapping_suggestions: int = Field(ge=0)
    final_ranges_outside_suggestions: int = Field(ge=0)
    answer_relevant_ranges_overlapping_suggestions: int = Field(ge=0)
    answer_relevant_ranges_outside_suggestions: int = Field(ge=0)
    suggestions_without_final_evidence: int = Field(ge=0)


class AccountingEvent(EventBase):
    event: Literal["accounting_completed"]
    data: AccountingData


class AnalysisPlanAcceptedEvent(EventBase):
    event: Literal["analysis_plan_accepted"]
    data: AnalysisPlanAcceptedData


class RetrievalSuggestionsBuiltEvent(EventBase):
    event: Literal["retrieval_suggestions_built"]
    data: RetrievalSuggestionsBuiltData


class QueuedEvent(EventBase):
    event: Literal["queued"]
    data: QueuedData


class RetryWaitEvent(EventBase):
    event: Literal["retry_wait"]
    data: RetryWaitData


class HeartbeatEvent(EventBase):
    event: Literal["heartbeat"]
    data: HeartbeatData


class WindowPlanEvent(EventBase):
    event: Literal["window_plan_created"]
    data: WindowPlanData


class WindowStartedEvent(EventBase):
    event: Literal["window_started"]
    data: WindowStartedData


class WindowCompletedEvent(EventBase):
    event: Literal["window_completed"]
    data: WindowCompletedData


class EvidenceValidationCompletedEvent(EventBase):
    event: Literal["evidence_validation_completed"]
    data: EvidenceValidationCompletedData


class LedgerBuiltEvent(EventBase):
    event: Literal["ledger_built"]
    data: LedgerBuiltData


class LedgerSynthesisPreflightEvent(EventBase):
    event: Literal["ledger_synthesis_preflight"]
    data: LedgerSynthesisPreflightData


class LedgerCompactionRequiredEvent(EventBase):
    event: Literal["ledger_compaction_required"]
    data: LedgerCompactionRequiredData


class LedgerCompactionGroupStartedEvent(EventBase):
    event: Literal["ledger_compaction_group_started"]
    data: LedgerCompactionGroupStartedData


class LedgerCompactionGroupCompletedEvent(EventBase):
    event: Literal["ledger_compaction_group_completed"]
    data: LedgerCompactionGroupCompletedData


class LedgerCompactionLevelCompletedEvent(EventBase):
    event: Literal["ledger_compaction_level_completed"]
    data: LedgerCompactionLevelCompletedData


class LedgerCompactionCompletedEvent(EventBase):
    event: Literal["ledger_compaction_completed"]
    data: LedgerCompactionCompletedData


class LedgerSynthesisStartedEvent(EventBase):
    event: Literal["ledger_synthesis_started"]
    data: LedgerSynthesisStartedData


class LedgerSynthesisReceivedEvent(EventBase):
    event: Literal["ledger_synthesis_received"]
    data: LedgerSynthesisReceivedData


class SynthesisValidationCompletedEvent(EventBase):
    event: Literal["synthesis_validation_completed"]
    data: SynthesisValidationCompletedData


class WarningEvent(EventBase):
    event: Literal["warning"]
    data: WarningData


class WindowOutputUnusableEvent(EventBase):
    event: Literal["window_output_unusable"]
    data: WindowOutputUnusableData


class WindowUnavailableEvent(EventBase):
    event: Literal["window_unavailable"]
    data: WindowUnavailableData


class RetrievalOverlapCompletedEvent(EventBase):
    event: Literal["retrieval_overlap_completed"]
    data: RetrievalOverlapCompletedData


class FailedEvent(EventBase):
    event: Literal["failed"]
    error: CommonError


class CompletedConversationEvent(EventBase):
    event: Literal["completed"]
    result: ConversationalResult


class EmbeddingBatchStartedData(StrictModel):
    batch_index: int = Field(ge=0)
    batch_count: int = Field(gt=0)
    first_item_index: int = Field(ge=0)
    last_item_index: int = Field(ge=0)
    item_count: int = Field(gt=0)

    @model_validator(mode="after")
    def bounds(self) -> "EmbeddingBatchStartedData":
        if self.last_item_index < self.first_item_index or self.item_count != self.last_item_index - self.first_item_index + 1:
            raise ValueError("embedding batch bounds are inconsistent")
        return self


class VectorItem(StrictModel):
    message_id: str
    vector: list[float]

    @field_validator("message_id")
    @classmethod
    def valid_vector_id(cls, value: str) -> str:
        return _bounded(value, maximum=MAX_ID_LENGTH, name="message_id")

    @field_validator("vector")
    @classmethod
    def finite_vector(cls, values: list[float]) -> list[float]:
        if not values or any(not math.isfinite(value) for value in values):
            raise ValueError("vector must contain finite floats")
        return values


class VectorBatchData(StrictModel):
    batch_index: int = Field(ge=0)
    items: list[VectorItem] = Field(min_length=1)


class EmbeddingProgressData(StrictModel):
    completed_items: int = Field(ge=0)
    total_items: int = Field(gt=0)
    server_items_per_second: float = Field(ge=0)


class EmbeddingBatchStartedEvent(EventBase):
    event: Literal["embedding_batch_started"]
    data: EmbeddingBatchStartedData


class VectorBatchEvent(EventBase):
    event: Literal["vector_batch"]
    data: VectorBatchData


class EmbeddingProgressEvent(EventBase):
    event: Literal["embedding_progress"]
    data: EmbeddingProgressData


class CompletedEmbeddingsResult(StrictModel):
    total_items: int = Field(ge=1)
    embedding_profile_id: str


class CompletedEmbeddingsEvent(EventBase):
    event: Literal["completed"]
    result: CompletedEmbeddingsResult


ConversationEvent = Union[
    AcceptedConversationEvent, QueuedEvent, RetryWaitEvent, HeartbeatEvent,
    AccountingEvent, AnalysisPlanAcceptedEvent, RetrievalSuggestionsBuiltEvent,
    WindowPlanEvent, WindowStartedEvent, WindowCompletedEvent,
    EvidenceValidationCompletedEvent, LedgerBuiltEvent,
    LedgerSynthesisPreflightEvent, LedgerCompactionRequiredEvent,
    LedgerCompactionGroupStartedEvent, LedgerCompactionGroupCompletedEvent,
    LedgerCompactionLevelCompletedEvent, LedgerCompactionCompletedEvent,
    LedgerSynthesisStartedEvent, LedgerSynthesisReceivedEvent,
    SynthesisValidationCompletedEvent, WarningEvent,
    WindowOutputUnusableEvent, WindowUnavailableEvent,
    RetrievalOverlapCompletedEvent, FailedEvent, CompletedConversationEvent,
]
EmbeddingEvent = Union[
    AcceptedEmbeddingsEvent, QueuedEvent, EmbeddingBatchStartedEvent,
    VectorBatchEvent, EmbeddingProgressEvent, FailedEvent,
    CompletedEmbeddingsEvent,
]
NDJSONEvent = Union[ConversationEvent, EmbeddingEvent]


def parse_ndjson_event(value: dict[str, Any], *, endpoint: str) -> NDJSONEvent:
    """Parse one strict event and reject endpoint-incompatible event names."""
    from pydantic import TypeAdapter

    if endpoint not in {"/v1/conversational-analysis", "/v1/embeddings"}:
        raise ValueError(f"unknown stream endpoint {endpoint!r}")
    event_name = value.get("event")
    conversation_names = {
        "accepted", "queued", "retry_wait", "heartbeat", "accounting_completed",
        "analysis_plan_accepted", "retrieval_suggestions_built", "window_plan_created",
        "window_started", "window_completed", "evidence_validation_completed", "ledger_built",
        "ledger_synthesis_preflight", "ledger_compaction_required",
        "ledger_compaction_group_started", "ledger_compaction_group_completed",
        "ledger_compaction_level_completed", "ledger_compaction_completed",
        "ledger_synthesis_started", "ledger_synthesis_received",
        "synthesis_validation_completed", "warning", "window_output_unusable",
        "window_unavailable",
        "retrieval_overlap_completed", "failed", "completed",
    }
    embedding_names = {"accepted", "queued", "embedding_batch_started", "vector_batch", "embedding_progress", "failed", "completed"}
    if event_name not in (conversation_names if endpoint == "/v1/conversational-analysis" else embedding_names):
        raise ValueError(f"event {event_name!r} is not valid for {endpoint}")
    model_map = {
        "accepted": AcceptedConversationEvent if endpoint == "/v1/conversational-analysis" else AcceptedEmbeddingsEvent,
        "queued": QueuedEvent,
        "retry_wait": RetryWaitEvent,
        "heartbeat": HeartbeatEvent,
        "accounting_completed": AccountingEvent,
        "analysis_plan_accepted": AnalysisPlanAcceptedEvent,
        "retrieval_suggestions_built": RetrievalSuggestionsBuiltEvent,
        "window_plan_created": WindowPlanEvent,
        "window_started": WindowStartedEvent,
        "window_completed": WindowCompletedEvent,
        "evidence_validation_completed": EvidenceValidationCompletedEvent,
        "ledger_built": LedgerBuiltEvent,
        "ledger_synthesis_preflight": LedgerSynthesisPreflightEvent,
        "ledger_compaction_required": LedgerCompactionRequiredEvent,
        "ledger_compaction_group_started": LedgerCompactionGroupStartedEvent,
        "ledger_compaction_group_completed": LedgerCompactionGroupCompletedEvent,
        "ledger_compaction_level_completed": LedgerCompactionLevelCompletedEvent,
        "ledger_compaction_completed": LedgerCompactionCompletedEvent,
        "ledger_synthesis_started": LedgerSynthesisStartedEvent,
        "ledger_synthesis_received": LedgerSynthesisReceivedEvent,
        "synthesis_validation_completed": SynthesisValidationCompletedEvent,
        "warning": WarningEvent,
        "window_output_unusable": WindowOutputUnusableEvent,
        "window_unavailable": WindowUnavailableEvent,
        "retrieval_overlap_completed": RetrievalOverlapCompletedEvent,
        "failed": FailedEvent,
        "completed": CompletedConversationEvent if endpoint == "/v1/conversational-analysis" else CompletedEmbeddingsEvent,
        "embedding_batch_started": EmbeddingBatchStartedEvent,
        "vector_batch": VectorBatchEvent,
        "embedding_progress": EmbeddingProgressEvent,
    }
    event_model = model_map.get(event_name)
    if event_model is None:
        raise ValueError(f"event {event_name!r} is not valid for {endpoint}")
    return TypeAdapter(event_model).validate_python(value)


SCHEMA_REGISTRY: dict[str, dict[str, Any]] = {
    "keyword_expansion": {
        "request": KeywordExpansionRequest.model_json_schema(),
        "response": KeywordExpansionResponse.model_json_schema(),
        "model_output": KeywordExpansionOutput.model_json_schema(),
    },
    "analysis_planning": {"model_output": AnalysisPlanningOutput.model_json_schema()},
    "conversational_plan": {
        "request": AnalysisPlanningRequest.model_json_schema(),
        "response": AnalysisPlanResponse.model_json_schema(),
        "model_output": AnalysisPlanningOutput.model_json_schema(),
    },
    "conversational_analysis": {
        "request": ConversationalAnalysisRequest.model_json_schema(),
        "response": ConversationalResult.model_json_schema(),
        "model_output": LedgerSynthesisOutput.model_json_schema(),
    },
    "embeddings": {
        "request": EmbeddingsRequest.model_json_schema(),
        "response": CompletedEmbeddingsResult.model_json_schema(),
    },
    "window_evidence_extraction": {"model_output": WindowEvidenceEnvelope.model_json_schema()},
    "ledger_compaction": {"model_output": LedgerCompactionOutput.model_json_schema()},
    "ledger_synthesis": {"model_output": LedgerSynthesisOutput.model_json_schema()},
}
