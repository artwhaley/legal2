# T94 - Virtual Transcript Annotation Editing

## Goal
Implement evidence boundary dragging, hit selection, highlighting, and persistence in the virtual widget.

## Background
The virtual widget must preserve Gen 1 evidence editing behavior exactly enough to become the replacement path.

**Spec reference:** `08_virtual_transcript_widget_spec.md` sections `Product Requirements`, `Persistence Requirements`

## Depends On
- T93

## Scope
- Implement boundary hit-testing
- Implement drag preview for all four boundaries
- Snap boundary drags to message slots
- Enforce valid slot ordering through existing slot helpers
- Persist boundary changes on release
- Implement hit-message selection within relevant range
- Ensure only one hit message per evidence block
- Implement message highlight toggle
- Persist highlights
- Implement reload/restore of active evidence state

## Guardrails
- Use existing `db.evidence_blocks` APIs when possible
- Preserve slot semantics
- Do not write pixel positions to the database
- Do not allow invalid boundary ordering
- Do not let hit message drift outside relevant range without a deliberate rule

## Non-Goals
- Search/conversational integration
- Multi-block editing UX beyond active block behavior

## Acceptance Criteria
- Dragging each boundary updates shading live
- Releasing a boundary persists the slot change
- Reload restores moved boundaries
- Selecting a new hit persists and remains unique
- Toggling highlights persists and reloads
- Creating an evidence block near a deep ordinal remains bounded

## Tests
- Cover boundary move validation and persistence
- Cover hit selection uniqueness
- Cover highlight toggle persistence
- Cover reload restores all edited evidence state
- Add a deep evidence block test near ordinal 14,000

