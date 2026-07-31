import sqlite3
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
from message_evidence_workstation.client_api.contracts import validate_stream_value
from message_evidence_workstation.services.client_workflows import (
    ConversationalWorkflow,
    format_conversational_result,
)
from message_evidence_workstation.db.schema import CREATE_TABLES_SQL
from message_evidence_workstation.domain.search_scope import (
    NarrowedSearchScope,
    WorkingCorpusScope,
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
        "uncertainties": [],
        "warnings": [],
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
        "warnings": [],
    }


def _common_result(**overrides) -> dict:
    value = {
        "completion_status": "complete",
        "answer_source": "structured_synthesis",
        "overview": "A complete overview.",
        "raw_answer": None,
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


def test_python_client_accepts_exact_duplicate_reports_and_oversized_unknown_ids():
    fabricated = "fabricated-" + ("x" * 600)
    result = _common_result(
        completion_status="complete_with_warnings",
        results=[{
            "probability": "high_probability",
            "classification_status": "model_classified",
            "statement": "Preserved statement.",
            "reported_range_ids": ["r000001", "r000001", fabricated],
            "verified_range_ids": ["r000001"],
            "unverified_range_ids": [fabricated],
            "citation_status": "partial",
            "uncertainty": None,
            "warnings": [
                {"code": "DUPLICATE_CITATION", "details": {"duplicate_count": 1}},
                {"code": "UNKNOWN_RANGE_ID", "details": {"range_id": fabricated}},
            ],
        }],
        synthesis_validation={
            "status": "warnings",
            "raw_output_preserved": False,
            "warnings": [
                {"code": "DUPLICATE_CITATION", "details": {"duplicate_count": 1}},
                {"code": "UNKNOWN_RANGE_ID", "details": {"range_id": fabricated}},
            ],
        },
    )
    event = {
        "request_id": _uuid(),
        "sequence": 1,
        "timestamp": "2026-01-01T00:00:00Z",
        "config_version": 1,
        "event": "completed",
        "result": result,
    }
    validate_stream_value(event, endpoint="/v1/conversational-analysis")


def test_conformant_synthesis_cannot_claim_warning_records():
    with pytest.raises(ValidationError, match="conformant synthesis"):
        SynthesisValidation.model_validate({
            "status": "conformant",
            "raw_output_preserved": False,
            "warnings": [{"code": "UNKNOWN_RANGE_ID", "details": {"range_id": "r999999"}}],
        })


def test_python_test_display_has_readable_probability_boundary_and_all_sections():
    result = _common_result(
        completion_status="complete_with_warnings",
        results=[
            _common_result()["results"][0],
            {
                **_common_result()["results"][0],
                "probability": "lower_probability",
                "statement": "A borderline result.",
            },
        ],
        unclassified_evidence=[{
            "range_id": "r000001",
            "summary": "Unclassified candidate.",
            "relevance": "Possibly responsive.",
            "reason": "not_referenced_by_synthesis",
        }],
        synthesis_validation={
            "status": "warnings",
            "raw_output_preserved": False,
            "warnings": [{
                "code": "SYNTHESIS_OMITTED_LEDGER_RANGE",
                "details": {"range_id": "r000001"},
            }],
        },
    )
    rendered = format_conversational_result(result)
    assert rendered.index("HIGH PROBABILITY") < rendered.index("LOWER PROBABILITY")
    assert "---------------- LOWER-PROBABILITY / REVIEW MATERIAL ----------------" in rendered
    assert "UNCLASSIFIED VALIDATED EVIDENCE" in rendered
    assert "UNVERIFIED MODEL STATEMENTS" in rendered
    assert "SYNTHESIS_OMITTED_LEDGER_RANGE" in rendered


def test_visible_history_persists_complete_rendered_answer_and_terminal_status():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(CREATE_TABLES_SQL)
    now = "2026-01-01T00:00:00Z"
    conn.execute(
        "INSERT INTO dataset(name,created_at,schema_version) VALUES (?,?,15)",
        ("Synthetic", now),
    )
    dataset_id = int(conn.execute("SELECT dataset_id FROM dataset").fetchone()[0])
    conn.execute(
        "INSERT INTO source_thread(source_thread_id,dataset_id,source_platform,platform_thread_id,display_title,start_ts,end_ts) VALUES (?,?,?,?,?,?,?)",
        ("t1", dataset_id, "synthetic", "t1", "Thread", now, now),
    )
    conn.execute(
        """INSERT INTO message(
               message_id,dataset_id,source_thread_id,source_platform,
               source_message_id,timestamp,sender_id,sender_display,body,
               body_normalized,embedding_input_hash,sort_index
           ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            "m1", dataset_id, "t1", "synthetic", "m1", now, "p1", "Person",
            "Message", "message", "a" * 64, 0,
        ),
    )
    corpus_id = int(conn.execute(
        "INSERT INTO working_corpus(dataset_id,name,created_at,updated_at) VALUES (?,?,?,?)",
        (dataset_id, "Corpus", now, now),
    ).lastrowid)
    revision_id = int(conn.execute(
        """INSERT INTO working_corpus_revision(
               working_corpus_id,revision_number,selection_mode,token_limit,
               estimated_tokens,message_count,tokenizer_id,scope_hash,
               dataset_content_revision,status,created_at,built_at
           ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            corpus_id, 1, "all", 768_000, 1, 1, "cl100k_base",
            "scope-hash", 1, "building", now, None,
        ),
    ).lastrowid)
    conn.execute(
        "UPDATE working_corpus SET current_revision_id=? WHERE working_corpus_id=?",
        (revision_id, corpus_id),
    )
    conn.execute(
        "INSERT INTO working_corpus_revision_message(working_corpus_revision_id,message_id,source_thread_id,ordinal,token_count,embedding_input_hash) VALUES (?,?,?,?,?,?)",
        (revision_id, "m1", "t1", 0, 1, "a" * 64),
    )
    conn.execute(
        "UPDATE working_corpus_revision SET status='ready',built_at=? WHERE working_corpus_revision_id=?",
        (now, revision_id),
    )
    conn.execute(
        "INSERT INTO working_corpus_revision_index(working_corpus_revision_id,index_generation,dataset_content_revision,status,created_at,updated_at) VALUES (?,?,?,?,?,?)",
        (revision_id, 1, 1, "ready", now, now),
    )
    scope = NarrowedSearchScope(WorkingCorpusScope(
        corpus_id, revision_id, 1, dataset_id, 1, 1, "scope-hash", 1, 1
    ))
    result = _common_result()

    ConversationalWorkflow._persist_visible_result(
        conn, scope, "What happened?", result
    )

    conversation = conn.execute(
        "SELECT status FROM conversation"
    ).fetchone()
    turn = conn.execute(
        "SELECT status,presented_answer FROM conversation_turn"
    ).fetchone()
    assert conversation["status"] == "complete"
    assert turn["status"] == "complete"
    assert "A complete overview." in turn["presented_answer"]
    assert "HIGH PROBABILITY" in turn["presented_answer"]
    assert "LOWER PROBABILITY" in turn["presented_answer"]
    conn.close()
