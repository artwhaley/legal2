# WML03 - Prompt And Strategy Core

## Goal
Build the non-GUI merge strategy harness and prompt builders.

## Depends On
- WML02

## Scope
- Implement `prompts.py`.
- Implement `strategies.py`.
- Implement `merge_lab.py` CLI wrapper.
- Strategies:
  - `one_shot_compact`
  - `hierarchical_balanced`
  - `rolling_synthesis`
  - `evidence_table_then_synthesis`
  - `deterministic_baseline`
- Support dry-run mode that writes prompt/payload without API calls.
- Support optional model call mode through existing non-UI model helpers.
- Every strategy writes standard output files:
  - `prompt_payload.json`
  - `prompt_preview.md`
  - `result_raw.txt`
  - `result_parsed.json`
  - `result_readable.md`
  - `metrics.json`

## Guardrails
- Do not implement unbounded recursive merge.
- `hierarchical_balanced` must be bounded: windows 1-3, windows 4-6, final merge.
- `deterministic_baseline` is only a control/evaluation artifact.
- Do not rerun scan calls.

## Acceptance Criteria
- CLI can run each strategy in `--dry-run`.
- Dry-run outputs include prompt/payload and metrics.
- Strategy call counts are known before execution.
- No production app behavior changes.

