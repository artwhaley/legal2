# Home Startup and Smart Embeddings — Ticket Orchestrator

## Source Spec
[07_home_startup_and_embeddings_spec.md](../07_home_startup_and_embeddings_spec.md)

## Execution Order

Run tickets **sequentially** unless a dependency note explicitly allows parallel work.

| Order | Ticket | Spec Section | Summary |
|------:|--------|--------------|---------|
| 1 | [T81](T81_embedding_completion_hang_fix.md) | 1 | P0: stop UI-thread calibration; callback watchdog; binary-search calibration |
| 2 | [T82](T82_home_cold_start_tab.md) | 2 | Persistent Home tab; no auto-load; lazy tab shell |
| 3 | [T83](T83_background_embedding_pipeline.md) | 3 | Unlock tabs after import; unify on mew-embedding; cache/reuse |
| 4 | [T84](T84_per_model_vec_partition_key.md) | 4 | model_name partition key migration; scoped insert/search/count |
| 5 | [T85](T85_embedding_progress_status_bar.md) | 5 | Global status bar; AppContext.embedding_state |
| 6 | [T86](T86_embedding_search_readiness_gating.md) | 5 | Grey out embedding modes; conversational warning banner |
| 7 | [T87](T87_home_startup_embeddings_regression.md) | 6 | Full regression, docs, smoke checklist |

## Global Guardrails

- Do not revert unrelated dirty worktree changes.
- Run focused tests after each ticket; run `python -m pytest -q` before closing T87.
- **UI thread principle:** callbacks from `embedding_worker` and `background_tasks` must complete in < 100ms. Heavy work belongs on background threads only.
- **Embedding principle:** PyTorch / sentence-transformers stay on `mew-embedding` (plain `threading.Thread`, never QThread).
- **Startup principle:** normal launch never auto-loads a dataset; user must click Load Dataset on Home.
- **Completeness principle:** semantic chunk calibration still runs — once, on background thread, cached in metadata — not removed, only relocated and optimized.
- **Storage principle:** vectors stay in workspace `.evw`; no separate embedding database.
- T55 Load Dataset tab behavior is superseded by T82/T83 for normal user launch; retain CLI auto-run for CI.

## Reviewing Agent

Read `07_home_startup_and_embeddings_spec.md` executive summary and Section 1 root cause, then verify each ticket's acceptance criteria before execution begins.

---

# Orchestrator Prompt (paste into agent)

You are implementing **Home Startup and Smart Embeddings** for the Message Evidence Workstation.

**Workspace:**

```text
C:\Users\artwh\OneDrive\Documents\legal2
```

## Mission

Fix the embedding-completion UI freeze on large datasets, deliver a fast cold-start Home tab with manual dataset loading, run embeddings intelligently in the background with progress and cache reuse, and persist vectors per embedding model in the workspace DB.

This is a legal evidence workstation. Search quality matters — message embeddings, chunk embeddings, and semantic chunk calibration are **real features**, not fluff. The bug was running calibration on the UI thread (60+ minutes for 15k messages). The fix is: calibrate once on a background thread, cache the result, never block the event loop.

## Current Problems

1. **Hang after embedding completes:** `settings_tab._update_chunk_preview()` runs from `on_success` on the UI thread. It calls `calibrated_config_for_dataset()` + `count_dataset_chunks()`, each doing a 101-iteration semantic threshold sweep over all messages with pure-Python cosine similarity — twice. ~60+ minutes frozen UI for 15k messages.
2. **Bad startup UX:** auto-runs julie_kramer donor, auto-activates workspace dataset on reopen, builds all tabs eagerly, Settings preloads embedding model at init.
3. **Embedding pipeline split:** load tab uses `mew-background` + separate adapter; Settings/search use `mew-embedding`. Vectors not model-scoped — switching models corrupts cache semantics.

## Execute Tickets In Order

1. `T81_embedding_completion_hang_fix.md`
2. `T82_home_cold_start_tab.md`
3. `T83_background_embedding_pipeline.md`
4. `T84_per_model_vec_partition_key.md`
5. `T85_embedding_progress_status_bar.md`
6. `T86_embedding_search_readiness_gating.md`
7. `T87_home_startup_embeddings_regression.md`

Read `tickets/home_startup_embeddings_orchestrator.md` for the dependency table and guardrails.

## Implementation Protocol

- Inspect relevant code before editing.
- Keep changes incremental and testable; one ticket at a time.
- After each ticket: run focused tests listed in that ticket.
- Before closing T87: `python -m pytest -q`
- Do not remove semantic chunk calibration — optimize and relocate it.
- Do not block tab unlock on embedding completion (import unlocks tabs; embedding continues in background).
- Do not auto-load datasets on normal app launch.
- Preserve CLI `--dataset`, `--reload-dataset` for CI/tests.

## Key Files To Inspect

```text
message_evidence_workstation/ui/settings_tab.py          # _update_chunk_preview, on_success
message_evidence_workstation/ui/embedding_worker.py      # mew-embedding thread, callback delivery
message_evidence_workstation/ui/background_tasks.py      # run_background callback delivery
message_evidence_workstation/ui/main_window.py         # _activate_dataset, tab lock
message_evidence_workstation/ui/load_dataset_tab.py    # → home_tab.py
message_evidence_workstation/app_bootstrap.py            # dataset_id on startup
message_evidence_workstation/dataset_load_pipeline.py  # import + embed phases
message_evidence_workstation/embeddings/chunking.py    # calibrate_semantic_similarity_threshold
message_evidence_workstation/embeddings/index_jobs.py # build/resume/cache
message_evidence_workstation/embeddings/sqlite_vec_backend.py
message_evidence_workstation/ui/simple_search_tab.py
message_evidence_workstation/ui/conversational_tab.py
tests/test_load_dataset_pipeline.py
tests/test_embedding_index_resume.py
tests/test_ui_smoke.py
07_home_startup_and_embeddings_spec.md
```

## Definition Of Done

- Embedding index-build completion returns UI to responsive state in < 1 second (callback < 50ms).
- UI callback watchdog catches future regressions (> 100ms asserts in tests).
- App opens to Home + Settings; other tabs locked until user loads dataset.
- No auto-load from donor folder or workspace reopen.
- Tabs unlock after import; embeddings build in background with status bar progress.
- Cached embeddings reused when same dataset + model already built.
- Per-model vectors persist when switching models (same dimensions).
- Embedding search modes disabled with explanation until ready.
- Conversational tab shows degradation warning while message embeddings incomplete.
- Full test suite passes.
