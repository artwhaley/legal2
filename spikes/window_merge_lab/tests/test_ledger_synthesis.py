"""Tests for evidence ledger synthesis: ledger, validator, and end-to-end flow."""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_record(range_id: str, **kw) -> dict:
    return {
        "range_id": range_id,
        "source_range_key": f"window_001::{range_id}::msg_001",
        "source_batch_id": "window_001",
        "source_thread_id": "thread_a",
        "input_title": "Tummy aches",
        "input_summary": "Olivia tummy aches",
        "date_description": "On Feb 21",
        "hit_message_id": "msg_001",
        "start_message_id": "msg_000",
        "end_message_id": "msg_002",
        **kw,
    }


# ---------------------------------------------------------------------------
# Ledger tests
# ---------------------------------------------------------------------------


def test_ledger_builds_records():
    from spikes.window_merge_lab.ledger import build_ledger, ledger_to_dicts
    windows = [
        {
            "window_id": "w_001",
            "source_thread_id": "t_a",
            "answer_summary": "test",
            "answer_ranges": [
                {
                    "title": "First range",
                    "summary": "desc",
                    "date_description": "On Jan 1",
                    "hit_message_id": "m1",
                    "start_message_id": "m0",
                    "end_message_id": "m2",
                }
            ],
            "cited_message_ids": ["m0", "m1", "m2"],
        }
    ]
    records, batch_ctx = build_ledger(windows)
    assert len(records) == 1
    r = records[0]
    assert r.range_id == "r000001"
    assert r.source_range_key == "w_001::r000001::m1"
    assert r.input_title == "First range"
    assert r.hit_message_id == "m1"

    dicts = ledger_to_dicts(records)
    assert len(dicts) == 1
    assert dicts[0]["range_id"] == "r000001"
    assert dicts[0]["source_range_key"] == "w_001::r000001::m1"
    print("PASS: ledger builds records with stable range_id")


def test_ledger_range_ids_are_sequential():
    from spikes.window_merge_lab.ledger import build_ledger, ledger_to_dicts
    windows = []
    for i in range(5):
        windows.append({
            "window_id": f"w_{i:03d}",
            "source_thread_id": "t_a",
            "answer_summary": f"window {i}",
            "answer_ranges": [
                {"title": f"r{j}", "summary": "", "date_description": "",
                 "hit_message_id": f"m{j}", "start_message_id": f"m{j-1}",
                 "end_message_id": f"m{j+1}"}
                for j in range(3)
            ],
            "cited_message_ids": [],
        })
    records, _ = build_ledger(windows)
    expected_ids = [f"r{n:06d}" for n in range(1, 16)]
    actual_ids = [r.range_id for r in records]
    assert actual_ids == expected_ids, f"Expected {expected_ids}, got {actual_ids}"
    print("PASS: ledger range_ids are sequential across windows")


def test_ledger_source_range_key_stable():
    from spikes.window_merge_lab.ledger import build_ledger, ledger_to_dicts
    windows = [
        {
            "window_id": "w_001",
            "source_thread_id": "t_a",
            "answer_summary": "test",
            "answer_ranges": [
                {"title": "A", "summary": "s", "date_description": "d",
                 "hit_message_id": "m1", "start_message_id": "m0",
                 "end_message_id": "m2"},
                {"title": "B", "summary": "s", "date_description": "d",
                 "hit_message_id": "m3", "start_message_id": "m0",
                 "end_message_id": "m4"},
            ],
            "cited_message_ids": [],
        }
    ]
    recs1, _ = build_ledger(windows)
    recs2, _ = build_ledger(windows)
    for r1, r2 in zip(recs1, recs2):
        assert r1.range_id == r2.range_id
        assert r1.source_range_key == r2.source_range_key
    print("PASS: ledger source_range_key is stable across builds")


def test_batch_context_generation():
    from spikes.window_merge_lab.ledger import build_ledger, batch_context_to_dicts
    windows = [
        {
            "window_id": "w_001",
            "source_thread_id": "t_a",
            "answer_summary": "Window about school",
            "answer_ranges": [
                {"title": "A", "summary": "s", "date_description": "d",
                 "hit_message_id": "m1", "start_message_id": "m0",
                 "end_message_id": "m2"},
            ],
            "cited_message_ids": [],
        }
    ]
    _, ctx = build_ledger(windows)
    dicts = batch_context_to_dicts(ctx)
    assert len(dicts) == 1
    assert dicts[0]["source_batch_id"] == "w_001"
    assert "summary" in dicts[0]
    print("PASS: batch context generated")


# ---------------------------------------------------------------------------
# Validator tests
# ---------------------------------------------------------------------------


def test_validator_passes_perfect_output():
    from spikes.window_merge_lab.validator import validate_synthesis_output
    records = [_make_record("r000001"), _make_record("r000002")]
    response = {
        "answer_summary": "Great answer",
        "answer_format": "detailed",
        "answer": "Full narrative here",
        "answer_ranges": [
            {"range_id": "r000001", "source_range_key": "w_001::r000001::msg_001",
             "title": "Tummy aches", "summary": "desc", "date_description": "On Feb 21",
             "display_text": "Some text", "hit_message_id": "msg_001",
             "start_message_id": "msg_000", "end_message_id": "msg_002"},
            {"range_id": "r000002", "source_range_key": "w_001::r000002::msg_001",
             "title": "More aches", "summary": "desc2", "date_description": "On Feb 22",
             "display_text": "More text", "hit_message_id": "msg_001",
             "start_message_id": "msg_000", "end_message_id": "msg_002"},
        ],
        "uncertainties": [],
        "coverage_summary": {"mode": "full", "input_range_count": 2,
                            "output_range_count": 2, "represented_range_count": 2,
                            "source_thread_ids": ["thread_a"]},
    }
    vr = validate_synthesis_output(response, records, "full")
    assert vr.ok, f"Expected pass, got issues: {vr.issues}"
    assert vr.represented_range_count == 2
    assert len(vr.missing_range_ids) == 0
    assert len(vr.unknown_range_ids) == 0
    assert len(vr.duplicate_range_ids) == 0
    print("PASS: validator passes perfect output")


def test_validator_rejects_missing_range():
    from spikes.window_merge_lab.validator import validate_synthesis_output
    records = [_make_record("r000001"), _make_record("r000002")]
    response = {
        "answer_summary": "Partial",
        "answer_format": "detailed",
        "answer": "Only one range",
        "answer_ranges": [
            {"range_id": "r000001", "source_range_key": "w_001::r000001::msg_001",
             "title": "Tummy aches", "summary": "desc", "date_description": "On Feb 21",
             "display_text": "Some text", "hit_message_id": "msg_001",
             "start_message_id": "msg_000", "end_message_id": "msg_002"},
        ],
        "uncertainties": [],
        "coverage_summary": {"mode": "full", "input_range_count": 1,
                            "output_range_count": 1, "represented_range_count": 1,
                            "source_thread_ids": ["thread_a"]},
    }
    vr = validate_synthesis_output(response, records, "full")
    assert not vr.ok
    assert "r000002" in vr.missing_range_ids
    assert any(i.code == "missing_range_id" for i in vr.issues)
    print("PASS: validator rejects missing range")


def test_validator_rejects_unknown_range():
    from spikes.window_merge_lab.validator import validate_synthesis_output
    records = [_make_record("r000001")]
    response = {
        "answer_summary": "Extra",
        "answer_format": "detailed",
        "answer": "Has extra range",
        "answer_ranges": [
            {"range_id": "r000001", "source_range_key": "w_001::r000001::msg_001",
             "title": "Tummy aches", "summary": "desc", "date_description": "On Feb 21",
             "display_text": "Some text", "hit_message_id": "msg_001",
             "start_message_id": "msg_000", "end_message_id": "msg_002"},
            {"range_id": "r999999", "source_range_key": "w_001::r999999::msg_001",
             "title": "Fake", "summary": "fake", "date_description": "On Mar 1",
             "display_text": "Fake text", "hit_message_id": "msg_001",
             "start_message_id": "msg_000", "end_message_id": "msg_002"},
        ],
        "uncertainties": [],
        "coverage_summary": {"mode": "full", "input_range_count": 1,
                            "output_range_count": 2, "represented_range_count": 1,
                            "source_thread_ids": ["thread_a"]},
    }
    vr = validate_synthesis_output(response, records, "full")
    assert not vr.ok
    assert "r999999" in vr.unknown_range_ids
    print("PASS: validator rejects unknown range")


def test_validator_rejects_duplicate_range():
    from spikes.window_merge_lab.validator import validate_synthesis_output
    records = [_make_record("r000001")]
    response = {
        "answer_summary": "Dup",
        "answer_format": "detailed",
        "answer": "Has duplicate range",
        "answer_ranges": [
            {"range_id": "r000001", "source_range_key": "w_001::r000001::msg_001",
             "title": "First", "summary": "a", "date_description": "d",
             "display_text": "t", "hit_message_id": "msg_001",
             "start_message_id": "msg_000", "end_message_id": "msg_002"},
            {"range_id": "r000001", "source_range_key": "w_001::r000001::msg_001",
             "title": "Second", "summary": "b", "date_description": "d",
             "display_text": "t", "hit_message_id": "msg_001",
             "start_message_id": "msg_000", "end_message_id": "msg_002"},
        ],
        "uncertainties": [],
        "coverage_summary": {"mode": "full", "input_range_count": 1,
                            "output_range_count": 2, "represented_range_count": 1,
                            "source_thread_ids": ["thread_a"]},
    }
    vr = validate_synthesis_output(response, records, "full")
    assert not vr.ok
    assert "r000001" in vr.duplicate_range_ids
    print("PASS: validator rejects duplicate range")


def test_validator_rejects_changed_message_id():
    from spikes.window_merge_lab.validator import validate_synthesis_output
    records = [_make_record("r000001", hit_message_id="msg_001")]
    response = {
        "answer_summary": "Changed",
        "answer_format": "detailed",
        "answer": "Changed message ID",
        "answer_ranges": [
            {"range_id": "r000001", "source_range_key": "w_001::r000001::msg_001",
             "title": "Tummy aches", "summary": "desc", "date_description": "On Feb 21",
             "display_text": "Some text", "hit_message_id": "msg_999",
             "start_message_id": "msg_000", "end_message_id": "msg_002"},
        ],
        "uncertainties": [],
        "coverage_summary": {"mode": "full", "input_range_count": 1,
                            "output_range_count": 1, "represented_range_count": 0,
                            "source_thread_ids": ["thread_a"]},
    }
    vr = validate_synthesis_output(response, records, "full")
    assert not vr.ok
    assert any(i.code == "changed_hit_message_id" for i in vr.issues)
    print("PASS: validator rejects changed message ID")


def test_validator_accepts_compact_as_valid():
    from spikes.window_merge_lab.validator import validate_synthesis_output
    records = [_make_record("r000001")]
    response = {
        "answer_summary": "Short",
        "answer_format": "brief",
        "answer": "Compact answer",
        "answer_ranges": [
            {"range_id": "r000001", "source_range_key": "w_001::r000001::msg_001",
             "title": "Tummy aches", "summary": "Short", "date_description": "On Feb 21",
             "display_text": "Short", "hit_message_id": "msg_001",
             "start_message_id": "msg_000", "end_message_id": "msg_002"},
        ],
        "uncertainties": [],
        "coverage_summary": {"mode": "compact", "input_range_count": 1,
                            "output_range_count": 1, "represented_range_count": 1,
                            "source_thread_ids": ["thread_a"]},
    }
    vr = validate_synthesis_output(response, records, "compact")
    assert vr.ok, f"Expected OA, got errors: {[i for i in vr.issues if i.severity == 'error']}"
    print("PASS: validator accepts compact mode as valid")


def test_validator_not_json():
    from spikes.window_merge_lab.validator import validate_synthesis_output
    vr = validate_synthesis_output("not a dict", [], "full")
    assert not vr.ok
    assert any(i.code == "not_object" for i in vr.issues)
    print("PASS: validator rejects non-object response")


def test_validator_missing_answer_ranges():
    from spikes.window_merge_lab.validator import validate_synthesis_output
    vr = validate_synthesis_output({"answer_summary": "x"}, [], "full")
    assert not vr.ok
    assert any(i.code == "missing_answer_ranges" for i in vr.issues)
    print("PASS: validator rejects missing answer_ranges")


# ---------------------------------------------------------------------------
# End-to-end ledger synthesis dry-run test
# ---------------------------------------------------------------------------


def test_ledger_synthesis_dry_run():
    from spikes.window_merge_lab.data_loader import load_compact_windows
    from spikes.window_merge_lab.strategies import run_evidence_ledger_synthesis
    windows = load_compact_windows()
    result = run_evidence_ledger_synthesis(
        "test query", windows, model_call=lambda m: ("{}", 0)
    )
    assert result.strategy_name == "evidence_ledger_synthesis"
    assert result.call_count == 1
    assert len(result.messages_per_call) == 1
    assert result.planner_plans is not None
    assert len(result.planner_plans) >= 1
    plan = result.planner_plans[0]
    assert plan.get("mode") in ("full", "compact")
    print("PASS: evidence_ledger_synthesis dry-run")


def test_ledger_synthesis_provisional_build_flow():
    from spikes.window_merge_lab.data_loader import load_compact_windows
    from spikes.window_merge_lab.strategies import run_evidence_ledger_synthesis
    windows = load_compact_windows()
    # Use a noop model call that returns valid JSON
    result = run_evidence_ledger_synthesis(
        "test query", windows,
        model_call=lambda m: ('{"answer_summary": "x", "answer_format": "detailed", '
                              '"answer": "y", "answer_ranges": [], '
                              '"uncertainties": [], "coverage_summary": {'
                              '"mode": "full", "input_range_count": 0, '
                              '"output_range_count": 0, "represented_range_count": 0, '
                              '"source_thread_ids": []}}', 0),
        model_context_tokens=262144,
        max_output_tokens=65536,
    )
    plan = result.planner_plans[0]
    assert plan.get("mode") == "full", f"Expected full with big context, got {plan.get('mode')}"
    assert plan.get("estimated_input_tokens", 0) > 0
    print("PASS: evidence_ledger_synthesis provisional-build flow works")


def test_ledger_synthesis_uses_anti_window_language():
    from spikes.window_merge_lab.prompts import build_evidence_ledger_synthesis_messages
    records = [
        {
            "range_id": "r000001",
            "source_range_key": "w001::r000001::m1",
            "source_batch_id": "w001",
            "source_thread_id": "t_a",
            "input_title": "Test",
            "input_summary": "Test summary",
            "date_description": "On Jan 1",
            "hit_message_id": "m1",
            "start_message_id": "m0",
            "end_message_id": "m2",
        }
    ]
    msgs = build_evidence_ledger_synthesis_messages("test", records)
    content = (msgs[0]["content"] + msgs[1]["content"]).lower()
    assert "source batch" in content.lower()
    assert "ledger records" in content.lower()
    print("PASS: evidence_ledger uses ledger and source-batch language")


# ---------------------------------------------------------------------------
# Bijection tests
# ---------------------------------------------------------------------------


def test_bijection_pass():
    from spikes.window_merge_lab.validator import validate_synthesis_output
    records = [_make_record(f"r{n:06d}") for n in range(1, 4)]
    response = {
        "answer_summary": "x", "answer_format": "detailed", "answer": "y",
        "answer_ranges": [
            {"range_id": r["range_id"],
             "source_range_key": r["source_range_key"],
             "title": "A", "summary": "s", "date_description": "d",
             "display_text": "t", "hit_message_id": r["hit_message_id"],
             "start_message_id": r["start_message_id"],
             "end_message_id": r["end_message_id"]}
            for r in records
        ],
        "uncertainties": [],
        "coverage_summary": {"mode": "full", "input_range_count": 3,
                            "output_range_count": 3, "represented_range_count": 3,
                            "source_thread_ids": ["thread_a"]},
    }
    vr = validate_synthesis_output(response, records, "full")
    assert vr.ok
    assert vr.represented_range_count == 3
    print("PASS: bijection pass — N in, N out")


def test_bijection_fail_missing():
    from spikes.window_merge_lab.validator import validate_synthesis_output
    records = [_make_record(f"r{n:06d}") for n in range(1, 4)]
    response = {
        "answer_summary": "x", "answer_format": "detailed", "answer": "y",
        "answer_ranges": [
            {"range_id": "r000001", "source_range_key": "w::r000001::m",
             "title": "A", "summary": "s", "date_description": "d",
             "display_text": "t", "hit_message_id": "m",
             "start_message_id": "m0", "end_message_id": "m2"},
        ],
        "uncertainties": [],
        "coverage_summary": {"mode": "full", "input_range_count": 3,
                            "output_range_count": 1, "represented_range_count": 1,
                            "source_thread_ids": ["thread_a"]},
    }
    vr = validate_synthesis_output(response, records, "full")
    assert not vr.ok
    assert len(vr.missing_range_ids) == 2
    print("PASS: bijection fail — missing 2 of 3")


def test_bijection_fail_extra():
    from spikes.window_merge_lab.validator import validate_synthesis_output
    records = [_make_record("r000001")]
    response = {
        "answer_summary": "x", "answer_format": "detailed", "answer": "y",
        "answer_ranges": [
            {"range_id": "r000001", "source_range_key": "w::r000001::m",
             "title": "A", "summary": "s", "date_description": "d",
             "display_text": "t", "hit_message_id": "m",
             "start_message_id": "m0", "end_message_id": "m2"},
            {"range_id": "r999999", "source_range_key": "w::r999999::m",
             "title": "B", "summary": "s", "date_description": "d",
             "display_text": "t", "hit_message_id": "m",
             "start_message_id": "m0", "end_message_id": "m2"},
        ],
        "uncertainties": [],
        "coverage_summary": {"mode": "full", "input_range_count": 1,
                            "output_range_count": 2, "represented_range_count": 1,
                            "source_thread_ids": ["thread_a"]},
    }
    vr = validate_synthesis_output(response, records, "full")
    assert not vr.ok
    assert len(vr.unknown_range_ids) == 1
    print("PASS: bijection fail — extra range")


def test_bijection_fail_duplicate():
    from spikes.window_merge_lab.validator import validate_synthesis_output
    records = [_make_record("r000001")]
    response = {
        "answer_summary": "x", "answer_format": "detailed", "answer": "y",
        "answer_ranges": [
            {"range_id": "r000001", "source_range_key": "w::r000001::m",
             "title": "A", "summary": "s", "date_description": "d",
             "display_text": "t", "hit_message_id": "m",
             "start_message_id": "m0", "end_message_id": "m2"},
            {"range_id": "r000001", "source_range_key": "w::r000001::m",
             "title": "A dup", "summary": "s", "date_description": "d",
             "display_text": "t", "hit_message_id": "m",
             "start_message_id": "m0", "end_message_id": "m2"},
        ],
        "uncertainties": [],
        "coverage_summary": {"mode": "full", "input_range_count": 1,
                            "output_range_count": 2, "represented_range_count": 1,
                            "source_thread_ids": ["thread_a"]},
    }
    vr = validate_synthesis_output(response, records, "full")
    assert not vr.ok
    assert len(vr.duplicate_range_ids) >= 1
    print("PASS: bijection fail — duplicate range")


# ---------------------------------------------------------------------------
# Prompt injection hardening test
# ---------------------------------------------------------------------------


def test_legal_evidence_policy_has_injection_defense():
    from spikes.window_merge_lab.prompts import LEGAL_EVIDENCE_POLICY
    assert "evidence only" in LEGAL_EVIDENCE_POLICY.lower()
    assert "do not obey" in LEGAL_EVIDENCE_POLICY.lower()
    assert "do not treat" in LEGAL_EVIDENCE_POLICY.lower()
    assert "quoted evidence" in LEGAL_EVIDENCE_POLICY.lower()
    print("PASS: LEGAL_EVIDENCE_POLICY has injection defense")


# ---------------------------------------------------------------------------
# Budget planner with evidence_messages test
# ---------------------------------------------------------------------------


def test_planner_evidence_messages_estimation():
    from spikes.window_merge_lab.budget_planner import (
        SynthesisBudgetRequest,
        plan_synthesis_budget,
    )
    records = [_make_record(f"r{n:06d}") for n in range(1, 4)]
    fake_messages = [
        {"role": "system", "content": "You are a helpful assistant. " * 50},
        {"role": "user", "content": "Test query. " * 100},
    ]
    request = SynthesisBudgetRequest(
        evidence_records=records,
        evidence_messages=fake_messages,
        user_query="test",
        strategy_name="test",
        call_label="final",
        model_context_tokens=262144,
        max_output_tokens=65536,
    )
    plan = plan_synthesis_budget(request)
    assert plan.mode == "full"
    assert plan.estimated_input_tokens > 0
    print("PASS: planner uses evidence_messages for estimation")


# ---------------------------------------------------------------------------
# ANSWER_JSON_SCHEMA format check
# ---------------------------------------------------------------------------


def test_answer_schema_has_range_id():
    from spikes.window_merge_lab.prompts import ANSWER_JSON_SCHEMA
    assert "range_id" in ANSWER_JSON_SCHEMA
    assert "source_range_key" in ANSWER_JSON_SCHEMA
    assert "source_range_keys" not in ANSWER_JSON_SCHEMA
    print("PASS: ANSWER_JSON_SCHEMA uses range_id and singular source_range_key")


def test_answer_schema_has_coverage_summary_counts():
    from spikes.window_merge_lab.prompts import ANSWER_JSON_SCHEMA
    assert "input_range_count" in ANSWER_JSON_SCHEMA
    assert "output_range_count" in ANSWER_JSON_SCHEMA
    assert "represented_range_count" in ANSWER_JSON_SCHEMA
    print("PASS: ANSWER_JSON_SCHEMA has coverage summary counts")


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    passed = 0
    failed = 0
    for test in sorted(tests, key=lambda t: t.__name__):
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"FAIL: {test.__name__}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    print(f"\n{passed}/{passed + failed} tests passed")
    sys.exit(0 if failed == 0 else 1)
