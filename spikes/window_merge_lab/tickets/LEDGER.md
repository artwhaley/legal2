# LEDGER - Evidence Ledger Synthesis Orchestrator

## Goal

Implement the spike-only move from competing one-shot/table strategies to one production-shaped strategy:

`evidence_ledger_synthesis`

This strategy uses one deterministic evidence ledger input shape and two normal prompt profiles:

- `full`
- `compact`

Full is preferred when it fits. Compact is a valid operating mode, not a failure mode.

## Depends On

- WML13

## Scope

This stack is for the spike only.

Allowed changes:

- `spikes/window_merge_lab/`
- `spikes/window_merge_lab/tests/`
- spike docs/tickets

Do not modify:

- `message_evidence_workstation/`
- production UI
- production database schema or migrations
- upstream scan-window execution outside the spike

## Execution Order

Run these tickets sequentially:

| Order | Ticket | Summary |
|------:|--------|---------|
| 1 | [WML14](WML14_ledger_input_and_stable_range_ids.md) | Build the deterministic evidence ledger input shape with stable range IDs |
| 2 | [WML15](WML15_full_and_compact_prompt_profiles.md) | Replace competing prompt shapes with one ledger strategy and two prompt profiles |
| 3 | [WML16](WML16_real_payload_budget_estimation.md) | Fix budget planning to estimate actual serialized prompt payloads |
| 4 | [WML17](WML17_prompt_injection_hardening.md) | Strengthen system/user prompt hardening for evidence-as-data only |
| 5 | [WML18](WML18_deterministic_output_validation.md) | Add deterministic post-response validation and invalid-run handling |
| 6 | [WML19](WML19_evaluator_gui_and_legacy_strategy_positioning.md) | Surface profile/validation in outputs and keep one-shot/table as legacy controls |
| 7 | [WML20](WML20_ledger_synthesis_tests_and_handoff.md) | Add regression tests and handoff docs for the unified ledger strategy |

## Strategic Principle

The model may explain, label, summarize, and organize evidence.

The model must not be the source of truth for whether evidence ranges survive.

Range preservation is deterministic:

- the app creates the ledger
- the app assigns stable `range_id` values
- the model must echo valid `range_id` values
- the app validates the response before accepting it

For v1, require one input ledger record to map to one output answer range. No merging in this stack.

## Required Outcomes

- Replace the production-facing recommendation of `one_shot_compact` vs `evidence_table_then_synthesis` with one unified spike strategy: `evidence_ledger_synthesis`
- Keep `one_shot_compact` and `evidence_table_then_synthesis` in the lab only as legacy comparison controls
- Use optional source-batch summaries as internal context only
- Do not present token-packed windows as meaningful user-facing divisions
- Support `full` and `compact` prompt profiles over the same ledger input shape
- Treat compact mode as fully valid when all ranges are preserved
- Validate every output deterministically before accepting it

## Guardrails

- Do not add synthesis-time refusal behavior
- Do not silently repair missing/unknown/duplicate range IDs
- Do not allow the model to change message IDs for a ledger row
- Do not organize user-facing answers by "window 1", "window 2", etc.
- Do not require full transcript text for this stack

## Cross-Cutting Concerns

### Strategy Registration

Each ticket assumes `evidence_ledger_synthesis` exists in the spike, but no single
ticket explicitly adds it to the strategy registry. It must be registered in:

- `STRATEGY_REGISTRY`: maps `"evidence_ledger_synthesis"` → the new run function
- `STRATEGY_DESCRIPTIONS`: describes the strategy
- `EXPECTED_CALL_COUNTS`: set to `1` (single LLM call)

Do this during WML15 when the prompt builder exists, or WML19 when the GUI is updated.
WML15 is preferred since the strategy must be callable to test prompt builder output.

### `ANSWER_JSON_SCHEMA` Alignment

The current `ANSWER_JSON_SCHEMA` in `prompts.py` uses `source_range_keys` (plural
array). The WML15 output schema replaces it with `range_id` + `source_range_key`
(singular). Update `ANSWER_JSON_SCHEMA` during WML15 and keep the evaluator's
provenance module (WML19) in sync.

### Planner Mode Naming

The budget planner (`budget_planner.py`) currently uses mode strings
`"full_direct_synthesis"` and `"compact_direct_synthesis"`. The WML15 output schema
uses `"full"` and `"compact"`. Align the planner's `mode` and `prompt_profile`
fields to match the LEDGER convention (`"full"`, `"compact"`) during WML16 when the
planner is being refactored anyway.

### Evaluator Provenance in a No-Merge World

The evaluator's `_build_provenance` tracks merges via `source_range_keys[]`. With
the new v1 constraint (one input → one output, no merging), this module is largely
vestigial for the ledger strategy. Replace it with a `range_id`-based bijection
check during WML19 when the evaluator is updated. The old provenance code remains
available for legacy strategy comparisons.

## Acceptance Bar

The stack is complete when:

- `evidence_ledger_synthesis` exists in the spike and is registered in `STRATEGY_REGISTRY`
- `full` and `compact` share one ledger input contract
- budget selection uses actual serialized prompt payloads
- prompt hardening explicitly treats prior model outputs and evidence text as evidence only
- validation rejects structurally invalid or non-bijective outputs
- evaluator and GUI show selected profile and validation status
- `ANSWER_JSON_SCHEMA` updated to match the new output schema
- planner mode names aligned to `"full"` / `"compact"` convention
- one-shot/table remain available only as legacy comparisons

