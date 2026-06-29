# T73 - Parallel New Transcript Tab Shell

## Goal
Add a new `New Transcript Widget` tab beside the old `Transcript Widget` tab and wire dataset activation into it without changing search or conversational behavior.

## Background
The new transcript architecture must be developed nondestructively. The old transcript tab stays live while the new document-backed widget is built in parallel.

**Spec reference:** `06_new_transcript_widget_spec.md` sections `Main Window Integration`, `Demo Tab Controls`

## Depends On
- None

## Scope
- Add `message_evidence_workstation/ui/new_transcript_widget_tab.py`
- Add a placeholder or skeletal `NewTranscriptWidget` owner widget if needed for compilation
- Add `New Transcript Widget` tab in `MainWindow` next to the old transcript tab
- Wire dataset activation so both transcript tabs receive `set_dataset(dataset_id)`
- Add source-thread combo and status label shell on the new tab
- Keep sidebar selection behavior unchanged unless selecting the same source thread in both transcript tabs is trivial and low risk

## Guardrails
- Do not route any existing search or conversational action to the new tab
- Do not remove or rename the old transcript tab
- Keep this ticket limited to shell wiring and tab availability

## Non-Goals
- Document rendering
- Evidence block creation/editing
- Boundary dragging
- Search integration

## Acceptance Criteria
- App shows both transcript tabs
- Dataset load/activation enables both tabs
- New tab can populate its thread combo from the active dataset
- Existing transcript tab behavior is unchanged

## Tests
- Add/extend a UI smoke test that asserts both tab labels exist
- Add/extend a test that dataset activation calls into the new transcript tab cleanly
- `python -m pytest tests/test_ui_smoke.py -q`
