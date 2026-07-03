# T102 - Conversational Whole Transcript Date Scope

## Goal

Make conversational answer-mode selection and whole-transcript answering operate on the selected date scope instead of the full dataset.

## Dependencies

T99.

## Implementation Notes

This ticket handles the part that most directly affects correctness before stress testing: scoped budgeting and scoped whole-transcript analysis.

Wire date scope through:

- conversational submit path
- scoped dataset budget stats
- answer budget resolution inputs
- whole transcript construction
- whole transcript result validation

Decisions:

- Date trimming happens before answer-mode selection.
- Whole transcript payload contains only scoped messages and scoped message IDs.
- Out-of-scope citations are invalid and must be rejected.
- If scoped message count is zero, fail visibly before any model call.

Keep the implementation linear:

1. capture scope
2. compute scoped stats
3. resolve budget
4. choose mode
5. run whole transcript if selected

## Files / Areas Likely Touched

- `message_evidence_workstation/ui/conversational_tab.py`
- `message_evidence_workstation/search/conversational_answer.py`
- `tests/test_conversational_answer.py`

## Acceptance Criteria

- Conversational mode selection is computed from scoped dataset stats.
- Whole transcript mode serializes only scoped messages.
- Whole transcript payload sent to the model contains only scoped message IDs.
- Whole transcript parser rejects out-of-scope citations.
- Zero-message scoped queries fail visibly before any model call.
- Logging records the active scope and scoped counts during mode resolution.

## Tests / Verification

- Add tests for:
  - scoped mode selection
  - scoped transcript serialization
  - scoped whole-transcript model payload
  - out-of-scope citation rejection
  - zero-message scope short-circuit
- Run:
  - `python -m pytest tests/test_conversational_answer.py -q`

## Non-Goals

- No exhaustive window planning changes yet.
- No conversational UI date controls yet beyond any minimal plumbing required by tests.
