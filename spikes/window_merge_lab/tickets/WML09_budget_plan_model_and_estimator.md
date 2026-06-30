# WML09 - Budget Plan Model And Estimator

## Goal
Add the core data structures and conservative token estimates needed to choose between full and compact direct synthesis for each LLM merge call.

## Depends On
- WML08

## Scope

Add a spike-local planner module, for example:

```text
spikes/window_merge_lab/budget_planner.py
```

Define:

```python
@dataclass
class SynthesisBudgetRequest:
    evidence_records: list[dict]
    user_query: str
    strategy_name: str
    call_label: str
    model_context_tokens: int
    max_output_tokens: int
    model_context_tokens: int
    reserved_margin_tokens: int = 2_000
    target_input_margin_ratio: float = 0.85
```

```python
@dataclass
class SynthesisBudgetPlan:
    mode: Literal["full_direct_synthesis", "compact_direct_synthesis"]
    strategy_name: str
    call_label: str
    range_count: int
    estimated_input_tokens: int
    estimated_output_tokens: int
    available_input_tokens: int
    available_output_tokens: int
    prompt_profile: str
    answer_format: Literal["detailed", "brief"]
    max_answer_chars: int
    max_range_summary_chars: int
    fallback_reason: str | None = None
```

Add helper estimates:

- `estimate_json_tokens(value: object) -> int`
- `estimate_full_direct_output_tokens(range_count: int) -> int`
- `estimate_compact_direct_output_tokens(range_count: int) -> int`
- `plan_synthesis_budget(request: SynthesisBudgetRequest) -> SynthesisBudgetPlan`

Suggested estimates:

```python
tokens = ceil(serialized_json_chars / 3.5)
full_output = base_answer_tokens + range_count * 190
compact_output = compact_answer_tokens + range_count * 110
```

Use conservative defaults:

```python
base_answer_tokens = 1_500
compact_answer_tokens = 700
```

Per-range constants are calibrated from actual run data (hierarchical C3: ~11,200 tokens for 67 ranges, ~195/range) with ~20% safety margin.

## Mode Selection

Implement:

```python
if full_input <= available_input and full_output <= available_output:
    return full_direct_synthesis

return compact_direct_synthesis
```

Mode 2 is a valid preservation-first mode, not a failure mode.

## Strategy Coverage

The planner must be strategy-agnostic. It should accept the records for one planned LLM call and return a prompt profile for that call.

Apply it to:

- `one_shot_compact`: one plan for the single all-window merge call.
- `evidence_table_then_synthesis`: one plan for the single compact-record synthesis call.
- `hierarchical_balanced`: one plan for each batch merge call and one plan for the final interim-merge call.
- `rolling_synthesis`: one plan for each rolling merge call.

Do not apply it to `deterministic_baseline`; that strategy has no LLM prompt.

## Context Source

`model_context_tokens` is provided by a new `QSpinBox` in the spike GUI (WML12), alongside the existing `max_output_tokens` field. The production app already has a model context override; the spike mirrors that field so the planner can use it.

## Guardrails

- Do not add `too_large_refine_query`.
- Do not drop or trim records in the planner.
- Do not make LLM calls in the planner.
- Keep estimates deterministic and easy to test.
- Do not hard-code behavior for only one strategy.

## Acceptance Criteria

- Planner selects Mode 1 when full estimates fit.
- Planner selects Mode 2 when full output estimate exceeds available output.
- Planner still selects Mode 2 when full input estimate exceeds available input.
- Plan includes useful `fallback_reason` when Mode 2 is chosen.
- Plan preserves `strategy_name` and `call_label` for metrics/debugging.
- Unit tests cover boundary cases around output budget and input budget.
