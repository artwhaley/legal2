# T79 - Hit Message And Highlight Editing

## Goal
Implement the remaining editable evidence controls on the new widget: one hit message per block and toggleable message highlights.

## Background
The transcript text itself is read-only, but the user still needs to shape evidence blocks by choosing the core hit message and marking highlighted messages. This is the last behavioral parity gap before the new widget can be considered feature-complete for demonstration.

**Spec reference:** `06_new_transcript_widget_spec.md` sections `Hit And Highlight Controls`, `Current Behavior To Preserve`

## Depends On
- T78

## Scope
- Add visible hit/highlight controls for relevant-range messages on the active block
- Implement hit-message selection with exactly-one-hit behavior
- Implement highlight toggle behavior with persisted message ID sets
- Persist through:
  - `evidence_blocks.update_evidence_block_anchor`
  - `evidence_blocks.set_evidence_block_highlights`
- Refresh rendered annotation state after edits

## Guardrails
- Do not allow multiple hit messages per evidence block
- Keep controls visually secondary to the transcript body
- Avoid UI affordances that imply the text itself is editable

## Non-Goals
- Search-page integration
- Replacing the old transcript tab

## Acceptance Criteria
- User can change the hit message for the active block
- User can toggle highlighted messages for the active block
- Persist/reload round-trips both hit message and highlights
- Rendered document updates immediately after edits

## Tests
- Add hit/highlight persistence tests
- Add one UI smoke path for control interaction if practical
- `python -m pytest tests/test_new_transcript_widget.py tests/test_ui_smoke.py -q`
