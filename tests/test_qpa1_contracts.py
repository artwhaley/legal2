import uuid

import pytest
from pydantic import ValidationError

from server.contracts import (
    AnalysisConcept,
    AnalysisContext,
    AnalysisPlanResponse,
    AnalysisPlanningOutput,
    ConversationalEvidenceLedgerItem,
    ConversationalResult,
    Coverage,
    EvidenceValidationSummary,
    FrozenAnalysisPlan,
    LedgerCompactionOutput,
    LedgerSynthesisOutput,
    PublicResultItem,
    RetrievalQuery,
    SearchPolicy,
    SynthesisValidation,
    UnclassifiedEvidence,
    UsageSummary,
    WindowEvidenceEnvelope,
)


def _uuid() -> str:
    return str(uuid.uuid4())


def _plan_output() -> dict:
    return {
        "analysis_question": "Identify passages that answer the user's question.",
        "answer_objective": "Present responsive exchanges with dates and supporting ranges.",
        "concepts": [{"label": "responsive exchange", "definition": "A passage that materially bears on the requested subject.", "manifestations": ["direct discussion"]}],
        "inclusion_criteria": ["The passage materially answers the requested question."],
        "exclusion_criteria": [],
        "retrieval_queries": ["question response"],
        "answer_requirements": ["Cite supporting ranges."],
        "interpretive_assumptions": [],
    }


def _frozen() -> dict:
    value = dict(_plan_output())
    value.pop("retrieval_queries")
    return value


def _usage() -> dict:
    return {"input_tokens": 1, "output_tokens": 1, "source": "estimated", "estimated_cost": None, "cost_complete": False, "currency": "USD"}


def _ledger_item() -> dict:
    return {
        "range_id": "r000001",
        "window_id": "w000001",
        "source_range_index": 0,
        "thread_id": "t1",
        "start_message_id": "m1",
        "end_message_id": "m1",
        "summary": "summary",
        "relevance": "relevance",
        "normalizations": [],
    }


def _evidence_validation(*, status: str = "complete", rejected: int = 0) -> dict:
    return {
        "planned_window_count": 1,
        "usable_window_count": 1,
        "unavailable_window_count": 0,
        "unavailable_windows": [],
        "status": status,
        "accepted_range_count": 1,
        "rejected_range_count": rejected,
        "normalized_range_count": 0,
        "rejected_ranges": [],
    }


def _common_result(**overrides) -> dict:
    value = {
        "completion_status": "complete",
        "answer_source": "structured_synthesis",
        "overview": "A complete overview.",
        "results": [{
            "probability": "high_probability",
            "classification_status": "model_classified",
            "statement": "A supported result.",
            "reported_range_ids": ["r000001"],
            "verified_range_ids": ["r000001"],
            "unverified_range_ids": [],
            "citation_status": "verified",
            "uncertainty": None,
            "warnings": [],
        }],
        "unclassified_evidence": [],
        "unverified_model_statements": [],
        "evidence_ledger": [_ledger_item()],
        "evidence_validation": _evidence_validation(),
        "synthesis_validation": {"status": "conformant", "raw_output_preserved": False, "warnings": []},
        "coverage": {"message_count": 1, "planned_window_count": 1, "usable_window_count": 1, "unavailable_window_count": 0, "evidence_range_count": 1},
        "retrieval_diagnostics": {
            "mode": "none", "query_count": 0, "raw_hit_count": 0,
            "unique_candidate_message_count": 0, "selected_suggestion_message_count": 0,
            "suggestion_range_count": 0, "final_ranges_overlapping_suggestions": 0,
            "final_ranges_outside_suggestions": 0, "answer_relevant_ranges_overlapping_suggestions": 0,
            "answer_relevant_ranges_outside_suggestions": 0, "suggestions_without_final_evidence": 0,
        },
        "ledger_processing": {
            "direct_synthesis_input_tokens": 1, "synthesis_usable_input_tokens": 1,
            "compaction_applied": False, "compaction_levels": 0, "compaction_group_calls": 0,
        },
        "usage": _usage(),
        "uncertainties": [],
        "strategy": "single_window_ledger",
    }
    value.update(overrides)
    return value


def test_planning_output_is_complete_and_strict():
    value = AnalysisPlanningOutput.model_validate(_plan_output())
    assert value.retrieval_queries == ["question response"]
    with pytest.raises(ValidationError):
        AnalysisPlanningOutput.model_validate({**_plan_output(), "unexpected": True})
    with pytest.raises(ValidationError):
        AnalysisPlanningOutput.model_validate({**_plan_output(), "retrieval_queries": ["question response", " Question response"]})


def test_public_plan_mode_is_explicit_and_embedding_nullable():
    plan = AnalysisPlanResponse(
        request_id=_uuid(), config_version=4, analysis_plan_id=_uuid(),
        compatibility_fingerprint="a" * 64, analysis_plan=FrozenAnalysisPlan.model_validate(_frozen()),
        retrieval_queries=[RetrievalQuery(query_id="q0001", text="question response")],
        embedding=None,
        search_policy=SearchPolicy(mode="none", top_k_per_query=100, fusion_method="reciprocal_rank_fusion", rrf_constant=60, maximum_prompt_suggestion_messages=40),
        usage=UsageSummary.model_validate(_usage()),
    )
    assert plan.embedding is None
    with pytest.raises(ValidationError):
        AnalysisPlanResponse.model_validate({**plan.model_dump(), "search_policy": {**plan.search_policy.model_dump(), "mode": "semantic_ranges"}})


def test_analysis_context_rejects_hits_for_none_and_requires_hits_for_semantic():
    base = {
        "analysis_plan_id": _uuid(), "plan_config_version": 4,
        "compatibility_fingerprint": "a" * 64, "analysis_plan": _frozen(),
        "retrieval_queries": [{"query_id": "q0001", "text": "question response"}],
        "embedding": None,
        "search_policy": {"mode": "none", "top_k_per_query": 100, "fusion_method": "reciprocal_rank_fusion", "rrf_constant": 60, "maximum_prompt_suggestion_messages": 40},
        "hits": [{"query_id": "q0001", "message_id": "m1", "rank": 1, "distance": 0.1}],
    }
    with pytest.raises(ValidationError):
        AnalysisContext.model_validate(base)
    semantic = {**base, "embedding": {"embedding_profile_id": "profile", "artifact_fingerprint": "b" * 64, "dimensions": 384, "normalization": "unit_l2"}, "search_policy": {**base["search_policy"], "mode": "semantic_ranges"}}
    assert AnalysisContext.model_validate(semantic).hits[0].message_id == "m1"


def test_new_synthesis_output_is_exact_and_long_overview_is_preserved():
    value = LedgerSynthesisOutput.model_validate({
        "overview": "x" * 25_000,
        "results": [{"probability": "high_probability", "statement": "supported", "range_ids": ["r000001"], "uncertainty": None}],
        "uncertainties": [],
    })
    assert len(value.overview) == 25_000
    with pytest.raises(ValidationError):
        LedgerSynthesisOutput.model_validate({
            "overview": "supported", "results": [{"probability": "high_probability", "statement": "supported", "range_ids": ["r000001"]}], "uncertainties": []
        })
    with pytest.raises(ValidationError):
        LedgerSynthesisOutput.model_validate({
            "overview": "supported", "results": [{"probability": "high_probability", "statement": "supported", "range_ids": ["r000001"], "uncertainty": None}], "uncertainties": [], "extra": True
        })


def test_compaction_and_extraction_contracts_remain_strict():
    value = LedgerCompactionOutput.model_validate({"group_id": "g01-000001", "summary": "summary", "covered_range_ids": ["r000001"], "uncertainties": []})
    assert value.covered_range_ids == ["r000001"]
    envelope = WindowEvidenceEnvelope.model_validate({"window_id": "w000001", "evidence_ranges": [{"thread_id": "t", "start_message_id": "m1", "end_message_id": "m2", "summary": "summary", "relevance": "relevance", "extra": True}], "uncertainties": []})
    assert envelope.evidence_ranges[0]["extra"] is True


def test_public_structured_raw_and_unavailable_variants_are_strictly_distinct():
    structured = ConversationalResult.model_validate(_common_result())
    assert structured.answer_source == "structured_synthesis"
    raw = ConversationalResult.model_validate(_common_result(
        completion_status="complete_with_warnings", answer_source="raw_synthesis_output",
        overview=None, raw_answer="plain readable synthesis", results=[],
        synthesis_validation={"status": "unparseable", "raw_output_preserved": True, "warnings": []},
    ))
    assert raw.raw_answer == "plain readable synthesis"
    unavailable = ConversationalResult.model_validate(_common_result(
        completion_status="partial", answer_source="synthesis_unavailable",
        overview=None, raw_answer=None, results=[],
        synthesis_validation={"status": "unavailable", "raw_output_preserved": False, "warnings": []},
        unclassified_evidence=[{"range_id": "r000001", "summary": "summary", "relevance": "relevance", "reason": "not_referenced_by_synthesis"}],
    ))
    assert unavailable.answer_source == "synthesis_unavailable"
    with pytest.raises(ValidationError):
        ConversationalResult.model_validate(_common_result(answer_source="raw_synthesis_output", raw_answer="raw"))


def test_evidence_validation_requires_complete_window_accounting():
    valid = EvidenceValidationSummary.model_validate(_evidence_validation())
    assert valid.planned_window_count == 1
    with pytest.raises(ValidationError):
        EvidenceValidationSummary.model_validate({**_evidence_validation(), "planned_window_count": 2})
    with pytest.raises(ValidationError):
        EvidenceValidationSummary.model_validate({**_evidence_validation(), "status": "partial"})


def test_public_result_requires_exact_verified_subset_and_status_fields():
    value = PublicResultItem.model_validate(_common_result()["results"][0])
    assert set(value.verified_range_ids) <= set(value.reported_range_ids)
    with pytest.raises(ValidationError):
        PublicResultItem.model_validate({**value.model_dump(), "citation_status": "wrong"})
    with pytest.raises(ValidationError):
        UnclassifiedEvidence.model_validate({"range_id": "r000001", "summary": "s", "relevance": "r", "reason": "wrong"})
