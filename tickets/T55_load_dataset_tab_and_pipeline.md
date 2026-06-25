# T55 - Load Dataset Tab And Startup Pipeline

## Goal
Replace implicit bootstrap import with a temporary Load Dataset tab, narrated pipeline, auto-embedding attempt, and clean handoff to dataset-dependent tabs.

## Background
App currently imports on bootstrap and requires manual embedding on Settings. Spec requires Settings access before load, narrated pipeline, auto embedding with skip/retry, and tab removal after success. This ticket integrates the earlier scale foundations: streaming import, batch logging, and optimized embedding resume.

**Spec reference:** `04_pre_scale_hardening_spec.md` Section 9, Section A (largest-thread watchdog)

## Depends On
- T51 (streaming import and failed-import state)
- T61 (batch logging during import/embedding/load pipeline)
- T62 (optimized embedding resume path used by auto-embedding)

## Scope
- Main window opens with **Load Dataset** tab + **Settings** available; dataset-dependent tabs disabled or clearly unavailable until load succeeds.
- Load Dataset tab controls:
  - Load dataset button (normalized directory picker).
  - Status log (timestamped append-only narrative).
  - Cancel / skip / retry for embedding phase.
- Pipeline steps (narrate each):
  1. Open/create workspace DB.
  2. Schema migrate.
  3. Stream import (T51) or skip if existing + user choice.
  4. Rebuild FTS.
  5. Rebuild spellfix.
  6. `rebuild_dataset_sessions` (single startup place).
  7. Default categories / printable artifact groups.
  8. Auto embedding with T62 resume: preload model, validate sqlite-vec, message embeddings, chunk embeddings.
  9. Enable dataset tabs; remove temporary Load Dataset tab.
- Failed import handling:
  - If import fails, leave dataset-dependent tabs disabled.
  - Mark workspace/dataset load state as failed or stale.
  - Keep the Load Dataset tab visible with the error and retry path.
- Embedding failure/skip:
  - Open app with embedding features marked unavailable/stale.
  - Log next action; this is not a dead-end modal.
- Largest-thread watchdog:
  - If max thread count > threshold, e.g. 5000, narrate warning about virtualized scrolling (T56 may follow).
- CLI:
  - `--dataset`, `--db`, `--reload-dataset` auto-runs pipeline for CI/tests.
- Eliminate redundant `bootstrap_app` import + `set_dataset` double-load.

## Guardrails
- Settings tab usable before dataset load (API keys, context window).
- Do not block app open on embedding success.
- Do not enable dataset-dependent tabs after failed import.
- Session rebuild is **not** added back to exhaustive scan (T49).

## Non-Goals
- Virtualized transcript (T56).
- Embedding resume algorithm changes (T62 already done; integrate only).
- Raw donor import UI.

## Acceptance Criteria
- Fresh launch: Load Dataset + Settings visible; after successful load, dataset tabs work and Load Dataset tab removed.
- Second launch with existing workspace: offer load or open existing (minimal OK).
- CLI flags still work for tests.
- User can configure API keys in Settings before clicking Load Dataset.
- Failed import leaves dataset-dependent tabs disabled and shows retry path.
- Embedding skip/failure leaves usable app with clear stale/unavailable status.
- Auto-embedding uses T62 optimized resume path and does not load all embedded IDs into RAM.

## Tests
- UI smoke: tab disabled state before load.
- CLI bootstrap test with `--dataset` fixture path.
- Failed import test: malformed dataset does not enable dataset tabs and can retry.
- Embedding skip/failure smoke with mocked failure.
- `python -m pytest -q`
