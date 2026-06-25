# T54 - Simple Search Pagination UI

## Goal
Expose FTS pagination in Simple Search UI with clear "Showing X–Y of Z" readout and Previous/Next navigation.

## Background
Backend pagination (T53) must be usable without hiding results from the operator.

**Spec reference:** `04_pre_scale_hardening_spec.md` §3.3, §3.4

## Depends On
- T53 (paginated FTS API)
- T52 (batch hydration)

## Scope
- Simple Search results pane:
  - Previous / Next page controls
  - Display: "Showing 1–200 of 9,847 matches" when total known
  - Optional "load more" in results pane only (not transcript)
- Wire paginated `search_messages` calls
- Embedding lane: keep top-K selectivity; label in UI as vector similarity top-K (honest ranking limit)
- Hybrid display: FTS pages and embedding results remain clearly separate if both shown

## Guardrails
- No silent truncation messaging
- Do not cap total accessible results

## Non-Goals
- Virtualized transcript (T56)
- Conversational search changes

## Acceptance Criteria
- User can navigate all pages of a high-hit query
- Total count displayed when available
- No regression in exact-match ranking within a page

## Tests
- UI smoke test: search returns pagination controls when hits > page size (may use crafted fixture or mock)
- `python -m pytest -q`
