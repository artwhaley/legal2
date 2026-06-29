# T68 - Real SQL FTS Pagination

## Goal
Replace fake in-memory FTS pagination with SQL-level merged pagination and deterministic total counts.

## Background
The current search API still materializes the full merged hit set in Python, sorts it, and slices a page afterward. That is the main large-hit bottleneck.

**Spec reference:** `05_large_dataset_performance_patch_spec.md` Section 4

## Depends On
- T67

## Scope
- Rewrite paged `search_messages` so deduplication, ordering, and page slicing occur in SQL
- Return:
  - `hits`
  - `total_count`
  - `has_more`
  - `next_offset`
- Preserve deterministic ordering across repeated identical queries
- Keep malformed-query handling safe
- Minimize Python-side hit materialization to the requested page only

## Guardrails
- Do not silently cap total accessible results
- Do not regress exact/partial/fuzzy semantics without explicit test updates
- Avoid full-hit-list Python sorting on the paged path

## Non-Goals
- Search mode UI changes
- Expanded keyword pagination

## Acceptance Criteria
- Common-token FTS searches page at SQL level
- Only current-page hits are hydrated/grouped
- `total_count` reflects the complete deduped match count
- Stable page ordering preserved

## Tests
- FTS tests for paged vs full equivalence on small fixture
- Instrumented test proving page-sized Python hit materialization on synthetic large fixture
- `python -m pytest -q`

