# T77 - Document Annotation Overlays

## Goal
Render evidence ranges and message states on top of the document so the transcript reads like annotated transcript text instead of plain text with no evidence context.

## Background
The user-facing requirement is document first. Context ranges, relevant passages, hit message, and highlights must appear as document markup, not as a row-grid substitute.

**Spec reference:** `06_new_transcript_widget_spec.md` sections `Annotation Model`, `Visual Formatting`

## Depends On
- T76

## Scope
- Add internal overlay state for loaded evidence blocks
- Render:
  - context regions
  - relevant regions
  - active block distinction
  - hit/core message visual state
  - highlighted message visual state
- Prefer document-native formatting tools where possible:
  - `QTextCharFormat`
  - `ExtraSelection`
  - lightweight overlay painting for margin controls
- Keep transcript body visually document-like while exposing evidence structure clearly

## Guardrails
- Do not regress to dominant row separators or table layout
- Do not make highlighted or relevant states dependent on reparsing document text
- Keep overlay state separate from underlying transcript text

## Non-Goals
- Draggable boundary handles
- Editing hit/highlight via UI controls

## Acceptance Criteria
- Existing evidence blocks visibly mark context, relevant region, hit message, and highlights
- Active block is visually distinguishable
- Annotation rendering survives thread reload
- Transcript still feels like one continuous document

## Tests
- Add rendering-state tests that verify overlay state after thread load
- Add at least one smoke assertion for active block annotation behavior
- `python -m pytest tests/test_new_transcript_widget.py -q`
