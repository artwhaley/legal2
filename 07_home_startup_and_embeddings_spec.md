# Home Startup and Smart Embeddings Spec

## Executive Summary

Large datasets exposed four problems:

1. **UI freeze after embedding completes** - Settings index-build callbacks run semantic chunk calibration on the UI thread. For roughly 15k messages this can block the event loop for a very long time.
2. **Slow, confusing startup** - The app auto-loads donor datasets, auto-activates workspace datasets on reopen, and builds all tabs eagerly before the user chooses a file.
3. **Embedding workflow fragility** - Load-tab embedding uses a separate background thread and adapter from Settings/search. Vectors are not model-scoped, so switching models can invalidate or confuse cached indexes.
4. **Slow import handoff** - Large reloads can spend many minutes after the final message progress line before FTS starts, and Step 6 can spend minutes building transcript sessions.

This spec delivers:

- **P0 hang fix** with permanent UI-callback instrumentation
- **Persistent Home tab** - cold start shows Home + Settings only; manual Load Dataset
- **Fast import handoff** - post-message cleanup and import-time session rebuild complete quickly and do not run semantic/vector work before tab unlock
- **Background embedding pipeline** - tabs unlock after import; embeddings continue with status bar progress
- **Per-model vector persistence** in the workspace `.evw` file via sqlite-vec partition keys
- **Search UX gating** - embedding modes disabled until ready; conversational warning banner

## Non-Goals

- Dataset switching / save-load workspace UX
- Text-message importer
- Separate embedding database file
- Per-dimension multi-table vector storage; models with different dims cannot coexist in one vec table

## Section 1 - Embedding Completion Hang (P0)

### Root Cause

`settings_tab._update_chunk_preview()` runs on the UI thread from embedding `on_success`. It calls `calibrated_config_for_dataset()` and `count_dataset_chunks()`, each triggering semantic calibration over the full dataset with pure-Python cosine similarity.

### Requirements

- Index-build `on_success` / `on_error` callbacks do O(1) UI work only: read metadata, update labels, re-enable buttons.
- `_update_chunk_preview()` reads pre-cached counts/threshold from `embedding_index_metadata.chunking_config_json`; no live calibration on UI thread.
- Calibration runs once during chunk index build on `mew-embedding` thread; result is persisted in metadata.
- Replace 101-iteration brute-force threshold sweep with binary search, about seven iterations.
- UI-thread callback watchdog in `embedding_worker.py` and `background_tasks.py`: assert/log if callback exceeds 100ms.
- Split `_activate_dataset()`: defer sidebar populate, transcript first-thread load, settings budget preview via staggered timers.
- Lazy transcript load: populate thread combo in `set_dataset()`; defer `load_source_thread()` until tab visible or deferred timer.

## Section 2 - Fast Cold-Start Home Tab

### Requirements

- Every normal app launch: `AppContext.dataset_id = None`; `MainWindow` never calls `_activate_dataset()` on init.
- Persistent **Home** tab at index 0; never removed after load.
- Only Home + Settings enabled on startup; all dataset tabs greyed out.
- No auto-run from `default_dataset_path()`; no `Open existing workspace dataset` button.
- User clicks **Load Dataset**, chooses a folder, and starts the import pipeline.
- After successful load in same session: grey out Load Dataset button on Home.
- Embedding model preload on Home `showEvent` via `embedding_worker`, not Settings `__init__`.
- Lazy construction of heavy tabs, or lightweight placeholders, until first unlock.
- CLI `--dataset` / `--reload-dataset` still auto-runs pipeline for CI/tests.

## Section 3 - Smarter Embedding Pipeline And Fast Import Handoff

### Requirements

- Route all index builds through `embedding_worker.run_embedding_job` on the `mew-embedding` thread.
- Import pipeline stays on `mew-background`; it is IO/SQL-bound and must not run PyTorch.
- After import succeeds: unlock dataset tabs immediately; embedding continues in background.
- Blocking import must be fast:
  - narrate and time the post-message tail after the final `messages: read N, wrote N` line
  - optimize `source_thread.message_count` updates and `message.thread_ordinal` backfill so Julie Kramer-scale reloads do not spend minutes before FTS starts
  - avoid full embedding snapshot/restore in the blocking import handoff when cache/reuse can preserve or rebuild vectors safely
- Fast must not mean lossy:
  - `source_thread.message_count` must exactly match imported messages per thread
  - `message.thread_ordinal` must remain stable, gapless, zero-based, and ordered by canonical transcript order
  - FTS, spellfix, evidence-block links, and transcript navigation invariants must remain correct
  - failures must be surfaced in logs/status, not hidden behind a faster unlock
- Step 6 import-time transcript sessions must not run semantic chunking or vector scans:
  - use lightweight time/day sessions with `use_semantic_chunks=False`, or defer semantic session refinement to background post-processing
  - no blocking import path may call `iter_dataset_chunks()`, `count_dataset_chunks()`, `calibrated_config_for_dataset()`, or `load_message_vector_map()`
  - if semantic sessions are deferred, baseline sessions must still be valid and deterministic, and semantic refinement must run later from cached/calibrated metadata before claiming semantic readiness
- On load: check `get_ready_index()` for message + chunk with active model; skip build if complete and config matches.
- Partial builds resume via existing checkpoint logic in `index_jobs.py`.

## Section 4 - Per-Model Vector Persistence

### Requirements

- Keep vectors in workspace `.evw`, not a separate DB.
- Rebuild vec tables with `model_name text partition key`; sqlite-vec >= 0.1.6 supports partition keys.
- All insert/search/count paths filter by active `model_name`.
- `mark_indexes_stale_for_model_change`: mark metadata stale only; do not delete other models' vectors.
- Document limitation: per-model persistence only when models share the same vector dimension count.

## Section 5 - Status Bar And Search Gating

### Requirements

- Global status bar: `Message embeddings: N / M | Chunk embeddings: X / Y`.
- `AppContext.embedding_state` for tabs to query readiness and progress.
- Simple Search: disable message/chunk embedding combo items when index not ready; tooltip explains why.
- Conversational: warning banner while message embeddings are incomplete.

## Section 6 - Regression

- `test_embedding_completion_no_ui_block` - completion callback < 50ms
- `test_home_startup_no_auto_load` - donor present, no import until button click
- `test_home_startup_no_reopen_activate` - DB has ready dataset, UI still at Home
- `test_per_model_embedding_cache` - switch models, switch back, no rebuild for same dims
- Update load pipeline / UI smoke tests for persistent Home tab
- Update `docs/smoke_test_checklist.md` and `docs/known_limitations.md`

## Review Checklist

- [ ] No UI-thread path calls `count_dataset_chunks`, `calibrated_config_for_dataset`, or `load_message_vector_map`
- [ ] Callback watchdog present and tested
- [ ] Cold start never auto-loads dataset
- [ ] Home tab persistent; Load button greyed after load
- [ ] Tabs unlock after import, not after embedding
- [ ] Import Step 3 tail and Step 6 complete quickly on large datasets
- [ ] Import-time session rebuild does not call semantic chunking or load message vectors
- [ ] Speed optimizations preserve exact counts, stable ordinals, FTS/spellfix correctness, evidence links, and valid baseline sessions
- [ ] Deferred semantic refinement is visible, cached, and verified before any UI claims semantic session readiness
- [ ] Status bar updates during embedding build
- [ ] Embedding search modes gated until ready
- [ ] Per-model vectors persist when switching back for same dims
