# QPA1 execution log

The execution agent owns this file.

## 2026-07-30 - Post-executor contract remediation

- Replaced incompatible v2/v3 extraction, compaction, and synthesis prompts at
  migration while preserving all non-prompt settings and secrets.
- Activated current defaults for all five live operations as config version 62;
  non-prompt settings remain identical to version 61.
- Unified the duplicate `/admin/events` routes into one complete projection.
- Made non-object ranges reach independent `RANGE_NOT_OBJECT` quarantine.
- Enforced range bounds, direct-evidence findings, validation-count
  consistency, and selective plan compatibility.
- Added production-path regressions for every defect.
- Final checks: 51 focused passed; real browser 1 passed; full suite 160 passed
  with 2 scale tests deselected; explicit scale 1 passed; compile, package
  boundaries, and diff checks passed.
- No live provider call or embedding rebuild was performed.

Append one dated section for baseline and for every ticket. Record:

- ticket and status;
- inspected contacts and preserved overlapping user changes;
- implementation files;
- deleted obsolete contacts;
- exact commands, results, counts, and timings;
- failures found and corrected;
- remaining dependency or genuine blocker;
- process/debug-capture state where relevant.

Do not include secrets, corpus text, complete prompts, or provider response
content here. Store authorized exact content only in temporary debug/diagnostic
artifacts and link their paths.

## 2026-07-30 - QPA1-000 baseline and contact-surface inventory

- Read `AGENTS.md` and every QPA packet file in the README-defined order before
  editing. The QPA packet supersedes the prior RAUC1 v3 planning, endpoint,
  extraction, disposition, and result requirements while preserving the server,
  stateless EVW boundary, local vector lookup, window packing, compaction,
  retry/cancellation, accounting, and debug-capture foundations.
- Git baseline: branch `main`; HEAD
  `90735c297d14370aa8e98d857ee5c19df8ced124`; upstream `origin/main`; ahead /
  behind `0 / 0`.
- Dirty worktree baseline: 402 entries — 19 modified, 225 added/untracked,
  158 deleted, 0 renamed. Broad overlapping user work includes the current
  `server/` surface, 93 test entries, 10 script entries, 108
  `message_evidence_workstation` entries, `.tmp` artifacts, README,
  `pyproject.toml`, and one Flutter entry. These changes were preserved.
  Expected QPA contacts are already within these dirty surfaces; no reset,
  clean, checkout, rewrite, commit, push, or deploy was performed.
- No server, diagnostic runner, pytest, or Python-client process was running;
  ports 8710 and 8711 had no listeners. The last live RAUC1 capture and all
  prior capture files remain preserved; no capture was active at baseline.
- Control store: `C:\Users\artwh\.message_evidence_server\control.sqlite3`,
  control schema 3, active config version 59, draft absent. Active product
  config schema is v3 with global retrieval mode `semantic_ranges`, top-k 100,
  maximum suggestion messages 40, and 90% window utilization. All five active
  operation assignments use the existing configured model profile
  `model-7ac4caef076e`; no secret values were read or printed.
- Current product POST routes (4): `/v1/keyword-expansion`,
  `/v1/conversational-retrieval-plan`, `/v1/conversational-analysis`, and
  `/v1/embeddings`.
- Current v3 runtime contacts include `retrieval_terms`,
  `retrieval_plan_id`, `retrieval_assistance`, `terms_only`, and
  `retrieval_assistance_accepted` across `server/app.py`,
  `server/contracts.py`, `server/config.py`, `server/prompts.py`,
  `server/conversation_unified.py`, the Python gateway/workflow, and current
  tests. These are the intended QPA migration/deletion contacts, not preserved
  runtime compatibility.
- Baseline commands:
  `.\\.venv\\Scripts\\python.exe -m compileall -q server message_evidence_workstation scripts tests`
  — passed;
  `.\\.venv\\Scripts\\python.exe -m pytest -q --basetemp .tmp\\qpa1-baseline`
  — 122 passed, 1 skipped, 2 deselected, 1 warning in 6.85 seconds;
  `.\\.venv\\Scripts\\python.exe -m pytest -q --basetemp .tmp\\qpa1-baseline-focused tests\\test_sfv1_contracts.py tests\\test_sfv1_control_store.py tests\\test_sfv1_conversation_unified.py tests\\test_sfv1_retrieval_assistance.py tests\\test_sfv1_retrieval_client.py tests\\test_sfv1_evidence_ledger.py`
  — 34 passed, 1 warning in 1.84 seconds.
- Preserved diagnostic artifacts include
  `.tmp\\six-window-model-comparison\\20260729T031230Z` (6 files) and
  `.tmp\\retrieval-hint-experiment\\20260729T232500Z` (18 files). No artifact
  content or corpus text was copied into this log.
- QPA1-000 disposition: complete. Next dependency: QPA1-100.

## 2026-07-30 - QPA1-100 configuration v4 and strict contract foundation

- `server/config.py` now defines schema v4, the final five operations with
  `analysis_planning`, and retrieval mode `none|semantic_ranges`. The explicit
  v3-to-v4 migration preserves non-prompt operation settings, maps legacy mode
  values, renames the planning assignment, and replaces the incompatible
  planner prompt.
- `server/config_store.py` now atomically migrates stored v3 payloads and
  records one content-free `config_schema_v4_migration` audit entry. The live
  control store migrated from control schema 3 to 4 and active payload schema 4;
  no secrets were printed or changed.
- `server/prompts.py` now seeds generic analysis planning, plan-oriented
  extraction, disposition-free compaction, and finding/disposition synthesis.
  The planning seed contains no diagnostic school/fight language.
- Replaced `server/contracts.py` with strict v4 plan, context, extraction
  envelope, validation diagnostic, findings/disposition, compaction, result,
  and stream contracts. `WindowEvidenceEnvelope` keeps the envelope strict
  while intentionally leaving individual range objects for the QPA-500 parser.
- Added `tests/test_qpa1_contracts.py` and `tests/test_qpa1_config.py` covering
  exact planning bounds/fields, mode/embedding invariants, range-envelope
  strictness, disposition/finding shapes, compaction output, v3 migration,
  operation/settings preservation, and control-store schema behavior.
- Command:
  `.\\.venv\\Scripts\\python.exe -m pytest -q --basetemp .tmp\\qpa1-100-contracts tests\\test_qpa1_contracts.py tests\\test_qpa1_config.py`
  — 9 passed in 0.27 seconds.
- QPA1-100 disposition: complete. Next dependency: QPA1-200.

## 2026-07-30 - QPA1-200 analysis-planning endpoint

- Replaced the old retrieval-term endpoint in `server/app.py` with
  `POST /v1/conversational-plan`. It performs exactly one server-owned
  `analysis_planning` operation, validates the complete plan, assigns ordered
  `q0001` query IDs, resolves `none|semantic_ranges`, reports nullable/actual
  embedding metadata, and computes the v4 compatibility fingerprint.
- The product admission route set now names `/v1/conversational-plan`; the old
  `/v1/conversational-retrieval-plan` route is deleted rather than aliased.
- Admin model/operation contacts were updated enough for the v4 planner and
  strict contracts to load; full admin vocabulary is completed in QPA1-700.
- Added `tests/test_qpa1_analysis_plan.py` covering one planner call, generic
  frozen-plan response, no embedding preparation in `none`, actual semantic
  geometry, old-route 404, malformed output failure, and fingerprint change.
- Command:
  `.\\.venv\\Scripts\\python.exe -m pytest -q --basetemp .tmp\\qpa1-200-plan tests\\test_qpa1_analysis_plan.py`
  — 5 passed, 1 warning in 0.74 seconds.
- QPA1-200 disposition: complete. Next dependency: QPA1-300.
## QPA1-300 - Dumb-client plan execution

- Replaced the Python client planning contract with strict v4 validation for
  the complete `analysis_plan`, ordered `retrieval_queries`, mode policy,
  embedding metadata, and usage.
- Renamed the gateway to `/v1/conversational-plan` and made
  `analysis_context` required for conversational analysis.
- The workflow now passes the server plan through unchanged. `none` performs
  no EVW read, embedding request, or local lookup. `semantic_ranges` performs
  one query-embedding workload and exact selected-revision message lookup,
  returning only query ID, message ID, rank, and distance in hits.
- Preserved cancellation/progress boundaries and validated the final context
  before submission.
- Updated the Python client progress label to analysis planning.
- Verification:
  - `.venv\\Scripts\\python.exe -m compileall -q server message_evidence_workstation`
  - `.venv\\Scripts\\python.exe -m pytest -q --basetemp .tmp\\qpa1-300-client tests\\test_sfv1_retrieval_client.py tests\\test_qpa1_contracts.py tests\\test_qpa1_analysis_plan.py`
- Result: 13 passed, 1 warning.

## 2026-07-30 - QPA1-400 frozen-plan orchestration

- `server/conversation_unified.py` now requires the strict frozen
  `analysis_context`, validates config version, compatibility fingerprint,
  exact plan/query/policy identity, semantic geometry, message IDs, and hit
  ranks before model work. The complete plan is injected into every extraction,
  compaction, and synthesis payload; the client cannot alter it.
- The unified path handles one-window and many-window workloads through the same
  planner, preserves immutable request snapshots, emits
  `analysis_plan_accepted`, and keeps retrieval suggestions advisory rather than
  prefiltering corpus windows. Per-window outputs are independently validated
  before ledger construction.
- Added/updated orchestration and converted SFV conversation hardening tests;
  the partial-range integration test confirms a malformed sibling does not
  discard a valid range and terminal status remains explicit.
- Verification: focused orchestration/contract/client/runner command later
  passed 24 tests; the final deterministic suite passed 146 tests, 1 skipped,
  2 deselected, 1 warning.
- QPA1-400 disposition: complete. Next dependency: QPA1-500.

## 2026-07-30 - QPA1-500 independent range validation

- `server/evidence_ledger.py` now validates each supplied range independently
  against the exact window message set. It rejects unknown endpoints,
  cross-thread and noncontiguous ranges, duplicates, wrong/missing/extra range
  fields, and malformed objects with stable ordered diagnostics.
- The only normalization is a provably reversed valid endpoint pair within one
  thread; accepted records carry normalization metadata. Rejected ranges never
  receive canonical IDs and never enter the ledger, compaction, findings, or
  overlap diagnostics.
- Added 9 focused range tests plus end-to-end partial completion coverage.
  The local MiniMax-shaped fixture proves accepted siblings survive, rejected
  diagnostics preserve supplied IDs without transcript text, and the completed
  result uses `partial_evidence_validation`.
- QPA1-500 disposition: complete. Next dependency: QPA1-600.

## 2026-07-30 - QPA1-600 synthesis and findings

- `server/prompts.py`, `server/contracts.py`, `server/evidence_ledger.py`, and
  `server/conversation_unified.py` now use categorical dispositions exactly
  `direct_evidence`, `useful_context`, and `not_responsive`. Findings must cite
  existing IDs and at least one direct-evidence range; compaction carries no
  dispositions and final synthesis alone classifies relevance.
- Synthesis receives the full validated plan, validation summary, complete
  accepted ledger metadata including window/source index/normalizations, and
  compaction summaries without reconstructing the plan. The final result keeps
  complete/partial status agreement and renamed answer-relevance diagnostics.
- Added focused synthesis/contract coverage; final suite remained 146 passed,
  1 skipped, 2 deselected, 1 warning.
- QPA1-600 disposition: complete. Next dependency: QPA1-700.

## 2026-07-30 - QPA1-700 admin and Python result display

- `server/admin.py`, `server/templates/admin.html`, and
  `server/observability.py` expose the v4 five-operation inventory, plan and
  validation schemas, categorical result fields, content-free accepted/
  rejected/normalized totals, and visible partial-validation status.
- `message_evidence_workstation/client_api/contracts.py`, `gateway.py`,
  `services/client_workflows.py`, and the result/progress UI now validate and
  echo the server plan without creating policy, execute semantic lookup only
  when instructed, require `analysis_context`, and visibly label partial
  evidence validation. No EVW write or Flutter change was made.
- Admin focused verification passed 7 tests with 1 intentional skip; client,
  browser, persistence, and result-display coverage passed in the final suite.
- QPA1-700 disposition: complete. Next dependency: QPA1-800.

## 2026-07-30 - QPA1-800 regression, boundaries, and mixed load

- Updated `scripts/run_retrieval_hint_experiment.py` and its tests to the v4
  plan/context route, final modes, final result diagnostics, and semantic-only
  diagnostic arms. No second product workflow or v3 terms-only path remains.
- Replaced the deselected mixed-load fixture with a QPA v4 scale test covering
  concurrent planning, one query-embedding workload per plan, local candidate
  lookup, one-window and multi-window analysis, complete and partial range
  results, forced compaction, admin reads, configured concurrency bounds, and
  cancellation. Explicit scale command: 1 passed in 0.74 seconds.
- `scripts/verify_package_boundaries.py` now checks exactly four product POST
  routes and scans current server/client runtime for forbidden v3 residue while
  leaving explicit migration code/tests documented. It reported `package
  boundaries: PASS`.
- Final local QPA gates passed:
  - `.venv\\Scripts\\python.exe -m compileall -q server message_evidence_workstation scripts tests`;
  - `.venv\\Scripts\\python.exe -m pytest -q --basetemp .tmp\\qpa1-final-regression`
    — 146 passed, 1 skipped, 2 deselected, 1 warning in 4.64 seconds;
  - `.venv\\Scripts\\python.exe -m pytest -q -m scale --basetemp
    .tmp\\qpa1-final-scale tests\\test_sfv1_mixed_load.py` — 1 passed in
    0.74 seconds;
  - `scripts\\verify_package_boundaries.py` — PASS;
  - `git diff --check` — PASS (only existing Git line-ending warnings).
- QPA1-800 disposition: complete. Next dependency: QPA1-900.

## 2026-07-30 - QPA1-900 live validation and closeout

- Live preconditions were verified without printing secrets: active control
  schema 4/config schema 4; config 59 before the run; all five operations
  assigned to `z-ai/glm-5.2`; semantic mode; revision 4 of
  `.tmp\\sfv1-fixture-multicorpus-v15.evw`; 12,402 messages; 384-dimensional
  unit-L2 local embedding geometry; no unrelated request or capture active.
- The corpus preflight estimated 720,646 transcript tokens and only 4.33
  windows at the active 90% utilization. Following file 09, only window
  utilization was temporarily lowered to 60% through admin save/validate/
  activate, creating config 60. The one authorized run used the exact question
  `Show me fights about school.`, one plan, one query-embedding workload, one
  exact local lookup, and one analysis request.
- The run planned and completed all 9 extraction windows. All 9 windows had
  accepted ranges and complete local validation with zero rejected and zero
  normalized ranges. Synthesis then entered the configured GLM call but did not
  return before its 1,200-second operation deadline. Exact terminal blocker:
  request `8292bfbc-f27e-4cab-ae26-2819226563c8`, code
  `PROVIDER_TIMEOUT`, message `operation deadline expired`, stage `provider`,
  retryable `false`, with 9 completed windows.
- No answer, final ledger, findings, or dispositions are claimed from the live
  run. The preserved live artifacts are under
  `.tmp\\question-planned-analysis-live\\20260730T052319Z-416dcfc9`; the exact
  debug capture is
  `C:\\Users\\artwh\\.message_evidence_server\\debug-captures\\20260730T052325Z-6666d201bdcd.jsonl`.
- Cleanup succeeded: capture stopped and flushed with zero bound requests;
  config 61 restored utilization to 90%; semantic mode and the five v4
  operations remained active; the server process was stopped and port 8710 was
  clear. The revision-4 EVW remained read-only; final hash was
  `06D5D25CCA193F2EDB389E3EC219BF42A79F8B1CD780F166DCFFF6A6A07817DC`, size
  91,516,928 bytes, with unchanged recorded EVW timestamps/sidecars.
- The final deterministic regression, compile, scale, boundary, and diff
  checks were rerun after live cleanup and passed as recorded in QPA1-800.
- QPA1-900 disposition: complete with the sole external live blocker
  documented. No provider fallback, automatic rerun, tuning rerun, or invented
  live quality result was performed.
