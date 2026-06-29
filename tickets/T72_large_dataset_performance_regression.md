# T72 - Large Dataset Performance Regression

## Goal
Close the large-dataset performance stack with scale tests, regression verification, and doc updates based on `05_large_dataset_performance_patch_spec.md`.

## Background
Tickets T64-T71 implement the large-dataset patch incrementally. This ticket verifies the stack holds together and documents the new behavior for operators and developers.

**Spec reference:** `05_large_dataset_performance_patch_spec.md` Sections 13, 14, 15, 16

## Depends On
- T64 through T71

## Scope
- Add or extend `@pytest.mark.scale` tests for:
  - common-token FTS first-page behavior on large synthetic fixture
  - transcript focus/deep-scroll on very large single-thread fixture
  - no-search-on-typing UI behavior
  - stale/cancelled search result suppression
- Keep default suite fast; document `-m scale` execution
- Update docs as needed for:
  - explicit search modes
  - Enter/Search-only behavior
  - Cancelable background search
  - transcript ordinal/indexed scaling approach
- Run full fast suite and document any remaining known limits

## Guardrails
- No feature expansion beyond regressions, tests, and docs unless a prior ticket acceptance gap is discovered
- Scale tests may be marked out of default runs, but they must exist and be documented

## Non-Goals
- New product features outside the approved performance stack
- Broader architectural redesign

## Acceptance Criteria
- Full fast test suite passes
- Scale tests exist and are marked
- Docs reflect explicit modes, background search, and indexed transcript behavior
- Remaining large-data limitations are documented honestly

## Tests
- `python -m pytest -q` (required)
- `python -m pytest -m scale -q` documented for manual/nightly validation

