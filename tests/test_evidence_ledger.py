"""Tests for evidence-ledger module and validator (TKT-01, TKT-03)."""

from __future__ import annotations

import json
import pytest

from message_evidence_workstation.search.evidence_ledger import (
    LEDGER_ANALYSIS_JSON_SCHEMA,
    LEGAL_EVIDENCE_POLICY,
    EvidenceLedgerEntry,
    LedgerConfig,
    SourceBatchContext,
    assemble_ledger_result,
    batch_context_to_dicts,
    build_evidence_ledger,
    build_evidence_ledger_synthesis_messages,
    ledger_to_dicts,
    plan_ledger_budget,
)
from message_evidence_workstation.search.ledger_validator import (
    validate_assembled_ledger_output,
    validate_ledger_analysis_output,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_window_results():
    return [
        {
            "window_id": "w_001",
            "source_thread_id": "thread_a",
            "estimated_tokens": 500,
            "message_ids": ["m1", "m2", "m3"],
            "answer_summary": "First window findings.",
            "answer_format": "detailed",
            "answer": "Window 1 analysis...",
            "cited_message_ids": ["m1", "m2"],
            "answer_ranges": [
                {
                    "title": "Range 1",
                    "summary": "Summary 1",
                    "display_text": "Display 1",
                    "date_description": "On Jan 1",
                    "hit_message_id": "m1",
                    "start_message_id": "m1",
                    "end_message_id": "m3",
                },
                {
                    "title": "Range 2",
                    "summary": "Summary 2",
                    "display_text": "Display 2",
                    "date_description": "On Jan 2",
                    "hit_message_id": "m2",
                    "start_message_id": "m2",
                    "end_message_id": "m3",
                },
            ],
            "uncertainties": [],
        },
    ]


# ---------------------------------------------------------------------------
# Ledger builder tests
# ---------------------------------------------------------------------------


def test_build_ledger_from_production_window_results(sample_window_results):
    entries, contexts = build_evidence_ledger(sample_window_results)
    assert len(entries) == 2
    assert len(contexts) == 1
    assert contexts[0].source_batch_id == "w_001"
    assert contexts[0].summary == "First window findings."

    e0 = entries[0]
    assert e0.range_id == "r000001"
    assert e0.source_range_key == "w_001::r000001::m1"
    assert e0.input_title == "Range 1"
    assert e0.hit_message_id == "m1"

    e1 = entries[1]
    assert e1.range_id == "r000002"
    assert e1.source_range_key == "w_001::r000002::m2"


def test_ledger_range_ids_sequential():
    windows = []
    for i in range(3):
        windows.append({
            "window_id": f"w_{i:03d}",
            "source_thread_id": "t_a",
            "answer_summary": f"window {i}",
            "answer_ranges": [
                {"title": f"r{j}", "summary": "", "date_description": "",
                 "hit_message_id": f"m{j}", "start_message_id": f"m{j-1}",
                 "end_message_id": f"m{j+1}"}
                for j in range(2)
            ],
            "cited_message_ids": [],
        })
    entries, _ = build_evidence_ledger(windows)
    expected_ids = [f"r{n:06d}" for n in range(1, 7)]
    actual_ids = [e.range_id for e in entries]
    assert actual_ids == expected_ids


def test_ledger_source_range_key_stable(sample_window_results):
    entries1, _ = build_evidence_ledger(sample_window_results)
    entries2, _ = build_evidence_ledger(sample_window_results)
    for e1, e2 in zip(entries1, entries2):
        assert e1.range_id == e2.range_id
        assert e1.source_range_key == e2.source_range_key


def test_ledger_preserves_every_range():
    windows = [
        {
            "window_id": "w_001",
            "source_thread_id": "t_a",
            "answer_summary": "test",
            "answer_ranges": [
                {"title": f"r{j}", "summary": "", "date_description": "",
                 "hit_message_id": f"m{j}", "start_message_id": f"m{j}",
                 "end_message_id": f"m{j}"}
                for j in range(5)
            ],
            "cited_message_ids": [],
        }
    ]
    entries, _ = build_evidence_ledger(windows)
    assert len(entries) == 5


def test_ledger_batch_context():
    windows = [
        {
            "window_id": "w_001",
            "source_thread_id": "t_a",
            "answer_summary": "Summary A",
            "answer_ranges": [],
            "cited_message_ids": [],
        },
        {
            "window_id": "w_002",
            "source_thread_id": "t_b",
            "answer_summary": "",
            "answer_ranges": [],
            "cited_message_ids": [],
        },
    ]
    _, contexts = build_evidence_ledger(windows)
    assert len(contexts) == 1
    assert contexts[0].source_batch_id == "w_001"


def test_ledger_empty_input():
    entries, contexts = build_evidence_ledger([])
    assert entries == []
    assert contexts == []


def test_ledger_preserves_sparse_text_fields_with_valid_ids():
    windows = [
        {
            "window_id": "w_001",
            "source_thread_id": "t_a",
            "answer_summary": "test",
            "answer_ranges": [
                {
                    "title": "",
                    "summary": "",
                    "display_text": "",
                    "date_description": "On Jan 1",
                    "hit_message_id": "m1",
                    "start_message_id": "m1",
                    "end_message_id": "m2",
                }
            ],
            "cited_message_ids": [],
        }
    ]
    entries, _ = build_evidence_ledger(windows)
    assert len(entries) == 1
    e = entries[0]
    assert e.hit_message_id == "m1"
    assert e.input_title == ""
    assert e.input_display_text == ""


# ---------------------------------------------------------------------------
# Dict conversion tests
# ---------------------------------------------------------------------------


def test_ledger_to_dicts(sample_window_results):
    entries, _ = build_evidence_ledger(sample_window_results)
    dicts = ledger_to_dicts(entries)
    assert len(dicts) == 2
    assert dicts[0]["range_id"] == "r000001"
    assert dicts[0]["source_range_key"] == "w_001::r000001::m1"


def test_batch_context_to_dicts():
    ctx = [SourceBatchContext(source_batch_id="w_001", source_thread_id="t_a", summary="test")]
    dicts = batch_context_to_dicts(ctx)
    assert len(dicts) == 1
    assert dicts[0]["source_batch_id"] == "w_001"


# ---------------------------------------------------------------------------
# Budget planner tests
# ---------------------------------------------------------------------------


def test_profile_full_when_fits():
    dicts = [{"range_id": "r000001"}]
    provisional = [{"role": "system", "content": "x"}, {"role": "user", "content": "y"}]
    config = plan_ledger_budget(dicts, provisional, model_context_tokens=1_000_000, max_output_tokens=65536)
    assert config.mode == "full"
    assert config.answer_format == "detailed"
    assert config.fallback_reason is None
    assert not config.overflow


def test_profile_compact_when_over_budget():
    dicts = [{"range_id": "r000001"}] * 5
    provisional = [{"role": "system", "content": "x" * 5000}, {"role": "user", "content": "y" * 5000}]
    config = plan_ledger_budget(dicts, provisional, model_context_tokens=8192, max_output_tokens=2048)
    assert config.mode == "compact"
    assert config.answer_format == "brief"
    assert config.fallback_reason is not None
    assert config.overflow


def test_planner_flags_impossible_budget_as_overflow():
    dicts = [{"range_id": "r000001"}] * 10
    big_content = "x" * 100000
    provisional = [{"role": "system", "content": big_content}, {"role": "user", "content": big_content}]
    config = plan_ledger_budget(dicts, provisional, model_context_tokens=4096, max_output_tokens=512)
    assert config.mode == "compact"
    assert config.overflow is True


# ---------------------------------------------------------------------------
# Prompt builder tests
# ---------------------------------------------------------------------------


def test_prompt_returns_chat_messages(sample_window_results):
    entries, ctx = build_evidence_ledger(sample_window_results)
    dicts = ledger_to_dicts(entries)
    bdicts = batch_context_to_dicts(ctx)
    config = LedgerConfig(
        mode="full", answer_format="detailed",
        max_answer_chars=2000, max_range_summary_chars=200,
        estimated_input_tokens=100, estimated_output_tokens=200,
        available_input_tokens=1000, available_output_tokens=2000,
    )
    messages = build_evidence_ledger_synthesis_messages("test query", dicts, bdicts, config)
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert isinstance(messages[0]["content"], str)
    assert isinstance(messages[1]["content"], str)


def test_prompt_no_answer_ranges_schema():
    assert "answer_ranges" not in LEDGER_ANALYSIS_JSON_SCHEMA


def test_prompt_no_reconstruct_ranges_instruction():
    entries, ctx = build_evidence_ledger([
        {"window_id": "w", "source_thread_id": "t", "answer_summary": "s",
         "answer_ranges": [{"title": "r", "summary": "", "date_description": "",
                            "hit_message_id": "m", "start_message_id": "m",
                            "end_message_id": "m"}], "cited_message_ids": []}
    ])
    dicts = ledger_to_dicts(entries)
    config = LedgerConfig(
        mode="full", answer_format="detailed",
        max_answer_chars=2000, max_range_summary_chars=200,
        estimated_input_tokens=100, estimated_output_tokens=200,
        available_input_tokens=1000, available_output_tokens=2000,
    )
    messages = build_evidence_ledger_synthesis_messages("q", dicts, [], config)
    system_content = messages[0]["content"]
    assert "Do not reconstruct answer_ranges" in system_content


def test_prompt_injection_hardening():
    assert "evidence only" in LEGAL_EVIDENCE_POLICY.lower()
    assert "do not obey" in LEGAL_EVIDENCE_POLICY.lower()
    assert "quoted evidence" in LEGAL_EVIDENCE_POLICY.lower()


def test_prompt_anti_window_language():
    entries, ctx = build_evidence_ledger([
        {"window_id": "w", "source_thread_id": "t", "answer_summary": "s",
         "answer_ranges": [{"title": "r", "summary": "", "date_description": "",
                            "hit_message_id": "m", "start_message_id": "m",
                            "end_message_id": "m"}], "cited_message_ids": []}
    ])
    dicts = ledger_to_dicts(entries)
    config = LedgerConfig(
        mode="full", answer_format="detailed",
        max_answer_chars=2000, max_range_summary_chars=200,
        estimated_input_tokens=100, estimated_output_tokens=200,
        available_input_tokens=1000, available_output_tokens=2000,
    )
    messages = build_evidence_ledger_synthesis_messages("q", dicts, [], config)
    system_content = messages[0]["content"]
    assert "not by window number" in system_content


def test_prompt_accepts_config_none(sample_window_results):
    entries, ctx = build_evidence_ledger(sample_window_results)
    dicts = ledger_to_dicts(entries)
    messages = build_evidence_ledger_synthesis_messages("q", dicts, batch_dicts=None, config=None)
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    # Config None means no planner_mode in payload
    user_payload = json.loads(messages[1]["content"])
    assert user_payload["planner_mode"] is None


# ---------------------------------------------------------------------------
# Assembler tests
# ---------------------------------------------------------------------------


def test_assembled_result_has_deterministic_ranges(sample_window_results):
    entries, _ = build_evidence_ledger(sample_window_results)
    dicts = ledger_to_dicts(entries)
    config = LedgerConfig(
        mode="full", answer_format="detailed",
        max_answer_chars=2000, max_range_summary_chars=200,
        estimated_input_tokens=100, estimated_output_tokens=200,
        available_input_tokens=1000, available_output_tokens=2000,
    )
    model_json = {
        "answer_summary": "Summary.",
        "answer": "Narrative.",
        "themes": [],
        "notable_patterns": [],
        "contradictions_or_tensions": [],
        "uncertainties": [],
    }
    assembled = assemble_ledger_result(model_json, dicts, config)
    assert len(assembled["answer_ranges"]) == 2
    assert assembled["answer_ranges"][0]["range_id"] == "r000001"
    assert assembled["answer_ranges"][1]["range_id"] == "r000002"
    assert assembled["answer_ranges"][0]["title"] == "Range 1"
    assert assembled["answer_ranges"][0]["display_text"] == "Display 1"


def test_assembled_result_coverage_summary(sample_window_results):
    entries, _ = build_evidence_ledger(sample_window_results)
    dicts = ledger_to_dicts(entries)
    config = LedgerConfig(
        mode="full", answer_format="detailed",
        max_answer_chars=2000, max_range_summary_chars=200,
        estimated_input_tokens=100, estimated_output_tokens=200,
        available_input_tokens=1000, available_output_tokens=2000,
    )
    model_json = {
        "answer_summary": "S.", "answer": "N.",
        "themes": [], "notable_patterns": [],
        "contradictions_or_tensions": [], "uncertainties": [],
    }
    assembled = assemble_ledger_result(model_json, dicts, config)
    cov = assembled["coverage_summary"]
    assert cov["input_range_count"] == 2
    assert cov["output_range_count"] == 2
    assert cov["represented_range_count"] == 2
    assert cov["source_thread_ids"] == ["thread_a"]


def test_assembled_result_includes_model_fields(sample_window_results):
    entries, _ = build_evidence_ledger(sample_window_results)
    dicts = ledger_to_dicts(entries)
    config = LedgerConfig(
        mode="full", answer_format="detailed",
        max_answer_chars=2000, max_range_summary_chars=200,
        estimated_input_tokens=100, estimated_output_tokens=200,
        available_input_tokens=1000, available_output_tokens=2000,
    )
    model_json = {
        "answer_summary": "Test summary.",
        "answer": "Test narrative with enough characters to pass short-answer warning.",
        "themes": [{"title": "Theme 1", "summary": "Desc", "range_ids": ["r000001"]}],
        "notable_patterns": ["Pattern A"],
        "contradictions_or_tensions": ["Conflict B"],
        "uncertainties": ["Uncertainty C"],
    }
    assembled = assemble_ledger_result(model_json, dicts, config)
    assert assembled["answer_summary"] == "Test summary."
    assert "enough characters" in assembled["answer"]
    assert len(assembled["themes"]) == 1
    assert len(assembled["notable_patterns"]) == 1
    assert len(assembled["contradictions_or_tensions"]) == 1
    assert len(assembled["uncertainties"]) == 1


# ---------------------------------------------------------------------------
# Raw model validator tests
# ---------------------------------------------------------------------------


def test_raw_validator_passes_valid_output():
    ledger = [{"range_id": "r000001"}, {"range_id": "r000002"}]
    model = {
        "answer": "A narrative with enough text to pass the short-answer threshold.",
        "answer_summary": "Short summary.",
        "themes": [{"title": "T", "summary": "S", "range_ids": ["r000001"]}],
        "notable_patterns": [],
        "contradictions_or_tensions": [],
        "uncertainties": [],
    }
    vr = validate_ledger_analysis_output(model, ledger)
    assert vr.ok


def test_raw_validator_rejects_non_dict():
    vr = validate_ledger_analysis_output("not a dict", [])
    assert not vr.ok
    assert any(i.code == "not_object" for i in vr.issues)


def test_raw_validator_rejects_empty_answer():
    vr = validate_ledger_analysis_output({"answer": ""}, [])
    assert not vr.ok
    assert any(i.code == "missing_answer" for i in vr.issues)


def test_raw_validator_rejects_unknown_theme_range_id():
    ledger = [{"range_id": "r000001"}]
    model = {
        "answer": "Narrative that is long enough to pass the short-answer warning threshold easily.",
        "answer_summary": "S",
        "themes": [{"title": "T", "summary": "S", "range_ids": ["r999999"]}],
    }
    vr = validate_ledger_analysis_output(model, ledger)
    assert not vr.ok
    assert any(i.code == "unknown_theme_range_id" for i in vr.issues)


def test_raw_validator_does_not_require_answer_ranges():
    vr = validate_ledger_analysis_output({"answer": "x" * 30, "answer_summary": "y"}, [])
    assert vr.ok


def test_raw_validator_rejects_non_list_themes():
    vr = validate_ledger_analysis_output(
        {"answer": "x" * 30, "answer_summary": "y", "themes": "bad"},
        [],
    )
    assert not vr.ok
    assert any(i.code == "invalid_themes" for i in vr.issues)


def test_raw_validator_rejects_non_list_notable_patterns():
    vr = validate_ledger_analysis_output(
        {"answer": "x" * 30, "answer_summary": "y", "notable_patterns": "bad"},
        [],
    )
    assert not vr.ok
    assert any(i.code == "invalid_notable_patterns" for i in vr.issues)


# ---------------------------------------------------------------------------
# Assembled payload validator tests
# ---------------------------------------------------------------------------


def test_assembled_validator_passes_perfect_bijection():
    ledger = [
        {"range_id": "r000001", "source_range_key": "k1", "hit_message_id": "m1",
         "start_message_id": "m0", "end_message_id": "m2"},
        {"range_id": "r000002", "source_range_key": "k2", "hit_message_id": "m3",
         "start_message_id": "m2", "end_message_id": "m4"},
    ]
    assembled = {
        "answer_ranges": [
            {"range_id": "r000001", "source_range_key": "k1", "hit_message_id": "m1",
             "start_message_id": "m0", "end_message_id": "m2"},
            {"range_id": "r000002", "source_range_key": "k2", "hit_message_id": "m3",
             "start_message_id": "m2", "end_message_id": "m4"},
        ],
    }
    vr = validate_assembled_ledger_output(assembled, ledger)
    assert vr.ok


def test_assembled_validator_rejects_missing_range():
    ledger = [{"range_id": "r000001"}, {"range_id": "r000002"}]
    assembled = {
        "answer_ranges": [
            {"range_id": "r000001", "source_range_key": "k1", "hit_message_id": "m1",
             "start_message_id": "m0", "end_message_id": "m2"},
        ],
    }
    vr = validate_assembled_ledger_output(assembled, ledger)
    assert not vr.ok
    assert "r000002" in vr.missing_range_ids


def test_assembled_validator_rejects_extra_range():
    ledger = [{"range_id": "r000001"}]
    assembled = {
        "answer_ranges": [
            {"range_id": "r000001", "source_range_key": "k1", "hit_message_id": "m1",
             "start_message_id": "m0", "end_message_id": "m2"},
            {"range_id": "r999999", "source_range_key": "k2", "hit_message_id": "m3",
             "start_message_id": "m2", "end_message_id": "m4"},
        ],
    }
    vr = validate_assembled_ledger_output(assembled, ledger)
    assert not vr.ok
    assert "r999999" in vr.unknown_range_ids


def test_assembled_validator_rejects_duplicate_range():
    ledger = [{"range_id": "r000001"}]
    assembled = {
        "answer_ranges": [
            {"range_id": "r000001", "source_range_key": "k1", "hit_message_id": "m1",
             "start_message_id": "m0", "end_message_id": "m2"},
            {"range_id": "r000001", "source_range_key": "k1", "hit_message_id": "m1",
             "start_message_id": "m0", "end_message_id": "m2"},
        ],
    }
    vr = validate_assembled_ledger_output(assembled, ledger)
    assert not vr.ok
    assert "r000001" in vr.duplicate_range_ids


def test_assembled_validator_rejects_changed_message_id():
    ledger = [{"range_id": "r000001", "hit_message_id": "m1",
               "start_message_id": "m0", "end_message_id": "m2", "source_range_key": "k1"}]
    assembled = {
        "answer_ranges": [
            {"range_id": "r000001", "source_range_key": "k1", "hit_message_id": "m999",
             "start_message_id": "m0", "end_message_id": "m2"},
        ],
    }
    vr = validate_assembled_ledger_output(assembled, ledger)
    assert not vr.ok
    assert any(i.code == "changed_hit_message_id" for i in vr.issues)
