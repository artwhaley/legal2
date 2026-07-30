# EWC15 Execution Log

## EWC15-000 baseline — 2026-07-23

- Repository: `C:\Users\artwh\OneDrive\Documents\legal2`
- Branch: `main`
- HEAD: `90735c2 (After court!)`
- Upstream: `origin/main`
- Worktree was already substantially dirty before this execution. Existing
  changes include the server-first split, temporary Python client, server
  package, Flutter project, EVW v14 implementation, generated fixtures/logs,
  and many deleted legacy Python files/tests. No existing changes were
  reverted.
- The v15 packet itself was present but had no execution log or closeout report.
- Baseline compile: PASS
  - `python -m compileall -q message_evidence_workstation server tests`
- Baseline package-boundary scan: PASS
  - `python scripts\\verify_package_boundaries.py`
- Baseline non-scale tests: PASS — `84 passed, 2 deselected`
  - `python -m pytest -q -m "not scale" --timeout=90 --basetemp=C:\\tmp\\legal2-v15-baseline`

## Initial architecture findings

The current implementation is v14-shaped and cannot be incrementally called
v15 without removing the old contract. The baseline contains `is_active`,
`working_corpus_message`, `working_corpus_index`, `vector_store_metadata`,
corpus/profile-partitioned vector tables, positional evidence slots, and
dataset-wide reload behavior. The Flutter tree contains only `lib/main.dart`
and `lib/src/native_extensions.dart`; the six-file v15 viewer surface does not
yet exist. The current Python workflow still resolves an implicit active
corpus and the current embedding workflow persists opaque profile identity.

These findings are the starting state for EWC15-100 onward, not accepted v15
behavior.

## Execution results

- Corrected revision membership insertion parameter order; fresh builds now
  materialize membership, FTS5, and spellfix rows correctly.
- Corrected the Python client conversational payload to the server contract's
  `text` field and forwarded server window progress events.
- Added explicit Python revision selection/refresh and explicit local embedding
  clearing. Removed destructive startup reload and unused embedding state,
  slot, and old FTS schema modules.
- Added the read-only Flutter v15 viewer/probe and strict
  `scripts/verify_evw_v15.py` validator.
- Migration copies deterministic legacy chunks and converts mapped legacy
  positional evidence; absent maps produce a candidate-only report and fail.
- Rebuilt `.tmp/sfv1-fixture-multicorpus-v15.evw`: corpus 3 revision 1 is
  99,980 tokens / 1,387 messages; corpus 2 revision 2 is 698,786 tokens /
  12,402 messages.
- Cache lifecycle probe: 1,269 distinct 100K hashes; 10,530 distinct 700K
  hashes; 1,269 reused during the 700K build; switch-back reused all 1,269;
  312 chunks built. Warm local-vector p95: 0.0381s messages / 0.0037s chunks.
- Python non-scale: 84 passed, 2 deselected. Scale: 2 passed. Flutter analyze,
  tests, Windows release build, real fixture probe, package boundaries,
  compileall, v15 validator, package build, and diff check passed.
