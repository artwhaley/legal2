# T83 - Background Embedding Pipeline

## Goal
Unlock dataset tabs immediately after a fast import while embeddings and semantic post-processing continue in the background on the unified `mew-embedding` thread, reusing cached indexes when available.

## Background
Today the load pipeline blocks tab handoff until embedding completes, and load-tab embedding runs on `mew-background` with a separate PyTorch adapter instance from Settings/search. Users should keyword-search immediately after import while embeddings build with visible progress.

Large reloads also revealed two import-phase slow paths that must be treated as performance bugs, not just progress-reporting bugs:

- After the final `messages: read N, wrote N` line, synchronous cleanup can spend many minutes updating counts, assigning ordinals, or snapshotting/restoring cached embeddings before Step 4 appears.
- Step 6 currently builds transcript sessions with semantic chunking by default. That can invoke vector loading and semantic chunk calibration during the blocking import path, which is not acceptable for large datasets.

**Spec reference:** `07_home_startup_and_embeddings_spec.md` Section 3

## Depends On
- T82 (Home tab signals and handoff)

## Scope
- **`home_tab.py` / `dataset_load_pipeline.py`:** split handoff so import success emits `dataset_imported` or an equivalent signal, then `MainWindow` unlocks dataset tabs.
- Embedding phase runs after unlock; it must not block `load_completed` or equivalent import handoff.
- New signal or extended result reports `embeddings_ready` when both indexes are ready for the active model.
- Add explicit narration/progress around the hidden post-message import tail before `run_import_pipeline()` emits completion:
  - updating `source_thread.message_count`
  - backfilling `message.thread_ordinal`
  - restoring cached embeddings after reload, when applicable
  - returning from `load_normalized_dataset()`
- The user-facing load log must not stop after `messages: read N, wrote N` while synchronous import cleanup is still running.
- Make the post-message import tail fast:
  - `source_thread.message_count` updates should be set-based SQL or one bounded query per thread, not per-message Python work.
  - `message.thread_ordinal` backfill must complete in seconds for a 15k-message single-thread dataset; if the current window-function update is slow on SQLite, replace it with an indexed temp-table or streaming `executemany` approach and add timing coverage.
  - Do not snapshot/restore full embedding blobs during the blocking import handoff when the later cache/reuse path can preserve or rebuild embeddings safely. If reload must preserve cached vectors before T84 lands, narrate and batch it with measurable progress.
- Make Step 6 fast:
  - Blocking import-time session rebuild must not call `iter_dataset_chunks()`, `count_dataset_chunks()`, `calibrated_config_for_dataset()`, or `load_message_vector_map()`.
  - During import, build lightweight time/day transcript sessions with `use_semantic_chunks=False`, or defer semantic session refinement to the background embedding/semantic post-processing phase.
  - Semantic session/chunk-derived refinement may run later, but it must not prevent tab unlock.
- Preserve correctness while improving speed:
  - `thread_ordinal` values must remain stable, gapless, zero-based, and ordered by the canonical transcript order.
  - `source_thread.message_count` must exactly match the imported message count per thread.
  - Import-time sessions must be valid and deterministic: every message belongs to the expected time/day session grouping, session boundaries reference real message IDs, and persisted sessions pass existing conversational/session tests.
  - Do not remove semantic session/chunk quality. If semantic sessions are deferred, they must run later from cached/calibrated metadata and replace or refine lightweight sessions only after a successful background pass.
  - Do not preserve speed by silently dropping cached embeddings, skipping FTS/spellfix, weakening evidence-block links, or hiding failures.
- Route load-tab embedding through `embedding_worker.run_embedding_job` instead of `run_background` plus inline adapter work in `run_embedding_pipeline`.
- Remove duplicate adapter load on `mew-background` for embedding.
- On embed start, call `get_ready_index()` for message and chunk with `settings.embedding_model`; skip build if complete and chunking config matches.
- Partial builds resume via existing checkpoint logic in `index_jobs.py`.
- Log `reusing cached embeddings` when the skip path is taken.
- Preserve skip/cancel/retry embedding controls on Home during embed phase.

## Guardrails
- Import still uses `mew-background` with separate worker `conn`; no PyTorch on the import thread.
- Failed import must not unlock tabs.
- Embedding failure must not re-lock tabs; mark embedding unavailable and allow retry from Home or Settings.
- Do not delete cached vectors on skip.
- The blocking import phase should be IO/SQL work only. Semantic chunking, vector scans, embedding calibration, and PyTorch work belong after unlock.
- Fast must not mean lossy. Any optimized path must preserve the same database invariants and search/session correctness, or it must explicitly defer higher-quality semantic refinement with visible status.

## Non-Goals
- Per-model partition key (T84); cache check uses current metadata plus vec rows as-is until T84.
- Status bar UI (T85); emit progress via existing log bus and T85 wires display.

## Acceptance Criteria
- After import completes, dataset tabs unlock before embedding finishes.
- During reload/import, the log shows progress for post-message cleanup before FTS begins; a large import cannot appear stuck immediately after the final `messages` progress line.
- Step 3 post-message cleanup and Step 6 session rebuild are fast enough for the Julie Kramer scale dataset to complete in seconds, not many minutes. If exact local timing varies, tests must enforce no semantic/vector work in those blocking paths.
- Step 6 import-time session rebuild does not call semantic chunking or load message vectors.
- Optimized import still produces exact message counts, stable ordinals, valid FTS/spellfix indexes, and deterministic baseline transcript sessions.
- If semantic session refinement is deferred, the UI/status/log clearly reports baseline sessions first and semantic refinement readiness later.
- Embedding builds on `mew-embedding` thread only; no parallel adapter on `mew-background`.
- Re-loading same dataset and model with ready indexes skips rebuild and logs cache reuse.
- Partial embedding resumes from checkpoint on retry.
- Skip embedding unlocks tabs with `embedding_available=False`.

## Tests
- Update `tests/test_load_dataset_pipeline.py` for import-only unlock.
- Add/extend tests proving import-time `rebuild_dataset_sessions` is called with `use_semantic_chunks=False` or is deferred.
- Add/extend tests proving optimized import preserves message counts, ordinals, and valid session boundaries.
- Add a regression test around post-message cleanup progress narration.
- Test cache skip path with pre-built metadata.
- `python -m pytest tests/test_load_dataset_pipeline.py tests/test_embedding_index_resume.py -q`
