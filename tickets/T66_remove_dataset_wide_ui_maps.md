# T66 - Remove Dataset-Wide UI Maps

## Goal
Remove dataset-wide in-memory message maps and other full-thread convenience loads from Simple Search, Conversational, Sidebar, and related bounded-read helpers.

## Background
Several tabs currently bind a dataset by loading every `message_id -> sort_index` pair into Python, and some workflows still read full threads just to derive a bounded range.

**Spec reference:** `05_large_dataset_performance_patch_spec.md` Sections 7, 11, 12

## Depends On
- T64

## Scope
- Remove dataset-wide `_sort_index_by_message` initialization from:
  - `SimpleSearchTab`
  - `ConversationalTab`
- Refactor grouping/order logic to use:
  - current-page order metadata, or
  - enriched hit ordinals/order keys from the search layer
- Replace bounded workflows that currently call `list_messages_for_thread`, including:
  - conversational read helpers
  - search-result drop/evidence block creation helpers
  - any similar bounded-range utility
- Keep thread lists (`list_source_threads`) where they are legitimately needed for navigation UI

## Guardrails
- Do not degrade grouping correctness for nearby hits
- Avoid introducing hidden N+1 lookup loops while removing global maps
- Preserve existing user-visible workflows

## Non-Goals
- Search worker/background execution
- FTS pagination internals

## Acceptance Criteria
- Dataset bind for Simple Search and Conversational does not query all messages
- Bounded conversational/search-result workflows do not load full threads
- Result grouping still behaves correctly for current-page hits

## Tests
- UI smoke tests updated to assert no dataset-wide message bind query path
- Conversational/tool helper regression tests
- `python -m pytest -q`

