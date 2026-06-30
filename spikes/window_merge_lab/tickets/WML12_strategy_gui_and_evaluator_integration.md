# WML12 - Strategy GUI And Evaluator Integration

## Goal
Wire the synthesis budget planner into every LLM-backed strategy execution path, output metrics, GUI visibility, and evaluator behavior.

## Depends On
- WML11

## Scope

Update all LLM-backed strategies so they:

- Build compact evidence records.
- Call the planner before building each LLM call's final messages.
- Select Mode 1 or Mode 2.
- Pass the selected prompt profile into the prompt builder.
- Save planner details in `metrics.json`.
- Include planner mode in `prompt_payload.json` or prompt metadata.

Strategies in scope:

- `one_shot_compact`
- `hierarchical_balanced`
- `rolling_synthesis`
- `evidence_table_then_synthesis`

`deterministic_baseline` should continue to work without planner mode selection because it does not call the model.

Suggested metric fields:

```json
{
  "strategy": "evidence_table_then_synthesis",
  "planner_mode": "full_direct_synthesis",
  "planner_modes": ["full_direct_synthesis"],
  "planner_calls": [
    {
      "call_label": "final",
      "mode": "full_direct_synthesis",
      "estimated_input_tokens": 12000,
      "estimated_output_tokens": 9500,
      "available_input_tokens": 250000,
      "available_output_tokens": 30000,
      "fallback_reason": null
    }
  ],
  "estimated_input_tokens": 12000,
  "estimated_output_tokens": 9500,
  "available_input_tokens": 250000,
  "available_output_tokens": 30000,
  "fallback_reason": null
}
```

For hierarchical and rolling strategies, `planner_calls` should contain one entry per LLM call. The top-level `planner_mode` may be the most compact mode used during the run, and `planner_modes` should list the call modes in execution order.

Suggested call labels:

- `one_shot_compact`: `final`
- `evidence_table_then_synthesis`: `final`
- `hierarchical_balanced`: `batch_1`, `batch_2`, `final`
- `rolling_synthesis`: `step_1`, `step_2`, etc.

Update GUI result display, if practical, to show:

- Selected planner mode.
- Estimated input tokens.
- Estimated output tokens.
- Fallback reason when compact mode is selected.

Update evaluator behavior:

- Continue checking provenance and orphaned ranges.
- Do not penalize compact mode for short summaries when range preservation succeeds.
- Keep warnings for malformed `source_range_keys`, but allow hit-ID recovery as already implemented.

## GUI Changes — Model Context Override

Add a `QSpinBox` for model context tokens alongside the existing `max_output_tokens` field (same settings group row). Label: "Model context". Range: 8192–524288. Default: 32768. This mirrors the production app's existing context override field and feeds `model_context_tokens` into `SynthesisBudgetRequest`.

## Guardrails

- Do not make production app changes.
- Do not add new model calls.
- Do not change saved source scan inputs.
- Do not remove existing metrics fields.
- Do not make GUI changes that block CLI/headless tests.

## Acceptance Criteria

- One-shot strategy saves planner metrics.
- Hierarchical strategy saves planner metrics for every LLM call.
- Rolling strategy saves planner metrics for every LLM call.
- Evidence-table strategy saves planner metrics.
- Prompt preview makes selected mode visible.
- GUI or result text exposes selected mode.
- Evaluator still reports orphaned/unmatched ranges.
- Compact mode with preserved ranges passes core quality checks.
- Existing strategy smoke tests still pass.
