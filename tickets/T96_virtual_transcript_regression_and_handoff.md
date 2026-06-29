# T96 - Virtual Transcript Regression And Handoff

## Goal
Close the virtual transcript stack with regression coverage, documentation, and a replacement-readiness handoff.

## Background
This stack should end with a clear decision point: either the virtual widget is ready to replace Gen 1 in workflows, or the remaining blockers are explicitly documented.

**Spec reference:** `08_virtual_transcript_widget_spec.md` section `Acceptance Criteria`

## Depends On
- T95

## Scope
- Add/expand regression tests for the full virtual widget stack
- Add manual smoke checklist updates
- Document any known limitations
- Document replacement plan for later search/conversational integration
- Run targeted tests
- Run relevant UI smoke tests

## Guardrails
- Do not remove old widgets in this ticket
- Do not integrate search/conversational pages in this ticket
- Do not claim readiness unless evidence editing and deep scrolling both work

## Acceptance Criteria
- Tests cover bounded loading, scrolling, jumping, evidence creation, annotation painting, editing, persistence, and reload
- Manual smoke checklist includes 15k-message testing steps
- Known limitations are updated honestly
- Handoff states whether the virtual widget is ready for workflow integration

## Tests
- `python -m pytest tests/test_virtual_transcript_height_index.py tests/test_virtual_transcript_model.py tests/test_virtual_transcript_widget.py -q`
- `python -m pytest tests/test_ui_smoke.py -q`
- Any existing transcript/evidence tests affected by shared helpers

