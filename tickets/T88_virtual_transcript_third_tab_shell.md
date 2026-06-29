# T88 - Virtual Transcript Third Tab Shell

## Goal
Add a third tab named `Virtual Transcript Widget` beside the existing transcript tabs without changing existing workflows.

## Background
The virtual widget must be developed nondestructively. The existing Gen 1 tab remains the behavior reference, and the Gen 2 tab remains available for comparison.

**Spec reference:** `08_virtual_transcript_widget_spec.md` sections `Demo Tab`, `Guardrails`

## Depends On
- None

## Scope
- Add `message_evidence_workstation/ui/virtual_transcript_widget_tab.py`
- Add a skeletal `VirtualTranscriptWidget` class if needed
- Add `Virtual Transcript Widget` to `MainWindow`
- Wire dataset activation into the new tab
- Add a source-thread selector shell
- Add a basic status label

## Guardrails
- Do not remove or rename existing transcript tabs
- Do not route search/conversational actions to the new tab
- Keep this ticket limited to shell wiring

## Non-Goals
- Virtual rendering
- Evidence editing
- Boundary dragging
- Search integration

## Acceptance Criteria
- App shows three transcript tabs:
  - `Transcript Widget`
  - `New Transcript Widget`
  - `Virtual Transcript Widget`
- Dataset activation reaches the virtual tab
- The virtual tab can list source threads for the active dataset
- Existing transcript tabs still work as before

## Tests
- Add/extend a UI smoke test that asserts all three tab labels exist
- Add/extend a dataset activation test for the virtual tab shell
- `python -m pytest tests/test_ui_smoke.py -q`

