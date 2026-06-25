# T53 - FTS Pagination And Search API

## Goal
Add paginated FTS search with total hit count and deterministic ordering. Never silently truncate results.

## Background
FTS queries return unbounded hit lists. Product principle: completeness over convenience - paginate, do not cap.

**Spec reference:** `04_pre_scale_hardening_spec.md` Section 3 (backend), Section 3.4 embedding labeling note

## Depends On
- T52 (batch hydration for page results)

## Scope
- Extend `search/fts.py`:
  - Paginated query: `limit`, `offset` for the first pass.
  - Stable ordering: rank, then `(timestamp, sort_index, message_id)`.
  - Return structure: `{ hits, total_count, has_more, next_offset }`.
  - `total_count` via `COUNT(*)` with the same MATCH semantics.
- Multi-token search semantics:
  - Build one merged FTS result set.
  - De-duplicate by `message_id`.
  - Rank deterministically after merge.
  - Paginate **after** merge/de-dupe.
  - `total_count` reflects the merged, de-duped result count.
- Document/keyset cursor fields for future if offset pagination is too slow or unstable on scale fixtures.
- Extend `search_messages` to support pagination parameters.
- Add configurable default page size in settings (default **200**; page size, not total cap).
- Batch-hydrate hits for current page via T52 helper.
- Label embedding results in return type/docs as "top K by similarity" (ranking budget, not completeness claim).

## Guardrails
- Do not drop hits beyond the current page; user must reach all pages.
- No silent truncation in logs.
- Do not paginate each token lane separately unless explicitly adding an equivalent merged/de-duped view.

## Non-Goals
- Simple Search UI controls (T54).

## Acceptance Criteria
- High-frequency token search returns `total_count` matching unbounded merged/de-duped semantics.
- Page ordering deterministic across repeated identical queries on unchanged DB.
- Multi-token search total count and pages are based on merged/de-duped hits.
- Page of 200 hits uses batch hydration, not 200 queries.

## Tests
- FTS pagination unit tests with fixture.
- Total count matches full merged/de-duped result set on small fixture.
- Multi-token query test proves duplicate message hits are counted once.
- `python -m pytest -q`
