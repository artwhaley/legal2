# Result-Preserving Validation V1 Execution Log

The executor appends dated entries after every ticket.

For each entry record:

- ticket;
- inspected baseline and overlapping user changes;
- files changed/deleted;
- architectural decisions applied from the packet;
- exact commands and results;
- failures found and fixed;
- residue scan;
- remaining dependency/blocker;
- process/config/debug/fixture state where relevant.

Do not claim success without command evidence. Do not include secrets or private
transcript content.

## 2026-07-30 — RPV1-000 baseline and authority inventory

- Packet authority: read `AGENTS.md` completely and read packet documents
  `00_mission_and_invariants.md` through `11_executor_protocol.md`, then
  `kickoff_prompt.md`, in the README-prescribed order before editing.
- Repository baseline: branch `main`, `HEAD`
  `90735c297d14370aa8e98d857ee5c19df8ced124`, upstream `origin/main`.
  `git status --short` reported 440 entries: 19 modified, 158 deleted, and
  263 untracked. The worktree contains extensive pre-existing QPA/SFV1,
  Flutter, EVW, server, client, test, and `.tmp` work; it is preserved as-is.
  Every expected RPV1 contact is either pre-existing untracked packet-era work
  or the already modified Python UI file; no clean baseline is assumed.
- No project Python/uvicorn/Flutter/Dart process was running and no listener
  was found on ports 8000, 8001, 8710, 8787, 3000, 5000, or 8080.
- Read-only control-store inventory: `C:\Users\artwh\.message_evidence_server\control.sqlite3`,
  schema 4, active config version 64, draft version 65, one redacted provider
  account, and 65 encrypted secret/binding rows. Active operations are the
  required five (`keyword_expansion`, `analysis_planning`,
  `window_evidence_extraction`, `ledger_compaction`, `ledger_synthesis`), all
  assigned to redacted `z-ai/glm-5.2` profile details, with JSON-schema mode,
  3 attempts, 1200-second operation deadlines, and 16,384 output tokens.
  Active global settings include semantic-range retrieval, 90% window
  utilization, one concurrent window, and MiniLM all-MiniLM-L6-v2 / 384 /
  unit_l2 embeddings. Active v64 still contains obsolete synthesis prompt
  literals; v65 is an unactivated draft with the same obsolete synthesis
  prompt. No secrets were read or emitted.
- Product POST route inventory: exactly `/v1/keyword-expansion`,
  `/v1/conversational-plan`, `/v1/conversational-analysis`, and `/v1/embeddings`.
- Current active implementation inventory: strict `LedgerSynthesisOutput`
  plus post-synthesis disposition/finding validation in
  `server/evidence_ledger.py` and `server/conversation_unified.py`; strict
  stream/public result contracts in `server/contracts.py`; old synthesis
  prompt in `server/prompts.py`; window validation in
  `validate_window_evidence`; ordinary window task failures currently escape
  the batch; compaction/synthesis publication remains coupled to the old
  all-or-nothing path; Python gateway/UI and both diagnostic scripts still
  consume the old result shape. Baseline residue counts in active `.py` paths:
  `direct_evidence` 23, `useful_context` 12, `not_responsive` 14,
  `range_dispositions` 9, `validate_dispositions` 7,
  `validate_findings` 6, `partial_evidence_validation` 8, and
  `LEDGER_BIJECTION_FAILED` 4.
- Latest known GLM diagnostic blocker from the prior packet is preserved for
  context only: request `8292bfbc-f27e-4cab-ae26-2819226563c8`, provider
  timeout (`PROVIDER_TIMEOUT`, non-retryable, operation deadline expired)
  after 9/9 extraction windows, with debug capture
  `C:\Users\artwh\.message_evidence_server\debug-captures\20260730T052325Z-6666d201bdcd.jsonl`.
- Required baseline gates:
  - `\.venv\Scripts\python.exe -m compileall -q server message_evidence_workstation scripts tests` — exit 0.
  - `\.venv\Scripts\python.exe -m pytest -q` — all displayed tests reached
    completion, but pytest exited 1 during its Windows temp cleanup because a
    stale locked `C:\Users\artwh\AppData\Local\Temp\pytest-of-artwh\pytest-current`
    reparse point raised `PermissionError: [WinError 5]`; this is an
    environment cleanup issue, not a reported test failure. A project-local
    basetemp rerun is required to establish a clean baseline gate.
  - `\.venv\Scripts\python.exe scripts\verify_package_boundaries.py` —
    `package boundaries: PASS`, exit 0.
  - `git diff --check` — exit 0 (existing LF/CRLF warnings only).
- Clean baseline confirmation: `\.venv\Scripts\python.exe -m pytest -q
  --basetemp .tmp\rpv1-000-basetemp` — `160 passed, 2 deselected, 1 warning`
  in 12.50s, exit 0. The baseline temp directory is a new packet artifact;
  no source, EVW, or control-store file was intentionally changed.
- RPV1-000 gate: complete. No destructive ambiguity or external blocker was
  found. RPV1-100 may begin.

## 2026-07-30 — RPV1-100 contracts, prompts, and stored-config migration

- Inspected the pre-existing server contracts, prompt registry, config-store
  migration path, admin schema exposure, and current tests before editing.
- Changed `server/contracts.py`, `server/prompts.py`, `server/config.py`, and
  `server/config_store.py`. The public result now carries completion status,
  answer source, structured/raw/unavailable synthesis fields, warning records,
  source-validated ledger metadata, and the new stream event set. The stored
  known seeded synthesis prompt is migrated in place without changing schema,
  version identity, assignments, secrets, or binding rows. Custom incompatible
  prompts remain rejected at validation with an explicit update action.
- Added/updated contract and migration tests in `tests/test_qpa1_contracts.py`
  and `tests/test_qpa1_config.py`.
- Command/result: `\.venv\Scripts\python.exe -m pytest -q --basetemp
  .tmp\rpv1-contract-basetemp tests\test_qpa1_contracts.py
  tests\test_qpa1_config.py` — `15 passed`.
- Command/result: `\.venv\Scripts\python.exe -m compileall -q server
  message_evidence_workstation scripts tests` — exit 0.
- Residue scan at this point found legacy client/script/test consumers still
  pending under RPV1-700; no runtime decision was hidden or silently migrated.
- RPV1-100 gate: complete. RPV1-200 may begin.

## 2026-07-30 — RPV1-200 result-preserving synthesis inspection

- Inspected the old all-or-nothing synthesis assembly and its tests before
  replacing it with `server/result_validation.py`.
- Implemented exact JSON/fenced JSON inspection, deterministic normalization
  only where packet-authorized, raw readable-output preservation, independent
  result/citation handling, high-before-lower ordering, omitted ledger-range
  preservation, all-unverified isolation, and ledger-only unavailable output.
  No fabricated source enters the verified ledger.
- Changed `server/model_runtime.py` with a narrow raw-output and targeted
  machine-unusable retry extension; ordinary strict operations remain strict.
- Command/result: `\.venv\Scripts\python.exe -m pytest -q --basetemp
  .tmp\rpv1-synthesis-basetemp tests\test_qpa1_synthesis.py` — `15 passed`.
- Command/result: `\.venv\Scripts\python.exe -m pytest -q --basetemp
  .tmp\rpv1-synthesis-integration-basetemp tests\test_sfv1_conversation_hardening.py
  tests\test_qpa1_synthesis.py` — focused result-preserving tests passed after
  updating one stale expectation to the warning-bearing raw contract.
- RPV1-200 gate: complete. RPV1-300 may begin.

## 2026-07-30 — RPV1-300 source-integrity range salvage

- Replaced extraction envelope rejection with independent range salvage in
  `server/evidence_ledger.py`. Valid siblings survive; source thread identity
  is derived from supplied messages; deterministic endpoint reversal and thread
  correction are annotated; unknown, cross-thread, duplicate, and ambiguous
  candidates are diagnosed without discarding readable siblings. Parseable
  all-invalid windows remain usable; unusable top-level output is distinct.
- Added range-salvage coverage in `tests/test_qpa1_range_validation.py` and
  updated supporting fixtures/debug capture fields.
- Command/result: `\.venv\Scripts\python.exe -m pytest -q --basetemp
  .tmp\rpv1-range-basetemp tests\test_qpa1_range_validation.py
  tests\test_qpa1_synthesis.py tests\test_sfv1_evidence_ledger.py` — `29 passed`.
- RPV1-300 gate: complete. RPV1-400 may begin.

## 2026-07-30 — RPV1-400 window isolation and retry ownership

- Changed `server/conversation_unified.py` to return typed per-window outcomes,
  preserve sibling results, keep deterministic window order, emit unusable and
  unavailable diagnostics, include unavailable windows in coverage, and hard
  fail only when no usable extraction output exists after configured attempts.
- Added targeted window/synthesis retry behavior through shared model runtime;
  retries remain visible and usage-accounted. Updated Python workflow progress
  to count unavailable windows as terminal window outcomes and display their
  warnings.
- Command/result: `\.venv\Scripts\python.exe -m pytest -q --basetemp
  .tmp\rpv1-orchestration-basetemp tests\test_qpa1_orchestration.py
  tests\test_sfv1_conversation_unified.py tests\test_sfv1_mixed_load.py` —
  passed after the stale status assertion was updated to `partial`.
- Additional targeted retry/isolation coverage is retained in the orchestration
  and hardening tests; no source, corpus, or provider fallback was introduced.
- RPV1-400 gate: complete. RPV1-500 may begin.

## 2026-07-30 — RPV1-500 synthesis and compaction preservation

- Changed synthesis orchestration to emit receipt before validation, return
  readable nonconforming output successfully, retry only machine-unusable
  synthesis, and return a partial ledger-only terminal result after exhausted
  synthesis attempts.
- Compaction now uses targeted machine-unusable group retry. Any exhausted
  compaction/provider or coverage-integrity failure preserves the canonical
  ledger, emits `COMPACTION_UNAVAILABLE` and `SYNTHESIS_UNAVAILABLE`, and never
  submits incomplete compacted material.
- Added explicit hardening tests for compaction failure preservation and
  group-only retry in `tests/test_sfv1_conversation_hardening.py`; both passed.
- Command/result: `\.venv\Scripts\python.exe -m pytest -q --basetemp
  .tmp\rpv1-compaction-basetemp3 tests\test_sfv1_conversation_hardening.py::test_compaction_failure_returns_original_ledger_only_result
  tests\test_sfv1_conversation_hardening.py::test_empty_compaction_output_retries_only_the_group` — `2 passed`.
- RPV1-500 gate: complete. RPV1-600 may begin.

## 2026-07-30 — RPV1-600 prompts, admin, and observability

- Updated the admin synthetic synthesis payload and guidance to expose the new
  evidence-validation summary and result behavior. Admin schema display remains
  driven by the exact server Pydantic schema.
- Added content-free completion-status and warning metrics to
  `server/observability.py`; result warnings and terminal status are logged by
  code/status only. No corpus text, raw synthesis, or secrets enter ordinary
  logs.
- Command/result: admin, resilience, hardening, mixed-load, and runner tests
  were exercised with project-local basetemps; the final combined result is
  recorded under RPV1-800 after the last fixture expectation repair.
- RPV1-600 gate: complete. RPV1-700 may begin.

## 2026-07-30 — RPV1-700 Python client and diagnostic runners

- Reworked `message_evidence_workstation/client_api/contracts.py` to validate
  the new result fields, citation partitions, warning codes, coverage counts,
  evidence diagnostics, synthesis events, and endpoint-specific stream events.
  Removed the old terminal event/result contract from the client.
- Updated client progress/UI/persistence to show high/lower/unclassified and
  warning/partial outcomes, preserve readable overview/raw output, persist only
  source-validated ledger citations, and keep unavailable-window progress visible.
- Updated `scripts/run_question_planned_analysis_live.py` and
  `scripts/run_retrieval_hint_experiment.py` to emit the new result sections and
  RPV1 live artifact wording without legacy contract literals.
- Command/result: `\.venv\Scripts\python.exe -m pytest -q --basetemp
  .tmp\rpv1-client-contract-basetemp2 tests\test_sfv1_contracts.py
  tests\test_sfv1_retrieval_client.py tests\test_qpa1_synthesis.py
  tests\test_sfv1_conversation_hardening.py` — `31 passed, 1 warning`.
- RPV1-700 gate: complete. RPV1-800 may begin.

## 2026-07-30 — RPV1-800 deterministic regression and cleanup gates

- Final project-local regression: `\.venv\Scripts\python.exe -m pytest -q
  --basetemp .tmp\rpv1-800-final-basetemp` — `172 passed, 2 deselected,
  1 warning` in 12.74s, exit 0.
- Explicit scale gate: `\.venv\Scripts\python.exe -m pytest -q -m scale
  --basetemp .tmp\rpv1-800-scale-basetemp` — `2 passed`.
- Explicit browser gate: `\.venv\Scripts\python.exe -m pytest -q -m browser
  --basetemp .tmp\rpv1-800-browser-basetemp` — `1 passed`.
- `\.venv\Scripts\python.exe -m compileall -q server
  message_evidence_workstation scripts tests` — PASS. Package boundaries —
  PASS. `git diff --check` — PASS with pre-existing LF/CRLF conversion
  warnings only.
- Forbidden active-residue scan over server, Python client, scripts, and tests
  returned `NONE` for all eight packet-prohibited literals.
- Final fixture/process preflight remains pending for RPV1-900; no live model
  request has been made in this gate.
- RPV1-800 gate: complete. RPV1-900 is the only remaining dependency.

## 2026-07-30 — RPV1-900 live proof and cleanup

- Final live preflight verified active version 64/draft 65 before the run,
  schema 4, semantic retrieval, 90% normal utilization, 384-dimensional
  unit-L2 embeddings, all five operations on GLM 5.2 with JSON-schema mode,
  three attempts, 1200-second deadlines, 16,384 output tokens, and all five
  active prompts equal to the packet defaults. The revision-4 EVW fixture was
  readable and embedding-ready. No API keys were emitted.
- Started the project server with the project `.venv` interpreter and ran
  exactly one ordinary public flow using the exact question `Show me fights
  about school.`. No full-sequence rerun, provider/model change, hand repair,
  or private synthesis helper was used.
- Live artifact directory:
  `.tmp/result-preserving-validation-live/20260730T193650Z-23cc0595/`.
  It contains the redacted manifest, exact plan, retrieval metadata, window
  and synthesis summary, final result, Markdown report, and debug-capture
  path. Manifest artifact hashes were independently rechecked.
- Live outcome: terminal `completed`, `complete_with_warnings`,
  `structured_synthesis`; 9 planned and usable windows, 0 unavailable
  windows, 87 ledger ranges, 29 classified results (11 high-probability and
  18 lower-probability), 13 unclassified ranges, 0 unverified statements,
  one natural compaction level with one group call, and 13 synthesis warnings
  consisting of omitted-ledger-range annotations. Every verified citation
  maps to a canonical ledger range; the Markdown report includes the visible
  high/lower divider, unclassified and unverified sections, warnings, ledger,
  usage, and timing.
- Debug capture `C:\Users\artwh\.message_evidence_server\debug-captures\20260730T193656Z-1436799e94c5.jsonl`
  was stopped and flushed. Temporary 60% utilization was restored through
  normal activation: active version 66, draft version 67, utilization 90%,
  schema 4, all five prompts current. Project server processes and scoped
  listeners are stopped/absent. An unrelated user-owned VLC listener on 8080
  was observed and left untouched.
- Final command/result: `\.venv\Scripts\python.exe -m pytest -q
  --basetemp .tmp\rpv1-final-basetemp` — `172 passed, 2 deselected,
  1 warning` in 12.67s. Compileall PASS, package boundaries PASS,
  `git diff --check` PASS, forbidden active-residue scan NONE.
- RPV1-900 gate: complete. No external blocker remains. All packet tickets
  RPV1-000 through RPV1-900 are dispositioned.

## 2026-07-30 - Post-closeout deficiency correction

- Audited the completed packet against its result-preservation contract and
  corrected eight concrete gaps: synthesis transport failure discarded the
  ledger; queue/circuit failures escaped per-window isolation; long fabricated
  IDs could invalidate an otherwise readable answer; extraction warnings and
  uncertainties were absent from the public ledger; no-result behavior was
  ambiguous; safe compaction ID reordering was rejected; stream diagnostics
  mislabeled failures; and the Python test client displayed/persisted an
  incomplete representation of the result.
- Updated only the server contract/runtime, admin help, and temporary Python
  test-client surfaces necessary to close those gaps. No architecture redesign,
  provider change, live call, embedding rebuild, or EVW schema migration was
  performed.
- Final project-local regression with a unique workspace temp root:
  `183 passed, 2 deselected, 1 warning`, exit 0.
- Explicit scale gate: `2 passed`. Explicit browser gate: `1 passed`.
- Compileall PASS, package boundaries PASS, `git diff --check` PASS with
  line-ending conversion warnings only, forbidden active-residue scan NONE.
