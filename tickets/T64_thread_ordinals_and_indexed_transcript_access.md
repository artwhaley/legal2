# T64 - Thread Ordinals and Indexed Transcript Access

## Goal
Add a durable per-thread message ordinal and switch transcript range/focus access from `OFFSET`/`ROW_NUMBER()` to indexed ordinal lookups.

## Background
Transcript virtualization exists, but deep scroll and message focus still rely on expensive positional access patterns that degrade badly on large threads.

**Spec reference:** `05_large_dataset_performance_patch_spec.md` Sections 8, 14

## Depends On
- None

## Scope
- Add `thread_ordinal` to `message` schema, migration, and backfill for existing datasets
- Create supporting indexes for:
  - `(dataset_id, source_thread_id, thread_ordinal)`
  - uniqueness of ordinal within a thread where supported
- Compute/backfill ordinals after normalized import completes
- Replace repository helpers:
  - `fetch_messages_for_slot_range`
  - `message_index_in_thread`
  - any equivalent slot/range fetch helper
  with ordinal-based indexed SQL
- Add direct ordinal lookup helpers as needed for evidence block and conversational range reads

## Guardrails
- Preserve existing chronological ordering semantics
- Migration must be idempotent
- Do not introduce a full-thread Python backfill path when SQL window functions can do the work

## Non-Goals
- Transcript UI cleanup beyond what is required to consume new repository helpers
- Search mode/UI changes

## Acceptance Criteria
- Transcript range fetch uses `thread_ordinal` bounds, not `LIMIT/OFFSET`
- Message focus/index lookup uses one indexed query, not `ROW_NUMBER()`
- Existing datasets are backfilled successfully on schema init
- Reloaded/imported datasets have correct ordinals

## Tests
- Repository tests for ordinal backfill and indexed range fetch
- Transcript data source tests updated for ordinal semantics
- `python -m pytest -q`

