# T105 - Search Date Range Regression

## Goal

Run the full regression pass for the date range stack and close the feature in a stress-test-ready state.

## Dependencies

T99, T100, T101, T102, T103, T104.

## Implementation Notes

This is the hardening and verification ticket. Do not add new behavior here unless a regression fix is required.

Focus on:

- full-stack correctness across simple and conversational search
- log visibility
- empty-range behavior
- scoped count correctness
- scoped answer-mode correctness
- context expansion behavior remaining normal

If a shared helper is still duplicated in multiple search paths, consolidate it here only if that consolidation reduces risk and does not broaden behavior.

## Files / Areas Likely Touched

- test files across search and conversational areas
- docs if a short limitation or behavior note is warranted

## Acceptance Criteria

- The date range stack passes focused backend and UI regression tests.
- Simple search and conversational search both behave correctly with:
  - no scope
  - start-only scope
  - end-only scope
  - bounded scope
  - empty-result scope
- Embedding search remains scoped before final top-K.
- Conversational mode selection remains based on scoped stats.
- Evidence review context still may include nearby out-of-range messages.
- Logs make the active date scope visible at major search boundaries.

## Tests / Verification

- Run at minimum:
  - `python -m pytest tests/test_dataset_budget.py tests/test_transcript.py tests/test_fts.py tests/test_search_worker.py tests/test_embedding_search_fusion.py tests/test_window_planner.py tests/test_conversational_answer.py tests/test_ui_smoke.py -q`
- Run broader suite if targeted tests expose shared regressions.

## Non-Goals

- No new features beyond regression fixes.
