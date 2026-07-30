# Result-Preserving Validation V1 — Closeout Report

Date: 2026-07-30

## Outcome

RPV1-000 through RPV1-900 are complete. The result-preserving pipeline, source-integrity salvage, operation-local retries, compaction preservation, Python client contract, UI progress/status behavior, admin observability, and live proof are implemented and verified.

## Ticket disposition

- RPV1-000: baseline, authority, worktree, process, route, and control-store inventory complete.
- RPV1-100: new contracts, event set, prompt migration, and configuration validation complete.
- RPV1-200: readable synthesis preservation, citation salvage, result ordering, and unavailable fallback complete.
- RPV1-300: independent range salvage and source identity verification complete.
- RPV1-400: isolated window outcomes, targeted retries, coverage, and partial results complete.
- RPV1-500: synthesis receipt/validation sequencing and canonical-ledger-preserving compaction fallback complete.
- RPV1-600: prompts, admin schema/help, content-free logs, completion metrics, and warning metrics complete.
- RPV1-700: strict Python client, visible progress/status, persistence, and diagnostic runners complete.
- RPV1-800: deterministic regression and cleanup gates complete.
- RPV1-900: one authorized live GLM 5.2 run complete.

## Verification

- Full local regression: `172 passed, 2 deselected, 1 warning`.
- Scale tests: `2 passed`.
- Browser tests: `1 passed`.
- Compileall: PASS.
- Package boundaries: PASS.
- `git diff --check`: PASS; only existing line-ending warnings.
- Forbidden active-residue scan: NONE.

## Live proof

Artifact directory:
`.tmp/result-preserving-validation-live/20260730T193650Z-23cc0595/`

The run returned `completed` with `complete_with_warnings` and `structured_synthesis`: 9/9 windows usable, 87 canonical ledger ranges, 11 high-probability results, 18 lower-probability results, 13 unclassified ranges, 0 unverified statements, and one natural compaction level. Artifact hashes, verified citation identity, result ordering, and the visible Markdown divider were independently checked.

Debug capture was stopped/flushed. Temporary live configuration was restored through normal activation; active version is 66, draft version 67, schema 4, semantic retrieval remains enabled, utilization is back to 90%, and all five prompts match the packet defaults. Project server processes and scoped listeners are stopped. An unrelated VLC listener on port 8080 was not touched.

## Files

- [execution_log.md](C:/Users/artwh/OneDrive/Documents/legal2/docs/transformation/result_preserving_validation_v1/execution_log.md)
- [live run manifest](C:/Users/artwh/OneDrive/Documents/legal2/.tmp/result-preserving-validation-live/20260730T193650Z-23cc0595/run-manifest.json)
- [final public result](C:/Users/artwh/OneDrive/Documents/legal2/.tmp/result-preserving-validation-live/20260730T193650Z-23cc0595/final-result.json)
- [live Markdown report](C:/Users/artwh/OneDrive/Documents/legal2/.tmp/result-preserving-validation-live/20260730T193650Z-23cc0595/result.md)

The worktree remains dirty because extensive pre-existing user changes were preserved; no reset, checkout, commit, push, or unrelated cleanup was performed.
