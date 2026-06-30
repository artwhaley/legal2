# WML08 - Synthesis Budget Planner Orchestrator

## Goal
Implement a synthesis budget planner for the window merge lab that chooses between rich direct synthesis and preservation-first compact direct synthesis for every LLM-backed merge strategy.

This stack is intentionally scoped to the spike under `spikes/window_merge_lab/`. It should prove the strategy and prompt behavior before any production integration.

The planner must apply to:

- `one_shot_compact`
- `hierarchical_balanced`
- `rolling_synthesis`
- `evidence_table_then_synthesis`

`deterministic_baseline` has no LLM prompt and does not need budget-mode prompt selection.

## Depends On
- WML07

## Execution Order

Run these tickets sequentially:

| Order | Ticket | Summary |
|------:|--------|---------|
| 1 | [WML09](WML09_budget_plan_model_and_estimator.md) | Add planner data structures, token estimates, and mode-selection logic |
| 2 | [WML10](WML10_full_direct_synthesis_mode.md) | Implement Mode 1: full direct synthesis prompt profile |
| 3 | [WML11](WML11_compact_direct_synthesis_mode.md) | Implement Mode 2: compact direct synthesis prompt profile |
| 4 | [WML12](WML12_strategy_gui_and_evaluator_integration.md) | Wire planner into strategy execution, GUI visibility, metrics, and evaluator behavior |
| 5 | [WML13](WML13_budget_planner_tests_and_handoff.md) | Add regression tests, docs, and handoff notes |

## Strategic Principle

The synthesis planner is not allowed to drop ranges to fit a budget.

If rich synthesis is too expensive, degrade richness:

1. Shorter narrative.
2. Shorter per-range summaries.
3. Minimal display text.
4. Compact range inventory.

Do not add a refusal mode here. If a search is too broad, that should be caught before the expensive windowed search starts. For this spike stack, assume compact direct synthesis is sufficient for every result set the front end allows through.

Budget planning is per LLM call, not just per strategy run. Hierarchical and rolling strategies may make multiple calls, and each call should receive an explicit Mode 1 or Mode 2 prompt profile based on the records being sent into that call and the expected output size for that call.

## Supported Modes

### Mode 1 - Full Direct Synthesis

Use when estimated input and output fit comfortably.

- Use all compact evidence records.
- Produce a cohesive narrative answer.
- Preserve every source range.
- Allow only light merging when ranges clearly refer to the same conversation event.
- Include useful range summaries and display text.
- Use content-bearing range titles, not date-only metadata labels.

### Mode 2 - Compact Direct Synthesis

Use when Mode 1 is risky.

- Preserve every source range.
- Prioritize navigation correctness over rich prose.
- Keep the answer narrative short.
- Keep range titles content-bearing.
- Use minimal per-range summaries and display text.
- Avoid aggressive merging.
- Copy `source_range_key` values exactly.

## Explicitly Out Of Scope

- Production app behavior changes.
- Search-breadth gating before windowed search.
- Recursive/windowed synthesis of synthesis outputs.
- Refusal or "narrow your search" behavior inside synthesis.
- Dropping, sampling, or top-k clipping ranges as a synthesis-budget strategy.

## Guardrails

- Stay under `spikes/window_merge_lab/` unless a test import requires existing app helpers.
- Do not modify production app behavior.
- Do not modify database schema.
- Do not rerun expensive scan-window calls.
- Write generated outputs only under `spikes/window_merge_lab/outputs/`.
- Keep prompt behavior auditable through `prompt_payload.json` and `prompt_preview.md`.

## Acceptance Bar

The stack is complete when:

- A budget planner deterministically chooses Mode 1 or Mode 2.
- Mode 1 is selected when rich input and rich output estimates fit.
- Mode 2 is selected when Mode 1 output is too large or too close to the output budget.
- Mode 2 does not drop ranges.
- One-shot, hierarchical, rolling, and evidence-table prompts all support the selected planner profile.
- All LLM-backed prompts include stable provenance plus compact analysis context whenever they are carrying evidence ranges.
- GUI and metrics show which planner mode was selected and why.
- Evaluator treats compact mode as valid when all ranges are preserved.
- Smoke tests cover mode selection, prompt profile differences, and provenance preservation.
