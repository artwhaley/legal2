# T103 - Exhaustive Scan Date Scope

## Goal

Make exhaustive conversational scan fully honor the selected date range during window planning and retrieval-hint generation.

## Dependencies

T99, T101, T102.

## Implementation Notes

This ticket completes the scoped conversational backend for the exhaustive path.

Wire date scope through:

- `run_exhaustive_window_scan_answer`
- `build_token_bounded_windows_for_dataset`
- window-planning message iteration
- chars/token ratio calculation
- `collect_exhaustive_window_hints`
- FTS hint retrieval
- embedding hint retrieval
- scoped thread message ordering for hint block assignment

Decisions:

- Scoped window planning only iterates in-range messages.
- Scoped chars/token calculation is based on the scoped transcript, not the full dataset.
- Retrieval hints must come from the same scoped message universe as the exhaustive scan.
- If scope produces no windows, fail visibly before any model call.

Do not reintroduce retrieval-prefiltered exhaustive scan behavior. Hints remain hints, not gates.

## Files / Areas Likely Touched

- `message_evidence_workstation/search/conversational_answer.py`
- `message_evidence_workstation/search/window_planner.py`
- `message_evidence_workstation/search/exhaustive_hints.py`
- `tests/test_window_planner.py`
- `tests/test_conversational_answer.py`
- `tests/test_exhaustive_hints.py` if present, otherwise relevant existing conversational tests

## Acceptance Criteria

- Exhaustive scan budget uses scoped dataset stats.
- Planned windows contain only scoped messages.
- Window planner derives chars/token ratio from the scoped transcript.
- Retrieval hints are gathered only from scoped FTS and scoped embeddings.
- Hint block assignment uses scoped thread message order.
- If no scoped windows exist, the flow fails visibly before any model call.

## Tests / Verification

- Add tests for:
  - scoped planned windows
  - scoped chars/token calculation
  - scoped FTS hints
  - scoped embedding hints
  - no-window scoped failure
- Run:
  - `python -m pytest tests/test_window_planner.py tests/test_conversational_answer.py tests/test_exhaustive_hints.py -q`

## Non-Goals

- No UI polish work.
- No changes to evidence-block context expansion behavior.
