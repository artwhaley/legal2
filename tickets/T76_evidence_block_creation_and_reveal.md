# T76 - Evidence Block Creation And Reveal

## Goal
Add evidence block creation and reveal flows to the new widget so the demonstrator can exercise real DB-backed transcript workflows.

## Background
The old transcript wrapper already defines the behavioral contract: create from viewport center, create for a specific message, reveal an existing block, and select a block by ID. The new widget should match that contract before annotation editing starts.

**Spec reference:** `06_new_transcript_widget_spec.md` sections `Current Behavior To Preserve`, `Public API Required For Future Integration`

## Depends On
- T75

## Scope
- Implement:
  - `create_evidence_block_from_viewport_center(...)`
  - `create_evidence_block_for_message(...)`
  - `reveal_created_evidence_block(...)`
  - `select_evidence_block(...)`
- Reuse existing `db.evidence_blocks` creation APIs
- Resolve hit message from document position/metadata maps
- Load and track thread evidence blocks inside the new widget
- Add demo button:
  - `New evidence block`
  - `Jump random + create block`

## Guardrails
- New block creation must use existing default slot logic
- Reveal/select must load the correct source thread before scrolling when necessary
- Do not duplicate or fork evidence-block persistence logic

## Non-Goals
- Boundary dragging
- Hit/highlight editing controls
- Search/conversational integration

## Acceptance Criteria
- Creating from viewport center writes a valid block to DB
- Creating for a known message writes expected `core_hit_message_id`
- Revealing/selecting a block scrolls to its hit message
- Random jump + create block leaves a visible active block in the new widget

## Tests
- Add creation/reveal tests against a real test DB
- Extend UI smoke coverage for demo button flows
- `python -m pytest tests/test_new_transcript_widget.py tests/test_ui_smoke.py -q`
