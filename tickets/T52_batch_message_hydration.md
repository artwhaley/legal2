# T52 - Batch Message Hydration Repository

## Goal
Add batch message fetch by ID and use it to eliminate N+1 per-hit queries in search paths.

## Background
FTS and embedding search hydrate hits with one `SELECT` per message. Pagination (T53) needs batch fetch for each page.

**Spec reference:** `04_pre_scale_hardening_spec.md` §10

## Depends On
- None (foundation for T53)

## Scope
- Add `repositories.fetch_messages_by_ids(conn, dataset_id, message_ids) -> dict[str, Message]`
  - Preserve column parsing including `source_metadata_json`
  - Handle empty list gracefully
  - Chunk large IN clauses if needed (e.g. 500 IDs per query)
- Add `evidence_blocks.fetch_highlights_for_blocks(conn, block_ids) -> dict[int, frozenset[str]]` for batched highlight load
- Refactor embedding search hydration to use batch fetch
- Refactor any obvious N+1 in simple search hit enrichment (full UI pagination in T53)

## Guardrails
- **No arbitrary caps** on result completeness — batch only what is requested
- Do not change FTS ranking semantics

## Non-Goals
- FTS pagination API (T53)
- Virtualized transcript (T56)

## Acceptance Criteria
- Single batch query hydrates a page of 200 message IDs (or ≤2 chunked queries)
- Embedding search path uses batch fetch
- Evidence block list for a thread uses one highlight query for all blocks

## Tests
- Repository test: fetch_messages_by_ids returns correct map, preserves metadata
- Test highlight batch fetch
- `python -m pytest -q`
