# T71 - Embedding Modes and Background Integration

## Goal
Separate message/chunk embedding into explicit modes and complete their integration with the background search flow.

## Background
Embedding searches should be deliberate, independent modes with honest top-K presentation and safe background execution.

**Spec reference:** `05_large_dataset_performance_patch_spec.md` Section 6

## Depends On
- T67
- T69

## Scope
- Wire `Message embedding` mode to message-vector search only
- Wire `Chunk embedding` mode to chunk-vector search only
- Keep embedding execution on the safe background path already used for embedding jobs
- Integrate results with the common search result rendering/status/cancel contract
- Show top-K messaging instead of FTS-style total-count pagination

## Guardrails
- Do not run FTS first when an embedding mode is selected
- Do not mix message and chunk vectors in one mode
- Respect current embedding index readiness errors

## Non-Goals
- Embedding index build changes
- Vector pagination beyond top-K

## Acceptance Criteria
- Each embedding mode runs only its own vector search
- Results render through the background search UI without freezing
- Status/cancel flow behaves consistently with other modes

## Tests
- Search worker / UI smoke tests for both embedding modes
- Existing embedding search tests updated as needed
- `python -m pytest -q`

