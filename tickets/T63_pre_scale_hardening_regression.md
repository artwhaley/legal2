# T63 - Pre Scale Hardening Regression

## Goal
Close the hardening stack with scale test harness, documentation updates, and full regression verification against `04_pre_scale_hardening_spec.md` review checklist.

## Background
Tickets T46-T62 implement the spec incrementally. This ticket verifies end-to-end coherence before large donor dataset testing.

**Spec reference:** `04_pre_scale_hardening_spec.md` review checklist, Section F, Section B

## Depends On
- T46 through T62 (all prior hardening tickets)

## Scope
- Add optional `@pytest.mark.scale` tests:
  - Generated 100k-message JSONL import using streaming path.
  - Failed import fixture proves stale/failed state and no dataset-dependent tab enablement.
  - 50k-message single-thread transcript navigation smoke if feasible in CI/manual time budget.
  - 50k-message exhaustive scan planning smoke that proves bounded planner memory and no full-thread list construction.
  - 10k-message UI scroll perf smoke if 50k is too slow for automated widget tests.
- Keep default test suite fast:
  - Mark scale tests so normal `python -m pytest -q` does not run the heaviest cases unless project policy already includes them.
  - Document `python -m pytest -m scale -q` for manual/nightly validation.
- Update `docs/smoke_test_checklist.md` for:
  - Load Dataset tab flow.
  - Context window required before conversational use.
  - Paginated search.
  - Print preview / PDF export.
  - No workstation conversation steps.
- Update `docs/known_limitations.md`:
  - SQLite single-writer discipline.
  - Whole-transcript mode still loads full dataset when selected (document until future optimization).
  - Session-coverage path legacy status.
  - Single embedding worker limitation.
- Verify spec review checklist items; file checklist completion notes in PR or ticket comment.
- Run full `python -m pytest -q`.

## Guardrails
- Do not add new features; regression and docs only unless checklist reveals a missed T46-T62 acceptance criterion.
- If a gap is found, fix minimal delta or file follow-up ticket; do not expand scope.
- Scale tests may be skipped in default local runs, but they must exist and be documented.

## Non-Goals
- Client/server refactor.
- Raw donor importers.
- Env var consolidation.

## Acceptance Criteria
- Full fast test suite passes.
- Spec review checklist items verifiably satisfied (document mapping ticket -> checklist item).
- Scale tests exist and are marked.
- 100k import scale test exists and passes in manual/nightly mode.
- Large single-thread transcript/planner test exists; if not runnable in CI, document manual command and expected thresholds.
- Smoke checklist matches current app behavior.

## Tests
- `python -m pytest -q` (required)
- `python -m pytest -m scale -q` documented for manual/CI nightly
