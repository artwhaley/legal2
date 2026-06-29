# T78 - Boundary Drag And Overlay Persistence

## Goal
Implement draggable context/relevant boundaries on the new document widget and persist those edits safely to the existing evidence block schema.

## Background
The evidence contract uses four slot boundaries around ordered messages. The new widget must preserve that model while mapping slots to document positions instead of painted rows.

**Spec reference:** `06_new_transcript_widget_spec.md` sections `Boundary Rendering`, `Current Behavior To Preserve`

## Depends On
- T77

## Scope
- Add boundary handle rendering in a margin or overlay lane
- Map document y-position to nearest message ordinal / slot
- Add drag interaction for:
  - context start
  - relevant start
  - relevant end
  - context end
- Reuse or extract shared invariant-clamping logic for legal boundary moves
- Persist edited slots through `evidence_blocks.update_evidence_block_slots`
- Implement `persist_all_overlays()` and tab-level `Persist / reload current thread`

## Guardrails
- Persist on release or explicit reload, not on every mouse move
- Enforce slot invariants before any DB write
- Keep the old widget untouched except for safe shared-helper extraction if clearly justified

## Non-Goals
- Search integration
- New evidence schema

## Acceptance Criteria
- Each of the four boundaries can be moved through the new widget
- Illegal drag targets clamp to the nearest valid slot arrangement
- Persist/reload round-trips boundary edits exactly
- Reloading the thread shows the same boundaries from DB

## Tests
- Add boundary persistence and reload tests
- Add at least one drag or boundary-move smoke path
- `python -m pytest tests/test_new_transcript_widget.py tests/test_ui_smoke.py -q`
