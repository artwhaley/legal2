# T70 - Expanded Keyword Mode Pagination

## Goal
Make expanded keyword search a standalone paged mode with deduped complete results.

## Background
Keyword expansion is currently additive and can hydrate unbounded chip matches. On large datasets it needs its own bounded, paged retrieval flow.

**Spec reference:** `05_large_dataset_performance_patch_spec.md` Section 5

## Depends On
- T68
- T69

## Scope
- Treat keyword expansion as a full search mode, not a supplement to FTS
- Cache expansion terms for the current query
- Allow manual chip add/remove followed by explicit rerun
- Implement deduped paged keyword results across chips
- Return true total count over the deduped keyword result set

## Guardrails
- Do not run base FTS or embedding search from expanded keyword mode
- Do not silently drop chip matches
- Keep LLM expansion failure messaging clear and non-fatal

## Non-Goals
- Hybrid search fusion
- Embedding search changes

## Acceptance Criteria
- Expanded keyword mode pages across deduped chip results
- High-frequency chip queries remain responsive
- Manual chip edits remain usable with explicit rerun

## Tests
- Keyword expansion tests for paged deduped results
- UI smoke/regression for chip edit + rerun flow
- `python -m pytest -q`

