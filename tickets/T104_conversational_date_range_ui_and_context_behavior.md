# T104 - Conversational Date Range UI And Context Behavior

## Goal

Finish the conversational date range feature at the UI layer and lock in the explicit context-expansion behavior.

## Dependencies

T102, T103.

## Implementation Notes

Add start/end date controls to the conversational tab and ensure the selected scope is captured once per submission and passed immutably into the worker path.

Make user-visible behavior explicit:

- mode resolution status reflects scoped analysis
- answering status reflects scoped transcript or scoped exhaustive scan
- zero-result scoped failures are clear

Decisions:

- Context expansion remains normal outside the selected date range.
- The date range limits retrieval and analysis, not evidence review context.
- Submit-time scope snapshot is authoritative for the in-flight request.

If needed, add a concise status message or system message noting that opened evidence may show nearby out-of-range context.

## Files / Areas Likely Touched

- `message_evidence_workstation/ui/conversational_tab.py`
- `tests/test_ui_smoke.py`
- `tests/test_conversational_answer.py`

## Acceptance Criteria

- Conversational tab exposes explicit start/end date controls.
- Submitted conversational searches pass a stable date scope into the worker.
- Status and logging make the scoped analysis visible.
- Opened evidence/results can still show neighboring out-of-range context.
- No later UI change mutates the scope of a running answer request.

## Tests / Verification

- Add tests for:
  - submit-time scope capture
  - scoped status behavior
  - context expansion still reaching neighboring out-of-range messages where applicable
- Run:
  - `python -m pytest tests/test_ui_smoke.py tests/test_conversational_answer.py -q`

## Non-Goals

- No simple search work.
- No new filtering modes beyond explicit date range.
