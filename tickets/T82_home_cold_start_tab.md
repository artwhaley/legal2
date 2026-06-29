# T82 - Home Cold-Start Tab

## Goal
Deliver a fast app launch with a persistent Home tab and manual dataset loading. No auto-load, no workspace reopen activation.

## Background
Users need the window to appear immediately with only Home + Settings usable. Dataset loading is explicit via Load Dataset button. T55's temporary Load Dataset tab is superseded by a permanent Home tab.

**Spec reference:** `07_home_startup_and_embeddings_spec.md` Section 2

## Depends On
- T81 (deferred `_activate_dataset` patterns; can proceed in parallel if T81 lands first)

## Scope
- Rename/repurpose `load_dataset_tab.py` → `home_tab.py` (update imports).
- **`app_bootstrap.py`:** normal launch always returns `dataset_id=None` for UI; do not call `_ready_dataset_id()` for activation (DB rows may remain for embedding cache).
- **`main_window.py`:**
  - Always show Home at index 0 on init; disable dataset tabs; focus Home.
  - Remove `_needs_load_dataset_tab` auto-activate branch for existing workspace dataset.
  - Remove `_should_auto_run_load()` default-donor auto-run (keep CLI `--dataset` auto-run).
  - Remove `_remove_load_dataset_tab()` — Home stays permanently.
  - After successful load: grey out Load Dataset button on Home (same session).
- Remove **"Open existing workspace dataset"** button.
- Lazy tab construction: build Home + Settings first; defer heavy tabs (transcript widgets, conversational) until first unlock OR use lightweight placeholders.
- **`settings_tab.py`:** remove `start_embedding_model_preload()` from `__init__`.
- **`home_tab.py`:** on `showEvent`, call `preload_embedding_model()` via `embedding_worker`.
- Add `QStatusBar` shell (wired fully in T85).

## Guardrails
- CLI `--dataset`, `--reload-dataset` must still auto-run for CI/tests.
- Settings tab remains usable before dataset load.
- Do not wipe workspace DB on startup — only UI activation state is cleared.

## Non-Goals
- Decouple import from embedding (T83)
- Status bar progress wiring (T85)
- Dataset switching UX

## Acceptance Criteria
- Fresh launch with donor folder present: Home shown, tabs locked, no import until Load Dataset clicked.
- Launch with ready dataset in workspace DB: still Home, `dataset_id=None`, tabs locked.
- Window appears without loading transcript/conversational tabs eagerly (measure or smoke-test init path).
- Embedding model preload starts from Home show, not Settings init.
- After load in same session: Load Dataset button disabled on Home.
- CLI `--dataset` still auto-runs pipeline in tests.

## Tests
- `tests/test_home_startup_no_auto_load.py` (new)
- `tests/test_home_startup_no_reopen_activate.py` (new)
- Update `tests/test_load_dataset_pipeline.py`, `tests/test_ui_smoke.py`
- `python -m pytest tests/test_load_dataset_pipeline.py tests/test_ui_smoke.py -q`
