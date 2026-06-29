# T87 - Home Startup and Embeddings Regression

## Goal
Close the ticket stack with full regression coverage, documentation updates, and smoke checklist alignment.

## Background
Final verification that hang fix, startup UX, embedding pipeline, per-model cache, and search gating work together on large and small datasets.

**Spec reference:** `07_home_startup_and_embeddings_spec.md` Section 6

## Depends On
- T81 through T86

## Scope
- Consolidate and run full test additions from prior tickets:
  - `test_embedding_completion_no_ui_block`
  - `test_home_startup_no_auto_load`
  - `test_home_startup_no_reopen_activate`
  - `test_per_model_embedding_cache`
- Update `tests/test_load_dataset_pipeline.py` for persistent Home tab + import-only unlock.
- Update `tests/test_ui_smoke.py` monkeypatches if Home owns preload.
- Update `docs/smoke_test_checklist.md`:
  - Cold start: Home + Settings only
  - Manual Load Dataset
  - Status bar during embed
  - Embedding modes greyed until ready
- Update `docs/known_limitations.md`:
  - Per-model cache dimension constraint
  - Embedding build time on large datasets
  - No cross-session loaded-dataset UI state
- Update `02_ticket_index.md` if not already done.
- Optional scale test: verify callback watchdog + no UI block with large fixture (may use mocked calibration).

## Guardrails
- Full suite must pass before closing.
- Do not expand scope into dataset switching or new importers.

## Non-Goals
- New features beyond spec

## Acceptance Criteria
- `python -m pytest -q` passes.
- Smoke checklist reflects new startup and embedding UX.
- Known limitations document per-model dimension constraint.
- All T81–T86 acceptance criteria still met in integrated run.

## Tests
- `python -m pytest -q`
