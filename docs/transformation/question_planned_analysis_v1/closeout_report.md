# QPA1 closeout report

Date: 2026-07-30  
Repository: `C:\Users\artwh\OneDrive\Documents\legal2`  
Packet: `docs/transformation/question_planned_analysis_v1`

## Post-executor audit and remediation

The executor handoff was independently audited after this report was first
written. The audit found and repaired seven concrete defects:

- active config 61 still carried obsolete extraction, compaction, and synthesis
  prompts despite the v4 source contracts;
- `GET /admin/events` was registered twice and the real dashboard received the
  obsolete, incomplete projection;
- a non-object range element failed the complete provider response before
  range-level quarantine;
- direct evidence did not require at least one structured finding;
- an unrelated active config version change incorrectly invalidated an
  otherwise compatible frozen plan;
- range-level strings were not bounded;
- evidence-validation counts and statuses were not cross-validated.

The corrected prompts were saved and activated through the normal control-store
path as config version 62. All five active operation prompts now exactly match
the current source defaults; every non-prompt setting is unchanged from version
61. The current active configuration passes complete startup validation.

Post-remediation deterministic results:

```text
focused defect regressions: 51 passed
real Playwright admin browser test: 1 passed
complete default suite: 160 passed, 2 deselected
explicit scale suite: 1 passed
compileall: PASS
package boundaries: PASS
git diff --check: PASS (line-ending warnings only)
```

No provider call or embedding rebuild was used for this remediation. The
original live run below remains a historical failed diagnostic: it used config
60, sent an obsolete synthesis prompt, and timed out. It is not evidence that
the corrected config 62 synthesis path has passed a live model-quality test.

## Outcome

QPA1-000 through QPA1-900 were executed in dependency order. The v4
question-planned analysis stack is implemented, deterministic local gates are
green, the explicit scale test is green, package boundaries are green, and
the repository passed the final compile/regression/diff checks.

The single authorized live GLM 5.2 run completed all 9 extraction windows but
the configured `ledger_synthesis` call reached its 1,200-second operation
deadline. This is the sole external blocker. No live answer, findings,
dispositions, or model-quality pass is claimed.

## Ticket and acceptance-gate disposition

| Ticket / gate | Disposition | Evidence |
|---|---|---|
| QPA1-000 / A | Complete | Baseline inventory, compile, route/process/config audit, dirty worktree preserved |
| QPA1-100 / B-C | Complete | v4 migration, strict contracts, config/control-store tests |
| QPA1-200 / D | Complete | `/v1/conversational-plan`, one planning call, old route 404 |
| QPA1-300 / E | Complete | Dumb client plan echo, none/semantic behavior, exact local hits |
| QPA1-400 / F | Complete | Frozen plan through one/many window orchestration |
| QPA1-500 / G | Complete | Independent range validation and partial status |
| QPA1-600 / H | Complete | Categorical dispositions, findings, compaction/synthesis contract |
| QPA1-700 / I | Complete | Admin, browser, Python progress/result display |
| QPA1-800 / J | Complete | 146 passed; explicit scale 1 passed; boundaries/diff passed |
| QPA1-900 / K | Complete with external blocker | 9 windows completed; synthesis `PROVIDER_TIMEOUT`; cleanup/restoration complete |

## Final runtime inventory

Product POST routes are exactly:

- `/v1/keyword-expansion`
- `/v1/conversational-plan`
- `/v1/conversational-analysis`
- `/v1/embeddings`

The active config is control schema 4, config schema 4, version 61, semantic
mode, and 90% window utilization after restoration. Operations are exactly:

`keyword_expansion`, `analysis_planning`, `window_evidence_extraction`,
`ledger_compaction`, `ledger_synthesis`.

The active five operations use model profile `model-7ac4caef076e`, model
`z-ai/glm-5.2`. The local embedding geometry is 384 dimensions with unit-L2
normalization. No secret values were read into logs or artifacts.

## Implementation and file disposition

Production contacts changed for this packet:

- `server/config.py`, `server/config_store.py`, `server/prompts.py`,
  `server/contracts.py`;
- `server/app.py`, `server/conversation_unified.py`,
  `server/evidence_ledger.py`, `server/conversation.py`;
- `server/admin.py`, `server/observability.py`;
- `message_evidence_workstation/client_api/contracts.py`,
  `message_evidence_workstation/client_api/gateway.py`,
  `message_evidence_workstation/services/client_workflows.py`, and the
  result/progress UI contact in `message_evidence_workstation/ui/main_window.py`;
- `scripts/verify_package_boundaries.py`,
  `scripts/run_retrieval_hint_experiment.py`, and the narrowly scoped
  `scripts/run_question_planned_analysis_live.py`.

Tests and documentation changed for QPA include the focused `test_qpa1_*`
files, converted SFV contract/conversation/client/admin/experiment fixtures,
`tests/test_sfv1_mixed_load.py`, `README.md`,
`docs/transformation/question_planned_analysis_v1/manual_test.md`, and this
packet's execution/closeout artifacts.

No `flutter_client/**`, EVW schema/migration/revision/embedding/evidence
storage, deleted legacy provider/search packages, corpus file, or existing
debug capture was changed. The 402-entry dirty worktree observed at baseline
was preserved; no reset, clean, checkout, commit, push, or deploy was used.

## v4 migration

The live control store migrated from control schema 3 to 4 before ticket work.
The explicit migration maps `retrieval_terms` to `analysis_planning`, maps
`disabled`/`terms_only` to `none`, preserves operation/provider/profile/
accounting settings, replaces the incompatible planner prompt, and records one
content-free migration audit entry. Runtime configuration requires schema 4;
old values remain only in explicit migration code/tests and historical packet
text.

During live validation, the original active config 59 at 90% utilization was
temporarily activated as config 60 at 60% utilization because the preflight
estimated 4.33 windows. After the run, config 61 restored 90% through the
normal admin save/validate/activate path. The final active config is semantic
mode with the five v4 operations.

## Deterministic proof

Commands and results:

```text
.venv\Scripts\python.exe -m compileall -q server message_evidence_workstation scripts tests
PASS

.venv\Scripts\python.exe -m pytest -q --basetemp .tmp\qpa1-final-regression
146 passed, 1 skipped, 2 deselected, 1 warning in 4.64s

.venv\Scripts\python.exe -m pytest -q -m scale --basetemp .tmp\qpa1-final-scale tests\test_sfv1_mixed_load.py
1 passed in 0.74s

.venv\Scripts\python.exe scripts\verify_package_boundaries.py
package boundaries: PASS

git diff --check
PASS (Git emitted only existing line-ending normalization warnings.)
```

The focused range/synthesis/client/runner command passed 24 tests with one
warning. The admin-focused verification passed 7 tests with one intentional
skip. Routine tests used only fake providers/embeddings and did not rebuild
the large EVW embedding cache.

Local partial-validation proof uses the MiniMax-shaped malformed-range fixture:
valid siblings are retained, unknown IDs are rejected with stable diagnostics,
rejected ranges never receive ledger IDs, and the terminal result is
`partial_evidence_validation` with visible rejected counts. Endpoint reversal
is normalized only for a provably valid same-thread interval. Findings require
at least one `direct_evidence` ID and cannot cite `not_responsive` ranges.

## Live artifacts and review

Run directory:

`.tmp/question-planned-analysis-live/20260730T052319Z-416dcfc9`

It contains the redacted `run-manifest.json`, exact `analysis-plan.json`,
`retrieval-metadata.json`, `request-metadata.json`,
`window-and-synthesis-events.json`, and exact `live-blocker.json`. The run
planned 9 windows and completed all 9 extraction calls. The per-window artifact
records accepted counts `4, 4, 7, 9, 6, 3, 1, 2, 3`; every window was
`complete` with zero rejected and zero normalized ranges. The synthesis
preflight fit directly with 39 accepted ranges and 408 distinct evidence
messages; no compaction was required before synthesis.

Exact active debug capture:

`C:\Users\artwh\.message_evidence_server\debug-captures\20260730T052325Z-6666d201bdcd.jsonl`

The capture contains the exact plan/provider traffic, all extraction responses,
range-validation artifacts, and the terminal provider error. It was stopped
and flushed with zero bound requests. The exact terminal error was:

```text
request_id: 8292bfbc-f27e-4cab-ae26-2819226563c8
code: PROVIDER_TIMEOUT
message: operation deadline expired
stage: provider
retryable: false
details: completed_windows=9, window_count=9
```

Because synthesis did not return, there is no actual live answer or final
ledger/disposition review to report. In particular, the live gate cannot
establish whether cooperative school planning was distinguished from conflict,
whether direct conflict was demoted, or which findings would have cited the
provisional positives. Those questions remain an explicit residual risk rather
than a claimed result. The local partial-range proof is complete and separate
from the blocked live synthesis.

EVW no-write verification: revision 4 was opened through read-only SQLite
access, and the run performed no EVW writes. Final EVW SHA-256 was
`06D5D25CCA193F2EDB389E3EC219BF42A79F8B1CD780F166DCFFF6A6A07817DC` with size
91,516,928 bytes; the recorded EVW/WAL/SHM timestamps were unchanged by the
run. The server was stopped after cleanup and port 8710 was clear.

## Residual risks

- The configured GLM 5.2 synthesis call exceeded 1,200 seconds for this
  9-window run. End-to-end live answer quality and latency are therefore not
  proven. No tuning or rerun was authorized inside this closeout.
- Existing historical packets and explicit migration tests still mention v3
  names by design; current runtime/client residue checks pass.
- The worktree contains substantial pre-existing dirty/user changes. They were
  preserved rather than normalized or committed.

## Lean manual test

1. Start with `\.venv\Scripts\python.exe -m server` and open
   `http://127.0.0.1:8710/admin/`.
2. Confirm schema 4, the five operations, semantic mode, and the four POST
   routes above; save/validate/activate one harmless planner setting and
   confirm the active version changes without restart.
3. Open the Python harness on the prepared revision-4 EVW and submit a
   question. Confirm visible planning, one semantic embedding workload/local
   lookup, exhaustive windows, validation totals, optional compaction, and the
   terminal result.
4. Use a malformed-range fixture to confirm the visible
   `PARTIAL EVIDENCE VALIDATION` warning and rejected count; rejected ranges must
   not appear in the ledger or findings.
5. Do not expose the loopback port, copy secrets, modify the EVW, or rerun the
   paid GLM diagnostic as part of this manual check.
