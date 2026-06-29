# T67 - Background Search Worker and Cancel

## Goal
Move search work off the UI thread and add user-visible cancellation with stale-result protection.

## Background
Search currently performs expensive work synchronously from the UI, and typing/interaction can leave the app feeling stuck on large datasets.

**Spec reference:** `05_large_dataset_performance_patch_spec.md` Sections 2, 3

## Depends On
- T66

## Scope
- Add background search worker module and job/result types
- Use separate worker SQLite connections
- Add generation fencing / stale-result suppression
- Add Cancel button and active-search UI state
- Route expensive search work through the background path:
  - FTS
  - expanded keyword mode
  - result hydration
  - grouping
- Keep embedding mode integration safe with the existing embedding worker model; this ticket provides the UI state/cancellation contract

## Guardrails
- No Qt widget access from worker code
- Cancel may ignore stale results if true low-level interruption is not safe; do not fake completion as success
- Do not run searches on text change

## Non-Goals
- Final explicit mode UI polish
- SQL-level FTS query rewrite

## Acceptance Criteria
- Search no longer freezes the UI thread on common-term queries
- Cancel is enabled during active search and suppresses stale result rendering
- Enter/Search button is the only search trigger path

## Tests
- UI tests for enter-to-search, no-search-on-typing, and cancel/stale-generation handling
- `python -m pytest -q`

