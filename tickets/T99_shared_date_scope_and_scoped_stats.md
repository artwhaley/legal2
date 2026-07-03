# T99 - Shared Date Scope And Scoped Stats

## Goal

Create the single shared date-scope contract and wire it into the foundational SQL-backed search helpers so every later ticket builds on one explicit implementation.

## Dependencies

None.

## Implementation Notes

Create a shared value object for message date scoping and a small SQL helper for applying inclusive timestamp bounds.

This ticket owns the foundation for:

- open-ended start/end bounds
- inclusive timestamp filtering
- scoped dataset budget stats
- scoped transcript loading

Implement this once and reuse it everywhere else in the stack.

Decisions:

- Bounds are inclusive.
- Empty scope is valid and means unfiltered behavior.
- Scope is evaluated against `message.timestamp`.
- Scoped transcript loading returns only in-range messages.

## Files / Areas Likely Touched

- `message_evidence_workstation/search/date_scope.py` (new)
- `message_evidence_workstation/search/dataset_budget.py`
- `message_evidence_workstation/search/transcript.py`
- `message_evidence_workstation/search/conversational_answer.py`
- `tests/test_dataset_budget.py`
- `tests/test_conversational_answer.py`
- `tests/test_transcript.py`

## Acceptance Criteria

- A shared `MessageDateScope` type exists and clearly represents optional inclusive start/end bounds.
- Search code can ask whether a scope is active without reimplementing that logic.
- Dataset budget stats can be computed for full-dataset and scoped-dataset cases through the same contract.
- Scoped budget stats correctly reflect:
  - `message_count`
  - `thread_count`
  - `total_body_chars`
  - `total_body_normalized_chars`
  - `largest_thread_message_count`
- Dataset transcript loading can return only messages inside the selected date scope.
- No caller has to manually build ad hoc date SQL strings after this ticket.

## Tests / Verification

- Add tests for:
  - no scope
  - start-only scope
  - end-only scope
  - inclusive bounded scope
  - empty-result scope
- Run:
  - `python -m pytest tests/test_dataset_budget.py tests/test_conversational_answer.py tests/test_transcript.py -q`

## Non-Goals

- No UI changes yet.
- No FTS or embedding search changes yet.
- No exhaustive scan changes yet.
