# T80 - New Transcript Widget Regression

## Goal
Close the new transcript widget stack with regression coverage, scale-oriented validation, and final documentation updates.

## Background
Tickets T73-T79 establish the new demonstrator architecture. This ticket verifies that the parallel tab is stable, the old tab still exists, and the new widget is ready for later integration into search and conversational workflows.

**Spec reference:** `06_new_transcript_widget_spec.md` sections `Acceptance Criteria`, `Tests`, `Handoff Notes`

## Depends On
- T73 through T79

## Scope
- Finalize `tests/test_new_transcript_widget.py`
- Extend smoke coverage for:
  - both transcript tabs present
  - deep jump behavior
  - create/reveal flows
  - boundary persist/reload
  - hit/highlight persist/reload
- Add or extend a scale-marked validation for large single-thread load if needed
- Update docs as needed to note:
  - old and new transcript tabs coexist
  - new widget is the document-backed demonstrator
  - search/conversational integration is intentionally deferred
- Run the fast suite and document any honest remaining limitations

## Guardrails
- No search/conversational integration in this ticket
- No removal of the old widget in this ticket
- Keep regressions focused on the approved demonstrator scope

## Non-Goals
- Broader transcript redesign beyond the approved stack
- Flutter/client-server migration work

## Acceptance Criteria
- Fast relevant test suite passes
- New transcript widget behavior is covered by dedicated tests
- Docs reflect the parallel demonstrator status honestly
- Any remaining limitations are documented clearly for the next executor

## Tests
- `python -m pytest tests/test_new_transcript_widget.py tests/test_ui_smoke.py -q`
- `python -m pytest -q` before closing the ticket
