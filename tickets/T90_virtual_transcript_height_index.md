# T90 - Virtual Transcript Height Index

## Goal
Add a virtual height index that maps between scroll pixels and message ordinals without measuring every message.

## Background
Variable-height messages make transcript virtualization harder than fixed rows. The height index is the core scale primitive.

**Spec reference:** `08_virtual_transcript_widget_spec.md` section `Height Index`

## Depends On
- T89

## Scope
- Add `message_evidence_workstation/ui/virtual_transcript_height_index.py`
- Implement default estimated height initialization
- Implement measured height updates
- Implement total virtual document height
- Implement ordinal-to-offset lookup
- Implement offset-to-ordinal lookup
- Use a Fenwick tree, segment tree, or equivalent prefix-sum structure
- Support height cache invalidation for width/style changes

## Guardrails
- No recursive reflow
- No full-document measurement during scroll
- Do not assume fixed-height rows

## Non-Goals
- Painting actual messages
- SQL fetching
- Evidence annotations

## Acceptance Criteria
- Prefix sums remain correct after measured height updates
- Offset-to-ordinal lookup is logarithmic or otherwise bounded
- Total height updates when measured heights change
- Width/style invalidation resets measured heights safely

## Tests
- Add `tests/test_virtual_transcript_height_index.py`
- Cover total height, updates, offset lookup, ordinal lookup, clamping, and invalidation

