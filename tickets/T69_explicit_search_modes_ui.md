# T69 - Explicit Search Modes UI

## Goal
Replace additive search toggles with one explicit search mode and make search run only on Enter or Search button.

## Background
The current Simple Search UI can trigger FTS, keyword expansion, and both embedding searches for one query. Large datasets need one deliberate retrieval mode at a time.

**Spec reference:** `05_large_dataset_performance_patch_spec.md` Sections 1, 2

## Depends On
- T67
- T68

## Scope
- Replace:
  - keyword toggle
  - message embedding toggle
  - chunk embedding toggle
  with one exclusive mode control
- Search modes:
  - `FTS5`
  - `Expanded keyword`
  - `Message embedding`
  - `Chunk embedding`
- Remove text-change-triggered search behavior
- Add Search button if not already present
- Show mode-specific controls only when relevant:
  - embedding selectivity only for embedding modes
  - chip controls only for expanded keyword mode
  - page controls only for complete-result modes

## Guardrails
- One search action may invoke exactly one retrieval mode
- Do not remove honest labeling for top-K embedding results
- Keep transcript/result navigation intact

## Non-Goals
- Expanded keyword mode backend pagination
- Embedding worker internals

## Acceptance Criteria
- Typing does not search
- Enter/Search runs exactly one selected mode
- UI reflects mode-specific controls cleanly

## Tests
- Simple Search UI smoke updates for explicit mode selection and enter-to-search behavior
- `python -m pytest -q`

