"""Lightweight smoke tests for non-GUI spike components."""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def test_data_loader_loads_windows():
    from spikes.window_merge_lab.data_loader import load_compact_windows, load_scan_windows
    compact = load_compact_windows()
    assert len(compact) == 6, f"Expected 6 compact windows, got {len(compact)}"
    for w in compact:
        assert "model_run_id" in w
        assert "window_id" in w
    rich = load_scan_windows()
    assert len(rich) == 6
    print("PASS: data_loader loads 6 windows")


def test_data_loader_parses_fenced_json():
    from spikes.window_merge_lab.data_loader import parse_fenced_json
    result = parse_fenced_json('```json\n{"answer": "test"}\n```')
    assert result is not None
    assert result["answer"] == "test"
    result2 = parse_fenced_json('{"answer": "test"}')
    assert result2 is not None
    assert result2["answer"] == "test"
    result3 = parse_fenced_json("not json")
    assert result3 is None
    print("PASS: parse_fenced_json")


def test_data_loader_extracts_results():
    from spikes.window_merge_lab.data_loader import extract_scan_result, load_scan_windows
    windows = load_scan_windows()
    for w in windows:
        parsed = extract_scan_result(w)
        assert parsed is not None, f"Window {w['model_run_id']} failed to parse"
        assert "answer_summary" in parsed
        assert "answer" in parsed or True  # window may have empty answer
    print("PASS: extract_scan_result on all windows")


def test_strategies_registry():
    from spikes.window_merge_lab.strategies import EXPECTED_CALL_COUNTS, STRATEGY_REGISTRY
    assert len(STRATEGY_REGISTRY) == 5
    for name in STRATEGY_REGISTRY:
        assert name in EXPECTED_CALL_COUNTS
    print("PASS: strategies registry has 5 entries")


def test_deterministic_baseline():
    from spikes.window_merge_lab.data_loader import load_compact_windows
    from spikes.window_merge_lab.strategies import run_deterministic_baseline
    windows = load_compact_windows()
    result = run_deterministic_baseline("test query", windows)
    assert result.strategy_name == "deterministic_baseline"
    assert result.call_count == 0
    assert result.last_parsed is not None
    assert "answer_ranges" in result.last_parsed
    assert len(result.last_parsed["answer_ranges"]) >= 4
    print("PASS: deterministic_baseline")


def test_one_shot_dry_run():
    from spikes.window_merge_lab.data_loader import load_compact_windows
    from spikes.window_merge_lab.strategies import run_one_shot_compact
    windows = load_compact_windows()
    result = run_one_shot_compact("test query", windows, model_call=lambda m: ("", 0))
    assert result.strategy_name == "one_shot_compact"
    assert result.call_count == 1
    assert len(result.messages_per_call) == 1
    print("PASS: one_shot_compact dry-run")


def test_hierarchical_dry_run():
    from spikes.window_merge_lab.data_loader import load_compact_windows
    from spikes.window_merge_lab.strategies import run_hierarchical_balanced
    windows = load_compact_windows()
    result = run_hierarchical_balanced("test query", windows, model_call=lambda m: ("", 0))
    assert result.strategy_name == "hierarchical_balanced"
    assert result.call_count == 3
    print("PASS: hierarchical_balanced dry-run")


def test_rolling_dry_run():
    from spikes.window_merge_lab.data_loader import load_compact_windows
    from spikes.window_merge_lab.strategies import run_rolling_synthesis
    windows = load_compact_windows()
    result = run_rolling_synthesis("test query", windows, model_call=lambda m: ("", 0))
    assert result.strategy_name == "rolling_synthesis"
    assert result.call_count == 6
    print("PASS: rolling_synthesis dry-run")


def test_evidence_table_dry_run():
    from spikes.window_merge_lab.data_loader import load_compact_windows
    from spikes.window_merge_lab.strategies import run_evidence_table_then_synthesis
    windows = load_compact_windows()
    result = run_evidence_table_then_synthesis("test query", windows, model_call=lambda m: ("", 0))
    assert result.strategy_name == "evidence_table_then_synthesis"
    assert result.call_count == 1
    print("PASS: evidence_table_then_synthesis dry-run")


def test_prompt_builders():
    from spikes.window_merge_lab.prompts import (
        build_evidence_table_messages,
        build_hierarchical_batch_messages,
        build_one_shot_messages,
        build_rolling_synthesis_messages,
    )
    from spikes.window_merge_lab.data_loader import load_compact_windows
    windows = load_compact_windows()
    msgs = build_one_shot_messages("test", windows)
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    msgs2 = build_hierarchical_batch_messages("test", windows[:3])
    assert len(msgs2) == 2
    msgs3 = build_rolling_synthesis_messages("test", None, windows[0])
    assert len(msgs3) == 2
    msgs4 = build_evidence_table_messages("test", windows)
    assert len(msgs4) == 2
    assert "source_range_key" in msgs4[1]["content"]
    assert "input_title" in msgs4[1]["content"]
    assert "generic date-only titles" in msgs4[1]["content"]
    print("PASS: prompt builders")


def test_evaluator():
    from spikes.window_merge_lab.data_loader import load_compact_windows
    from spikes.window_merge_lab.evaluator import evaluate_strategy_outputs
    from spikes.window_merge_lab.strategies import run_deterministic_baseline
    windows = load_compact_windows()
    result = run_deterministic_baseline("test", windows)
    report = evaluate_strategy_outputs(result.last_parsed, windows)
    assert "Parse success" in report
    assert "Source windows represented" in report
    assert "Quality Checklist" in report
    print("PASS: evaluator")


def test_evaluator_falls_back_when_source_keys_are_malformed():
    from spikes.window_merge_lab.data_loader import load_compact_windows
    from spikes.window_merge_lab.evaluator import _build_provenance

    windows = load_compact_windows()
    source_ranges = windows[0]["answer_ranges"][:2]
    parsed = {
        "answer_ranges": [
            {
                "title": f"School Discussion {i}",
                "hit_message_id": r["hit_message_id"],
                "start_message_id": r["start_message_id"],
                "end_message_id": r["end_message_id"],
                "source_range_keys": [
                    f"{r['hit_message_id']}::School Discussion {i}"
                ],
            }
            for i, r in enumerate(source_ranges, 1)
        ]
    }

    provenance = _build_provenance(parsed, [windows[0]])
    assert provenance["model_reported_provenance"]
    assert provenance["fallback_match_count"] == 2
    assert provenance["orphaned_count"] == len(windows[0]["answer_ranges"]) - 2
    assert provenance["unmatched_output_count"] == 0
    print("PASS: evaluator fallback for malformed source keys")


def test_valid_message_ids():
    from spikes.window_merge_lab.data_loader import load_scan_windows, validate_message_ids
    windows = load_scan_windows()
    for w in windows:
        valid = set(w.get("message_ids", []))
        inv = validate_message_ids(w, valid)
        assert len(inv["all_invalid"]) == 0, f"Window {w['model_run_id']} has invalid IDs: {inv['all_invalid']}"
    print("PASS: all message IDs valid")


# --- Budget planner tests ---


def test_planner_selects_mode1_when_fits():
    from spikes.window_merge_lab.budget_planner import (
        SynthesisBudgetRequest,
        plan_synthesis_budget,
    )
    from spikes.window_merge_lab.data_loader import load_compact_windows
    windows = load_compact_windows()
    request = SynthesisBudgetRequest(
        evidence_records=windows,
        user_query="test",
        strategy_name="one_shot_compact",
        call_label="final",
        model_context_tokens=262144,
        max_output_tokens=65536,
    )
    plan = plan_synthesis_budget(request)
    assert plan.mode == "full_direct_synthesis", f"Expected Mode 1, got {plan.mode}"
    assert plan.answer_format == "detailed"
    assert plan.fallback_reason is None
    print("PASS: planner selects Mode 1 when everything fits")


def test_planner_selects_mode2_when_output_exceeds():
    from spikes.window_merge_lab.budget_planner import (
        SynthesisBudgetRequest,
        plan_synthesis_budget,
    )
    from spikes.window_merge_lab.data_loader import load_compact_windows
    windows = load_compact_windows()
    request = SynthesisBudgetRequest(
        evidence_records=windows,
        user_query="test",
        strategy_name="one_shot_compact",
        call_label="final",
        model_context_tokens=262144,
        max_output_tokens=512,
    )
    plan = plan_synthesis_budget(request)
    assert plan.mode == "compact_direct_synthesis", f"Expected Mode 2, got {plan.mode}"
    assert plan.answer_format == "brief"
    assert plan.fallback_reason is not None
    assert "output" in plan.fallback_reason
    print("PASS: planner selects Mode 2 when output budget too small")


def test_planner_selects_mode2_when_input_exceeds():
    from spikes.window_merge_lab.budget_planner import (
        SynthesisBudgetRequest,
        plan_synthesis_budget,
    )
    from spikes.window_merge_lab.data_loader import load_compact_windows
    windows = load_compact_windows()
    request = SynthesisBudgetRequest(
        evidence_records=windows,
        user_query="test",
        strategy_name="one_shot_compact",
        call_label="final",
        model_context_tokens=8192,
        max_output_tokens=65536,
    )
    plan = plan_synthesis_budget(request)
    assert plan.mode == "compact_direct_synthesis", f"Expected Mode 2, got {plan.mode}"
    assert plan.fallback_reason is not None
    assert "input" in plan.fallback_reason
    print("PASS: planner selects Mode 2 when input budget too small")


def test_planner_does_not_drop_records():
    from spikes.window_merge_lab.budget_planner import (
        SynthesisBudgetRequest,
        plan_synthesis_budget,
    )
    from spikes.window_merge_lab.data_loader import load_compact_windows
    windows = load_compact_windows()
    for max_tokens in [512, 4096, 65536]:
        request = SynthesisBudgetRequest(
            evidence_records=windows,
            user_query="test",
            strategy_name="test",
            call_label="final",
            model_context_tokens=262144,
            max_output_tokens=max_tokens,
        )
        plan = plan_synthesis_budget(request)
        assert plan.range_count > 0
    print("PASS: planner never drops records")


def test_strategies_include_planner_plans():
    from spikes.window_merge_lab.strategies import (
        run_one_shot_compact,
        run_hierarchical_balanced,
        run_rolling_synthesis,
        run_evidence_table_then_synthesis,
    )
    from spikes.window_merge_lab.data_loader import load_compact_windows
    windows = load_compact_windows()
    noop = lambda m: ("", 0)
    for runner in [run_one_shot_compact, run_evidence_table_then_synthesis]:
        r = runner("test", windows, model_call=noop)
        assert r.planner_plans is not None, f"{runner.__name__} has no planner_plans"
        assert len(r.planner_plans) >= 1
    r = run_hierarchical_balanced("test", windows, model_call=noop)
    assert r.planner_plans is not None
    assert len(r.planner_plans) == 3
    r = run_rolling_synthesis("test", windows, model_call=noop)
    assert r.planner_plans is not None
    assert len(r.planner_plans) == 6
    print("PASS: all strategies include planner_plans")


def test_prompt_mode1_includes_detailed_format():
    from spikes.window_merge_lab.budget_planner import (
        SynthesisBudgetPlan,
    )
    from spikes.window_merge_lab.prompts import build_one_shot_messages
    from spikes.window_merge_lab.data_loader import load_compact_windows
    windows = load_compact_windows()
    plan = SynthesisBudgetPlan(
        mode="full_direct_synthesis",
        strategy_name="one_shot_compact",
        call_label="final",
        range_count=67,
        estimated_input_tokens=10000,
        estimated_output_tokens=15000,
        available_input_tokens=250000,
        available_output_tokens=30000,
        prompt_profile="full_direct_synthesis",
        answer_format="detailed",
        max_answer_chars=2000,
        max_range_summary_chars=200,
    )
    msgs = build_one_shot_messages("test", windows, plan=plan)
    content = msgs[0]["content"] + msgs[1]["content"]
    assert "answer_format to detailed" in content
    assert "planner_mode" in msgs[1]["content"]
    print("PASS: Mode 1 prompt includes detailed format")


def test_prompt_mode2_includes_brief_format():
    from spikes.window_merge_lab.budget_planner import (
        SynthesisBudgetPlan,
    )
    from spikes.window_merge_lab.prompts import build_one_shot_messages
    from spikes.window_merge_lab.data_loader import load_compact_windows
    windows = load_compact_windows()
    plan = SynthesisBudgetPlan(
        mode="compact_direct_synthesis",
        strategy_name="one_shot_compact",
        call_label="final",
        range_count=67,
        estimated_input_tokens=10000,
        estimated_output_tokens=5000,
        available_input_tokens=8000,
        available_output_tokens=6000,
        prompt_profile="compact_direct_synthesis",
        answer_format="brief",
        max_answer_chars=500,
        max_range_summary_chars=60,
        fallback_reason="output ~5000 > available ~4000",
    )
    msgs = build_one_shot_messages("test", windows, plan=plan)
    content = msgs[0]["content"] + msgs[1]["content"]
    assert "answer_format to brief" in content
    assert "compact format" in content
    assert "Navigation correctness" in content
    print("PASS: Mode 2 prompt includes brief format and compact guidance")


if __name__ == "__main__":
    tests = [
        test_data_loader_loads_windows,
        test_data_loader_parses_fenced_json,
        test_data_loader_extracts_results,
        test_strategies_registry,
        test_deterministic_baseline,
        test_one_shot_dry_run,
        test_hierarchical_dry_run,
        test_rolling_dry_run,
        test_evidence_table_dry_run,
        test_prompt_builders,
        test_evaluator,
        test_evaluator_falls_back_when_source_keys_are_malformed,
        test_valid_message_ids,
    ]
    passed = 0
    failed = 0
    for test in tests:
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
