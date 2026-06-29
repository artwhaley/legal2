# Large Dataset Performance - Ticket Orchestrator

## Source Spec
[05_large_dataset_performance_patch_spec.md](../05_large_dataset_performance_patch_spec.md)

## Execution Order

Run tickets **sequentially** unless a dependency note explicitly allows parallel work.

| Order | Ticket | Spec Section | Summary |
|------:|--------|--------------|---------|
| 1 | [T64](T64_thread_ordinals_and_indexed_transcript_access.md) | 8 | Add `thread_ordinal`, backfill, and replace transcript OFFSET/ROW_NUMBER paths |
| 2 | [T65](T65_transcript_virtualization_cleanup.md) | 9, 10 | Remove full-thread transcript escape hatches and all-slot notification loops |
| 3 | [T66](T66_remove_dataset_wide_ui_maps.md) | 7, 11, 12 | Remove full-dataset UI maps and bounded full-thread helper calls |
| 4 | [T67](T67_background_search_worker_and_cancel.md) | 2, 3 | Background search execution, generation fencing, and Cancel button |
| 5 | [T68](T68_real_sql_fts_pagination.md) | 4 | Push merged FTS pagination and counts into SQL |
| 6 | [T69](T69_explicit_search_modes_ui.md) | 1, 6 | Replace additive toggles with one explicit search mode UI |
| 7 | [T70](T70_expanded_keyword_mode_pagination.md) | 5 | Make keyword expansion its own paged mode |
| 8 | [T71](T71_embedding_modes_and_background_integration.md) | 6 | Separate message/chunk embedding modes and background result flow |
| 9 | [T72](T72_large_dataset_performance_regression.md) | 13, 14, 15, 16 | Scale tests, regression verification, and docs |

## Global Guardrails

- Do not revert unrelated dirty worktree changes.
- Run focused tests after each ticket; run `python -m pytest -q` before closing T72.
- Large-data principle: no new UI path may load a full dataset or full giant thread into Python memory unless the ticket explicitly documents a bounded exception.
- Completeness principle: page complete-result modes; do not silently cap accessible results.
- Search execution principle: typing text alone must not hit the database.
- Transcript principle: scrolling performance is solved first with indexed ordinal access, not by forcing transcript segmentation at ingest.
- Embedding principle: keep model execution on the existing safe background path; do not introduce unsafe PyTorch/QThread behavior.

## Reviewing Agent

Read `05_large_dataset_performance_patch_spec.md` first, then verify each ticket's acceptance criteria map to the spec sections before execution begins.

