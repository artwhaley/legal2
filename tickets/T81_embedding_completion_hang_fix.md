# T81 - Embedding Completion Hang Fix

## Goal
Stop the UI from freezing when message or chunk embedding index builds complete on large datasets. Add permanent instrumentation so this class of bug cannot recur.

## Background
After embedding ~15k messages, the app appears hung for 20+ minutes (or indefinitely from the user's perspective). Root cause: `settings_tab._update_chunk_preview()` runs synchronously from embedding `on_success` on the UI thread. It triggers two full semantic calibration sweeps (101 threshold iterations each) via `calibrated_config_for_dataset()` and `count_dataset_chunks()`, deserializing all embedding blobs into Python dicts and running pure-Python cosine similarity for every message decision.

**Spec reference:** `07_home_startup_and_embeddings_spec.md` Section 1

## Depends On
- None (P0 — ship first)

## Scope
- **`settings_tab.py` index-build `on_success`:** remove `_update_chunk_preview()` call; do O(1) work only (read `embedding_index_metadata`, update `embedding_status` label, re-enable build buttons).
- **`_update_chunk_preview()` rewrite:** read pre-cached `chunk_count` and calibrated threshold from `embedding_index_metadata.chunking_config_json`; no calls to `count_dataset_chunks`, `calibrated_config_for_dataset`, or `load_message_vector_map`.
- **`chunking.py`:** replace 101-iteration brute-force in `calibrate_semantic_similarity_threshold` with binary search (~7 iterations). Calibration still runs during chunk index build on background thread only.
- **`index_jobs.py`:** ensure calibrated threshold + chunk count are persisted in metadata at build completion (verify existing `chunking_config_json` write path).
- **`embedding_worker.py`:** wrap `_deliver_success` / `_deliver_error` with timing watchdog (> 100ms: log critical; assert in test mode via env flag or pytest marker).
- **`background_tasks.py`:** same callback timing watchdog on bridge delivery.
- **`main_window.py` `_activate_dataset()`:** split into immediate unlock + staggered deferred work via `QTimer.singleShot(0, ...)`.
- **Lazy transcript load:** `TranscriptWidgetTab.set_dataset()` / `NewTranscriptWidgetTab.set_dataset()` populate thread combo only; defer first `load_source_thread()` until tab shown or deferred timer.

## Guardrails
- Do not remove semantic chunk calibration — relocate and optimize only.
- Do not call `load_message_vector_map()` on UI thread anywhere.
- Watchdog must not break normal fast callbacks in production (log warning; assert only under test).

## Non-Goals
- Home tab redesign (T82)
- Status bar (T85)
- Per-model vec migration (T84)

## Acceptance Criteria
- After message or chunk index build completes on a large dataset fixture, UI is responsive within 1 second.
- `on_success` callback for index build completes in < 50ms (with mocked or small fixture).
- `_update_chunk_preview()` performs no chunk iteration or calibration — metadata read only.
- Binary search calibration produces equivalent or acceptable threshold vs brute-force on test fixture.
- Callback watchdog test fails if a slow callback is injected.

## Tests
- `tests/test_embedding_completion_no_ui_block.py` (new)
- Update existing embedding index / settings tests as needed
- `python -m pytest tests/test_embedding_index_resume.py tests/test_message_embedding_index.py tests/test_chunk_embedding_index.py -q`
