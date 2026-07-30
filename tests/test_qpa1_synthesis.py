import json
from dataclasses import replace

import pytest

from server.evidence_ledger import EvidenceRangeRecord
from server.result_validation import assemble_synthesis_result, inspect_synthesis_content


def _record(number: int, *, summary: str | None = None) -> EvidenceRangeRecord:
    value = f"{number:06d}"
    return EvidenceRangeRecord(
        range_id=f"r{value}",
        window_id="w000001",
        source_range_index=number - 1,
        thread_id="t1",
        start_message_id=f"m{number}",
        end_message_id=f"m{number}",
        messages=((
            {"message_id": f"m{number}", "thread_id": "t1", "text": f"synthetic message {number}"},
        )),
        summary=summary if summary is not None else f"summary {number}",
        relevance=f"relevance {number}",
        normalizations=(),
        uncertainties=(),
        warnings=(),
    )


def _inputs(records):
    return {
        "records": records,
        "evidence_validation": {
            "planned_window_count": 1,
            "usable_window_count": 1,
            "unavailable_window_count": 0,
            "unavailable_windows": [],
            "status": "complete",
            "accepted_range_count": len(records),
            "rejected_range_count": 0,
            "normalized_range_count": 0,
            "rejected_ranges": [],
        },
        "strategy": "single_window_ledger",
        "message_count": len(records),
        "planned_window_count": 1,
        "usable_window_count": 1,
        "unavailable_window_count": 0,
        "retrieval_diagnostics": {
            "mode": "none", "query_count": 0, "raw_hit_count": 0,
            "unique_candidate_message_count": 0, "selected_suggestion_message_count": 0,
            "suggestion_range_count": 0, "final_ranges_overlapping_suggestions": 0,
            "final_ranges_outside_suggestions": len(records),
            "answer_relevant_ranges_overlapping_suggestions": 0,
            "answer_relevant_ranges_outside_suggestions": 0,
            "suggestions_without_final_evidence": 0,
        },
        "ledger_processing": {
            "direct_synthesis_input_tokens": 10, "synthesis_usable_input_tokens": 10,
            "compaction_applied": False, "compaction_levels": 0, "compaction_group_calls": 0,
        },
        "usage": {"input_tokens": 10, "output_tokens": 10, "source": "estimated", "estimated_cost": None, "cost_complete": False, "currency": "USD"},
    }


def _assemble(payload, records):
    return assemble_synthesis_result(payload, **_inputs(records))[0]


def _result(probability, statement, ids, uncertainty=None):
    return {"probability": probability, "statement": statement, "range_ids": ids, "uncertainty": uncertainty}


def test_exact_new_synthesis_is_complete():
    result = _assemble(json.dumps({
        "overview": "Overview",
        "results": [_result("high_probability", "Supported statement", ["r000001"])],
        "uncertainties": [],
    }), [_record(1)])
    assert result["completion_status"] == "complete"
    assert result["answer_source"] == "structured_synthesis"
    assert result["results"][0]["verified_range_ids"] == ["r000001"]


def test_latest_glm_shaped_contradiction_returns_useful_raw_output_with_warnings():
    raw = json.dumps({
        "overview": "Readable reviewer answer",
        "results": [_result("high_probability", "A useful result", ["r000001"])],
        "unexpected_model_field": "structural contradiction",
        "uncertainties": [],
    })
    result = _assemble(raw, [_record(1)])
    assert result["completion_status"] == "complete_with_warnings"
    assert result["answer_source"] == "raw_synthesis_output"
    assert result["raw_answer"] == raw
    assert result["results"][0]["verified_range_ids"] == ["r000001"]


def test_high_results_precede_lower_and_model_order_is_stable():
    result = _assemble(json.dumps({
        "overview": "Overview",
        "results": [
            _result("lower_probability", "lower one", ["r000001"]),
            _result("high_probability", "high one", ["r000002"]),
            _result("high_probability", "high two", ["r000003"]),
            _result("lower_probability", "lower two", ["r000004"]),
        ],
        "uncertainties": [],
    }), [_record(1), _record(2), _record(3), _record(4)])
    assert [item["statement"] for item in result["results"]] == ["high one", "high two", "lower one", "lower two"]


def test_mixed_valid_and_fabricated_citations_preserve_statement_and_valid_link():
    result = _assemble(json.dumps({
        "overview": "Overview",
        "results": [_result("high_probability", "Mixed statement", ["r000001", "r999999"])],
        "uncertainties": [],
    }), [_record(1)])
    item = result["results"][0]
    assert item["statement"] == "Mixed statement"
    assert item["verified_range_ids"] == ["r000001"]
    assert item["unverified_range_ids"] == ["r999999"]
    assert item["citation_status"] == "partial"
    assert any(w["code"] == "UNKNOWN_RANGE_ID" for w in item["warnings"])


def test_all_fabricated_citations_are_unverified_model_output():
    result = _assemble(json.dumps({
        "overview": "Overview",
        "results": [_result("high_probability", "Unsupported model statement", ["r999999"])],
        "uncertainties": [],
    }), [_record(1)])
    assert result["results"] == []
    assert result["unverified_model_statements"][0]["statement"] == "Unsupported model statement"
    assert result["unverified_model_statements"][0]["reported_range_ids"] == ["r999999"]


def test_duplicate_citations_are_deduplicated_for_links_and_warned():
    result = _assemble(json.dumps({
        "overview": "Overview",
        "results": [_result("high_probability", "Duplicated citation", ["r000001", "r000001"])],
        "uncertainties": [],
    }), [_record(1)])
    assert result["results"][0]["verified_range_ids"] == ["r000001"]
    assert any(w["code"] == "DUPLICATE_CITATION" for w in result["results"][0]["warnings"])


def test_missing_or_unknown_probability_is_unclassified_not_dropped():
    result = _assemble(json.dumps({
        "overview": "Overview",
        "results": [_result(None, "Unclassified but sourced", ["r000001"])],
        "uncertainties": [],
    }), [_record(1)])
    assert result["results"][0]["classification_status"] == "unclassified"
    assert result["results"][0]["probability"] is None
    assert result["results"][0]["verified_range_ids"] == ["r000001"]


def test_omitted_ledger_ranges_appear_in_canonical_order():
    result = _assemble(json.dumps({
        "overview": "Overview",
        "results": [_result("high_probability", "Only first", ["r000001"])],
        "uncertainties": [],
    }), [_record(1), _record(2), _record(3)])
    assert [item["range_id"] for item in result["unclassified_evidence"]] == ["r000002", "r000003"]
    assert result["completion_status"] == "complete_with_warnings"


def test_fenced_json_is_normalized_and_raw_content_is_preserved():
    raw = "```json\n" + json.dumps({
        "overview": "Overview",
        "results": [_result("high_probability", "Supported", ["r000001"])],
        "uncertainties": [],
    }) + "\n```"
    result = _assemble(raw, [_record(1)])
    assert result["answer_source"] == "structured_synthesis"
    assert result["overview"] == "Overview"
    assert result["synthesis_validation"]["raw_output_preserved"] is True


def test_readable_prose_is_raw_synthesis_output_and_not_retried_by_inspector():
    content = "The provider returned a readable reviewer limitation instead of JSON."
    result = _assemble(content, [_record(1)])
    assert result["answer_source"] == "raw_synthesis_output"
    assert result["raw_answer"] == content
    assert result["completion_status"] == "complete_with_warnings"


def test_parseable_partial_object_salvages_known_result_components():
    raw = json.dumps({
        "overview": "Partial overview",
        "results": [{"probability": "high_probability", "statement": "Salvaged", "range_ids": ["r000001"]}],
        "uncertainties": "not-a-list",
    })
    result = _assemble(raw, [_record(1)])
    assert result["answer_source"] == "raw_synthesis_output"
    assert result["raw_answer"] == raw
    assert result["results"][0]["statement"] == "Salvaged"


def test_malformed_json_is_not_heuristically_rewritten():
    raw = '{"overview":"Overview","results":[{"probability":"high_probability",]}'
    inspected = inspect_synthesis_content(raw)
    assert inspected.parse_status == "unparseable"
    result = _assemble(raw, [_record(1)])
    assert result["raw_answer"] == raw
    assert result["results"] == []


def test_zero_result_structured_answer_survives():
    result = _assemble(json.dumps({"overview": "No responsive evidence was found.", "results": [], "uncertainties": []}), [])
    assert result["completion_status"] == "complete"
    assert result["answer_source"] == "structured_synthesis"
    assert result["results"] == []


def test_long_synthesis_output_survives_without_twenty_thousand_character_cap():
    overview = "Readable " + ("answer " * 5_000)
    result = _assemble(json.dumps({"overview": overview, "results": [], "uncertainties": []}), [])
    assert result["overview"] == overview


def test_fabricated_ids_never_enter_verified_ledger_or_navigation():
    result = _assemble(json.dumps({
        "overview": "Overview",
        "results": [_result("high_probability", "Fabricated", ["r999999"])],
        "uncertainties": [],
    }), [_record(1)])
    assert "r999999" not in {item["range_id"] for item in result["evidence_ledger"]}
    assert "r999999" not in {item["range_id"] for item in result["unclassified_evidence"]}
    assert result["unverified_model_statements"][0]["reported_range_ids"] == ["r999999"]
