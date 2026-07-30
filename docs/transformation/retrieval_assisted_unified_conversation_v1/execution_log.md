# Execution log

This file is intentionally empty except for its heading. The execution agent
must append a dated baseline and one evidence section per RAUC1 ticket. Do not
copy prior packet completion claims into this log.

## 2026-07-29 — RAUC1-000 baseline and contact-surface inventory

- Repository: `C:\Users\artwh\OneDrive\Documents\legal2`
- Branch: `main`; HEAD: `90735c297d14370aa8e98d857ee5c19df8ced124`; upstream:
  `origin/main`; ahead/behind: `0/0`.
- Dirty-worktree snapshot was captured before implementation with
  `git status --porcelain=v1 --untracked-files=all`: 2,028 entries (19 modified,
  158 deleted, 1,851 untracked). Snapshot SHA-256 of the joined status lines:
  `98e0f9f8c035aaa2f18db100e92afaeb0ddf45b2440ed8e60fa661a26d64e8c3`.
  It includes pre-existing README/app/config/database/LLM/search/UI/test
  changes and extensive `.tmp`/fixture/process artifacts. Existing user work
  and existing processes were not reset, cleaned, reverted, stopped, staged,
  committed, pushed, or deployed.
- Existing processes observed and preserved: server PIDs 18780 and 47480
  (`python -m server`) with one listener on `127.0.0.1:8710`; UI-related
  `pythonw` PIDs 26816 and 54404.
- Baseline compile: `.\.venv\Scripts\python.exe -m compileall -q server message_evidence_workstation scripts tests` — exit 0.
- Baseline package boundary check:
  `.\.venv\Scripts\python.exe scripts/verify_package_boundaries.py` — PASS.
- Baseline focused SFV1 collection: 104 collected, 2 deselected by the
  missing-browser exclusion. The 102 selected tests reached green; pytest
  exited 1 during its final temp cleanup with `PermissionError: [WinError 5]`
  on pre-existing `pytest-current`. `test_sfv1_admin_browser.py` could not be
  collected because `.venv` lacks `playwright`.
- Current product POST routes: `/v1/keyword-expansion`,
  `/v1/conversational-analysis`, `/v1/embeddings` (three; retrieval-plan is
  absent). `/internal/live` and `/admin/*` are non-product routes.
- Current forbidden/legacy runtime contacts: `whole_corpus_answer` (config,
  contracts, conversation, prompts, admin, tests), `whole_corpus` and
  `windowed_ledger` result strategies, `ledger_reduction` and
  `ledger_reduction_max_depth`, and `retrieval_assistance_enabled`. The
  current server still has a direct whole-corpus branch and `build_whole_ledger`.
- Current control store: default state directory
  `C:\Users\artwh\.message_evidence_server`; control table reports schema 3,
  but all 13 stored versions have `config_schema_version=2`, six active
  operation names (`keyword_expansion`, `retrieval_terms`,
  `whole_corpus_answer`, `window_evidence_extraction`, `ledger_reduction`,
  `ledger_synthesis`), and v2 global keys. Version 12 is active and version 13
  is draft. Provider secrets were not printed; only masked/structural metadata
  was inspected. Existing audit count: 65; usage rows: 109.
- Debug capture inventory: four existing JSONL files under
  `C:\Users\artwh\.message_evidence_server\debug-captures`; the live server
  reported capture inactive, zero bound requests, zero pending records, and no
  writer failure. Existing files were not opened for corpus content.
- Fixture verification:
  `.\.venv\Scripts\python.exe scripts/verify_evw_v15.py .tmp\sfv1-fixture-multicorpus-v15.evw` — PASS.
  Revision 3: ready, 1,387 messages, 1,387/1,387 384-dimensional message
  embeddings, `unit_l2`, `cl100k_base`. Revision 4: ready, 12,402 messages,
  12,402/12,402 384-dimensional message embeddings, `unit_l2`, `cl100k_base`.
  The EVW was opened read-only for this inventory; EVW schema/lifecycle/WAL
  state was not changed.
- RAUC1-000 disposition: inventory complete; no unexplained mutation.
- Next dependency: RAUC1-100.

## 2026-07-29 — RAUC1-100 configuration v3 and clean operation migration

- Changed `server/config.py`, `server/config_store.py`, `server/prompts.py`,
  `server/admin.py`, and the control-store tests. Runtime configuration now
  declares schema v3 and exactly five operations:
  `keyword_expansion`, `retrieval_terms`, `window_evidence_extraction`,
  `ledger_compaction`, and `ledger_synthesis`.
- Added one explicit v2 payload migration: Boolean assistance maps
  `true -> terms_only` and `false -> disabled`; the old depth setting maps to
  `ledger_compaction_max_depth`; the removed whole assignment is dropped; the
  old reduction assignment is renamed while retaining its resolved fields.
  Migration preflights all payloads, writes normalized rows and one
  content-free audit record in one transaction, and leaves active/draft IDs and
  encrypted provider bindings unchanged. Runtime `ServerConfig.from_dict`
  accepts only v3.
- Added v3 retrieval settings and validation: mode, top-k, suggestion-message
  ceiling, RRF constant, and compaction depth. Bootstrap defaults are explicit.
- Focused command:
  `.\.venv\Scripts\python.exe -m pytest -q --basetemp .tmp\rauc1-100-config-tests tests\test_sfv1_control_store.py` — 15 passed.
- Safe copied-store proof: copied the current control DB and master key to
  `.tmp\rauc1-100-current-store-copy-20260729` without touching the real state;
  opening the copy produced schema 3, active version 12, the five final
  operations, `terms_only`, and one migration audit row.
- RAUC1-100 disposition: complete; full admin usability remains covered by its
  later dedicated RAUC1-500 gate.
- Next dependency: RAUC1-110.

## 2026-07-29 — RAUC1-110 strict retrieval/analysis contracts

- Replaced `server/contracts.py` and the Python transport validator with strict
  v3 request, response, model-output, result, retrieval-hit, diagnostic,
  ledger-processing, compaction, and stream-event contracts. Removed the old
  direct-answer strategies and stream event names. Added exact fingerprint,
  ID/length, rank, distance, query/message-pair, and one-result-per-range
  validation.
- Added focused contract assertions for required nullable assistance and exact
  window-plan payloads in `tests/test_sfv1_contracts.py`.
- Command:
  `.\.venv\Scripts\python.exe -m pytest -q --basetemp .tmp\rauc1-110-contracts2 tests\test_sfv1_contracts.py` — 5 passed.
- RAUC1-110 disposition: complete.
- Next dependency: RAUC1-120.

## 2026-07-29 — RAUC1-120 conversational retrieval-plan endpoint

- Added `POST /v1/conversational-retrieval-plan` to `server/app.py`, including
  normal product admission/debug/error/accounting handling, one configured
  `retrieval_terms` call, server-side term normalization, actual prepared
  embedding geometry, policy, and canonical compatibility fingerprint. The
  endpoint does not call embeddings or persist a plan.
- Added `RETRIEVAL_PLAN_EMPTY`, stale, and geometry error mappings; malformed
  model output remains a visible strict failure. Debug capture receives a
  `retrieval_plan_generated` record while normal logs remain content-free.
- Added `tests/test_sfv1_retrieval_assistance.py` endpoint coverage for ordered
  queries, normalization, empty output, malformed output, no embedding call,
  policy, geometry, and mode-independent/policy-sensitive fingerprints.
- Command:
  `.\.venv\Scripts\python.exe -m pytest -q --basetemp .tmp\rauc1-120-plan-tests tests\test_sfv1_retrieval_assistance.py` — 5 passed.
- RAUC1-120 disposition: complete.
- Next dependency: RAUC1-200.

## 2026-07-29 - RAUC1-200 multi-query local vector candidate workflow

- Extended the Python gateway with the strict JSON retrieval-plan call and
  made conversational analysis always send the required nullable
  `retrieval_assistance` field. Embedding streams now accept the existing
  cancellation handle.
- Extended `ConversationalWorkflow` to freeze the server plan, verify the
  selected EVW message-index readiness/geometry, submit every planned query in
  one embedding workload, validate returned profile/fingerprint/geometry,
  perform local message-level vector lookup within the narrowed selected
  revision, and attach deterministic one-based ranks. Candidate rows contain
  only `query_id`, `message_id`, `rank`, and `distance`; no body text or vector
  is sent.
- Added focused client tests covering one workload for all queries, candidate
  shape/order, and geometry failure before local search/analysis.
- Commands:
  `.\\.venv\\Scripts\\python.exe -m pytest -q --basetemp .tmp\\rauc1-200-client tests\\test_sfv1_retrieval_client.py tests\\test_sfv1_gateway.py` - 10 passed.
  `.\\.venv\\Scripts\\python.exe -m compileall -q message_evidence_workstation` - passed.
- RAUC1-200 disposition: complete.
- Next dependency: RAUC1-300.

## 2026-07-29 - RAUC1-300 unified extraction-ledger-synthesis orchestration

- Removed the runtime direct-answer branch and replaced it with one server
  path: retrieval-assistance validation, deterministic window planning, one
  `window_evidence_extraction` call per window, canonical ledger construction,
  direct synthesis preflight, loud hierarchical compaction when required, and
  `ledger_synthesis`.
- Added strict plan/config/profile/fingerprint/candidate validation, exact RRF
  candidate fusion, advisory adjacent-only suggestion ranges, stable window
  plan hashes, retrieval overlap diagnostics, and the final
  `single_window_ledger`/`multi_window_ledger` strategies.
- Added exact stream events for retrieval acceptance, suggestions, window
  plans, synthesis preflight, compaction progress, synthesis completion, and
  overlap diagnostics. The public `server.conversation` module now exposes the
  unified implementation without legacy runtime symbols.
- Removed the retired whole-ledger builder and extended final assembly with
  strict retrieval diagnostics and ledger-processing fields.
- Updated deterministic provider test equipment for the five-operation runtime
  and added a semantic one-window end-to-end stream test.
- Commands:
  `.\\.venv\\Scripts\\python.exe -m pytest -q --basetemp .tmp\\rauc1-300-gate tests\\test_sfv1_conversation_unified.py tests\\test_sfv1_contracts.py` - 6 passed.
  `python -m compileall -q server message_evidence_workstation` - passed.
  Static scan of `server` conversation/evidence runtime - no retired whole or
  reduction symbols.
- RAUC1-300 disposition: complete.
- Next dependency: RAUC1-310.

## 2026-07-29 - RAUC1-310 semantic fusion, suggestions, prompts, and overlap

- Replaced extraction prompt wording with the packet's full-window binding:
  retrieval queries/suggestions are non-exhaustive attention aids, may be
  rejected, and never justify omitting evidence outside suggestions.
- Added exact RRF fusion ordering (score, best distance, corpus ordinal,
  message ID), explicit selected/unselected accounting, adjacent-only
  per-window/thread suggestion ranges, and content-bearing debug-capture
  records for raw candidates, fusion decisions, and suggestion ranges. Normal
  event logs remain count-only.
- Added focused deterministic tests for RRF ordering and suggestion grouping.
- Command:
  `.\\.venv\\Scripts\\python.exe -m pytest -q --basetemp .tmp\\rauc1-310-fusion2 tests\\test_sfv1_semantic_fusion.py tests\\test_sfv1_conversation_unified.py` - 3 passed.
- RAUC1-310 disposition: complete.
- Next dependency: RAUC1-400.

## 2026-07-29 - RAUC1-400 ledger compaction and loud fallback

- Unified orchestration now performs exact synthesis preflight before any
  compaction, preserves original canonical ranges for final assembly, and
  emits required/group/level/completed compaction events with token and
  coverage accounting.
- Compaction triggers also produce a structured WARNING activity event; no
  fallback is silent. The final result reports compaction application, levels,
  and group calls.
- Command:
  `.\\.venv\\Scripts\\python.exe -m pytest -q --basetemp .tmp\\rauc1-400-compaction5 tests\\test_sfv1_conversation_unified.py -k compaction` - 1 passed.
- RAUC1-400 disposition: complete.
- Next dependency: RAUC1-500.

## 2026-07-29 - RAUC1-500 admin surface

- Removed the retired whole-corpus operation guide entry and changed the
  operation guide/sample payloads to the final five-operation vocabulary.
  Retrieval-term admin tests now use the strict retrieval-term output model;
  extraction samples expose ordered retrieval queries and suggestion ranges.
- Updated admin descriptions to describe unified extraction and explicit
  ledger compaction triggers. The admin/template legacy scan is clean and
  existing admin bootstrap tests remain green.
- Command:
  `.\\.venv\\Scripts\\python.exe -m pytest -q --basetemp .tmp\\rauc1-310-400-500 tests\\test_sfv1_semantic_fusion.py tests\\test_sfv1_conversation_unified.py tests\\test_sfv1_admin.py` - 11 passed.
  `python -m compileall -q server message_evidence_workstation` - passed.
- RAUC1-500 disposition: complete.
- Next dependency: RAUC1-600.

## 2026-07-29 - RAUC1-600 Python workflow and visible progress

- Completed the client-side linear workflow and cancellation boundary: the
  retrieval-plan JSON call can be cancelled, all query embeddings use one
  cancellable workload, local candidates are read only after network work is
  complete, and conversational analysis receives the strict assistance object.
- Updated GUI progress to expose the current phase (`retrieval_plan`, query
  embeddings, local candidates, and server phases) while retaining elapsed
  time, window counts, cancellation, and final visible-result persistence.
- Focused client/gateway command:
  `.\\.venv\\Scripts\\python.exe -m pytest -q --basetemp .tmp\\rauc1-600-client tests/test_sfv1_retrieval_client.py tests/test_sfv1_gateway.py` - 10 passed.
  `python -m compileall -q message_evidence_workstation server` - passed.
- RAUC1-600 disposition: complete.
- Next dependency: RAUC1-700.

## 2026-07-30 - RAUC1-700 regression, mixed-load, and scale validation

- Added the deterministic RAUC1-700 mixed-load harness and retrieval-experiment
  fixture coverage. The scale harness exercises concurrent retrieval plans,
  one embedding workload per query set, small and multi-window analyses,
  forced ledger compaction, admin projections, provider-call sequencing, and
  latency/accounting assertions.
- The final default test run was:
  `.\\.venv\\Scripts\\python.exe -m pytest -q --basetemp .tmp\\rauc1-final-regression`
  - 117 passed, 1 skipped, 2 deselected, 1 warning, 7.31 seconds.
- The explicit scale run was:
  `.\\.venv\\Scripts\\python.exe -m pytest -q --basetemp .tmp\\rauc1-final-scale tests\\test_sfv1_mixed_load.py -m scale`
  - 1 passed in 0.90 seconds.
- `compileall` across `server`, `message_evidence_workstation`, `scripts`,
  and `tests` passed. `scripts/verify_package_boundaries.py` passed.
- RAUC1-700 disposition: complete.
- Next dependency: RAUC1-800.

## 2026-07-30 - RAUC1-800 reproducible retrieval-hint investigation runner

- Added `scripts/run_retrieval_hint_experiment.py` with the packet-defined
  `prepare`, `run`, and `report` interface. It opens the EVW read-only, checks
  schema/revision/index/embedding geometry, freezes one server plan, performs
  one query-embedding workload, performs local message-level vector lookup,
  submits terms-only/full-semantic/censored-semantic arms, preserves exact
  request/result artifacts, and stops the debug capture during report.
- Added a bounded capture-writer drain after admin mode activation. This is a
  visible health wait for asynchronous debug records, not a retry of any
  network, provider, or model phase. Runner fixture tests passed:
  `.\\.venv\\Scripts\\python.exe -m pytest -q --basetemp .tmp\\rauc1-800-runner2 tests\\test_sfv1_retrieval_experiment.py`
  - 2 passed in 0.14 seconds.
- Prepared investigation directory:
  `.tmp\\retrieval-hint-experiment\\20260729T232500Z`.
  The frozen plan is `8e4e6e84-bc07-4ba0-b423-a854e743b9a1`, with queries
  `fight` and `school`, a 384-dimensional `unit_l2` embedding profile, rev4
  (12,402 messages), and one embedding workload. The small rev3 smoke corpus
  has 1,387 messages and 99,980 estimated tokens.
- Full-semantic live arm completed in 613,628.5 ms:
  `multi_window_ledger`, six windows, 74 ledger ranges, 7/7 provisional-gold
  recall, 69 final ranges outside suggestion ranges, 18 used ranges outside
  suggestions, no compaction, and window-plan hash
  `f9684a8ad9a3e69aaed24db10496a7987211602901a894a5abc65cdd220d7660`.
- Terms-only and censored-semantic each completed one six-window run and were
  preserved as partial results after strict `LEDGER_BIJECTION_FAILED` model
  evidence coverage failures. Neither arm was retried.
- RAUC1-800 disposition: complete.
- Next dependency: RAUC1-900.

## 2026-07-30 - RAUC1-900 live gate, documentation, and closeout

- Restarted the current source server on `127.0.0.1:8710` after the power
  interruption, preserving prior process/capture history and the two empty
  interrupted run directories. The live runner created capture session
  `20260730T002011Z-7cc97e5aa5ed` and recorded its path through `/admin/events`.
- The required 100K one-window smoke reached the provider and produced one
  extraction window in 18,688.4 ms, then failed loudly with non-retryable
  `LEDGER_BIJECTION_FAILED` because the returned evidence did not satisfy the
  strict ledger contract. No permissive repair or fallback was applied.
- All three permitted diagnostic arms were run once on the same frozen plan.
  Full-semantic succeeded; terms-only and censored-semantic remained partial
  with the same strict provider-output contract failure. The raw pool did
  overlap provisional positives, so censored-semantic was eligible.
- `report` wrote `comparison.json` and `comparison.md`, marked the comparison
  invalid because two arms were partial, and stopped the capture. Final
  `/admin/events` state had no active capture, no pending records, no writer
  failure, active config v20, and semantic retrieval-assistance mode.
- The live investigation artifacts are under
  `.tmp\\retrieval-hint-experiment\\20260729T232500Z`; the latest capture is
  `C:\\Users\\artwh\\.message_evidence_server\\debug-captures\\20260730T002011Z-7cc97e5aa5ed.jsonl`.
  The read-only EVW fixture was recorded at 91,516,928 bytes with SHA-256
  `06d5d25cca193f2edb389e3ec219bf42a79f8b1cd780f166dcfff6a6a07817dc`.
- Product route and legacy scans passed: exactly four `/v1` POST routes;
  retired whole-corpus/reduction names remain only in explicit v2 migration
  compatibility code, not runtime orchestration.
- Created `closeout_report.md` with ticket dispositions, gate evidence, live
  artifact paths, preserved-scope notes, and the provider-contract blocker.
- RAUC1-900 disposition: complete with a documented external live-provider
  contract limitation. Local implementation gates are green; the live
  apples-to-apples quality comparison is not claimed valid.
