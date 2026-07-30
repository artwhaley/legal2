# RAUC1 closeout report

Date: 2026-07-30  
Repository: `C:\Users\artwh\OneDrive\Documents\legal2`  
Packet: `docs/transformation/retrieval_assisted_unified_conversation_v1`

## Outcome

RAUC1-000 through RAUC1-900 are implemented and locally validated. The
runtime now has four product POST routes and one unified extraction ->
canonical ledger -> synthesis path. The live investigation was executed after
recovering from the power interruption. The provider was reachable and one
semantic arm completed successfully, but two diagnostic arms and the required
100K smoke produced strict, non-retryable ledger contract failures. The live
apples-to-apples comparison is therefore correctly marked invalid; no fallback,
permissive repair, or retry was used.

## Ticket disposition

| Ticket | Disposition | Evidence |
|---|---|---|
| RAUC1-000 | Complete | Baseline, worktree, package-boundary, route, fixture, and no-EVW-change checks recorded in `execution_log.md`. |
| RAUC1-100 | Complete | Config v3, explicit v2 migration, final five operations, and migration tests. |
| RAUC1-110 | Complete | Strict v3 contracts, result/event validation, fingerprints, ranks, geometry, and bijection checks. |
| RAUC1-120 | Complete | `POST /v1/conversational-retrieval-plan`, one `retrieval_terms` call, frozen plan geometry and fingerprint. |
| RAUC1-200 | Complete | One embedding workload for all queries, local exact message-level EVW lookup, deterministic RRF candidates. |
| RAUC1-300 | Complete | Unified extraction-ledger-synthesis orchestration; retired runtime whole-corpus path removed. |
| RAUC1-310 | Complete | Exact RRF ordering, advisory adjacent suggestions, outside-suggestion accounting, and overlap diagnostics. |
| RAUC1-400 | Complete | Exact synthesis preflight, loud hierarchical compaction, coverage and processing events. |
| RAUC1-500 | Complete | Admin operation guide, sample payloads, configuration projection, and content-free event status. |
| RAUC1-600 | Complete | Linear Python client workflow, cancellation boundaries, and visible retrieval/server progress. |
| RAUC1-700 | Complete | 117-test regression, explicit scale test, compile, boundary, and diff checks. |
| RAUC1-800 | Complete | Reproducible read-only experiment runner and artifact set. |
| RAUC1-900 | Complete with live limitation | Capture/report completed; provider contract failures are preserved and comparison is marked invalid. |

## Runtime contract delivered

The only product POST routes are:

1. `/v1/keyword-expansion`
2. `/v1/conversational-retrieval-plan`
3. `/v1/conversational-analysis`
4. `/v1/embeddings`

The server owns model/provider calls, prompts, retrieval-term generation,
window planning, ranking, extraction, ledger compaction, and synthesis. The
Python client owns the EVW readiness check, one query-embedding workload, local
message-level vector lookup, candidate IDs/ranks/distances, and request
assembly. Retrieval suggestions are advisory: the extraction prompt requires
full assigned-window inspection and the live semantic result demonstrates
material final ranges outside suggestions.

The runtime configuration is schema v3 with exactly these five operations:

- `keyword_expansion`
- `retrieval_terms`
- `window_evidence_extraction`
- `ledger_compaction`
- `ledger_synthesis`

The old runtime whole-corpus and ledger-reduction execution paths are absent.
Legacy names remain only in explicit v2-to-v3 migration compatibility code.
No Flutter, EVW schema, EVW lifecycle, or EVW storage code was changed.

## Validation

Final commands and results:

- `.venv\Scripts\python.exe -m pytest -q --basetemp .tmp\rauc1-final-regression` — **117 passed, 1 skipped, 2 deselected**, one existing Starlette/httpx deprecation warning, 7.31 seconds.
- `.venv\Scripts\python.exe -m pytest -q --basetemp .tmp\rauc1-final-scale tests\test_sfv1_mixed_load.py -m scale` — **1 passed**, 0.90 seconds.
- `.venv\Scripts\python.exe -m compileall -q server message_evidence_workstation scripts tests` — passed.
- `.venv\Scripts\python.exe scripts\verify_package_boundaries.py` — `package boundaries: PASS`.
- `git diff --check` — passed; only existing LF-to-CRLF warnings were emitted.

The skipped test is the Playwright browser test because Playwright is not
installed in this environment. The two deselected tests are the default
pytest `not scale` selection behavior.

## Live investigation

Artifacts:

- Directory: `.tmp\retrieval-hint-experiment\20260729T232500Z`
- Manifest: `manifest.json`
- Frozen plan ID: `8e4e6e84-bc07-4ba0-b423-a854e743b9a1`
- Frozen queries: `fight`, `school`
- Embedding profile: 384 dimensions, `unit_l2`
- Working corpus: EVW revision 4, 12,402 messages
- Smoke corpus: EVW revision 3, 1,387 messages, 99,980 estimated tokens
- Capture: `C:\Users\artwh\.message_evidence_server\debug-captures\20260730T002011Z-7cc97e5aa5ed.jsonl`
- Final capture state: stopped, zero pending records, no writer failure

| Run | Result | Measured outcome |
|---|---|---|
| 100K one-window smoke | Partial, strict failure | One window; 18,688.4 ms; `LEDGER_BIJECTION_FAILED`. |
| Terms-only | Partial, strict failure | Six windows; 398,493.5 ms; `LEDGER_BIJECTION_FAILED`. |
| Full-semantic | Complete | Six windows; 613,628.5 ms; `multi_window_ledger`; 74 ranges; 7/7 provisional-gold recall; 69 final ranges outside suggestions; 18 used ranges outside suggestions; no compaction. |
| Censored-semantic | Partial, strict failure | Six windows; 341,908.3 ms; `LEDGER_BIJECTION_FAILED`; eligible because raw candidates overlapped provisional positives. |

All three arms reused the same plan and the same window-plan hash:
`f9684a8ad9a3e69aaed24db10496a7987211602901a894a5abc65cdd220d7660`.

The live provider failures are preserved in each `*-result.json` artifact. The
provider returned responses, but the returned evidence did not satisfy the
strict server ledger contract. The 100K failure was specifically a returned
range with an invalid thread binding. The server emitted the failure and did
not silently discard, repair, or reinterpret the range. Because terms-only and
censored-semantic are partial, `comparison.json` and `comparison.md` state
that no valid apples-to-apples quality comparison can be claimed.

## Data integrity and state preservation

The investigation runner opened the EVW with SQLite `mode=ro` and performed
local message-level lookup only. The recorded fixture state is:

- `.tmp\sfv1-fixture-multicorpus-v15.evw`: 91,516,928 bytes
- SHA-256: `06d5d25cca193f2edb389e3ec219bf42a79f8b1cd780f166dcfff6a6a07817dc`
- Sidecars were observed as `.evw-shm` 32,768 bytes, `.evw-wal` 37,112 bytes,
  and `.evw.lock` 19 bytes.

The interrupted empty run directories were preserved. The completed run keeps
the frozen plan, query embedding metadata, raw candidates, raw gold overlap,
per-arm request/result artifacts, selected suggestions, comparison artifacts,
and the debug-capture path. No repository reset, cleanup, staging, commit, or
external deployment was performed.

## Residual limitation and next action

The implementation is ready from the local gates. The remaining live issue is
provider output quality under the strict evidence-range contract; it is not a
server fallback decision or a missing local prerequisite. A future live rerun
should happen only after the provider/model configuration is corrected or a
provider response contract issue is otherwise resolved. The captured full
semantic result is usable evidence of the intended path, but it must not be
presented as a valid three-arm quality comparison.

Authentication, billing, BYOK, and unrelated Flutter/client-surface work remain
outside this packet and were intentionally deferred. Later FTS/chunk retrieval
is also outside this stack.

## Manual verification

From the repository root:

```powershell
.venv\Scripts\python.exe -m pytest -q --basetemp .tmp\rauc1-final-regression
.venv\Scripts\python.exe -m pytest -q --basetemp .tmp\rauc1-final-scale tests\test_sfv1_mixed_load.py -m scale
.venv\Scripts\python.exe scripts\verify_package_boundaries.py
```

For the preserved live artifacts, inspect `manifest.json`,
`comparison.md`, the full-semantic result, the two partial result files, and
the capture path above. The admin status endpoint is:

`GET http://127.0.0.1:8710/admin/events`

## Post-handover audit and corrected three-arm run

The live investigation above is retained as historical evidence, but it is not
the final validation state. A post-handover audit found two material issues:

1. The strict ledger validator was correctly rejecting malformed provider
   output, but the extraction prompt did not make the opaque-ID ordering and
   thread-binding contract explicit enough. The failed responses included
   reversed endpoints and one `thread_id` populated with a message ID.
2. The persisted active configuration still contained the older extraction and
   compaction prompts. Therefore, the earlier full-semantic success did not
   exercise the intended current prompt contract and could not serve as the
   final comparison.

The extraction prompt now explicitly requires array-order range endpoints,
opaque IDs copied verbatim, and the message's actual `thread_id`. Ledger
failures now expose safe, exact range diagnostics. Each completed window is
validated before its completion event and before later batches proceed. No
range repair, silent retry, provider fallback, or evidence omission was added.
The comparison renderer now includes the exact synthesized answer and complete
returned evidence ledger for every arm.

The active persisted configuration was advanced to version 25 and verified to
contain the exact current default prompts for all five operations:

- `keyword_expansion`
- `retrieval_terms`
- `window_evidence_extraction`
- `ledger_compaction`
- `ledger_synthesis`

The final local validation after these corrections was:

- **122 passed, 1 skipped, 2 deselected**
- explicit scale test: **1 passed**
- compilation: passed
- package-boundary verification: passed
- `git diff --check`: passed

Corrected live artifacts:

- Directory:
  `.tmp\retrieval-hint-experiment\20260730T010423Z-audit`
- Human review:
  `comparison.md`
- Machine-readable run record:
  `manifest.json`
- Frozen plan ID:
  `96b53ea1-854a-45bb-bdf4-7104da20797a`
- Frozen retrieval terms:
  `fight`, `school`, `when`
- Working corpus:
  revision 4, 12,402 messages
- Window-plan hash shared by all arms:
  `f9684a8ad9a3e69aaed24db10496a7987211602901a894a5abc65cdd220d7660`
- Windows per arm: 6

| Arm | Result | Recall | Ledger ranges | Used ranges | Wall time |
|---|---|---:|---:|---:|---:|
| `terms_only` | Complete | 7/7 | 31 | 8 | 426.5 s |
| `semantic_ranges` | Complete | 5/7 | 19 | 13 | 272.1 s |
| `semantic_ranges_censored` | Complete | 6/7 | 28 | 13 | 436.9 s |

All three arms completed without retry, fallback, queueing, throttling, ledger
compaction, or contract failure. The comparison is valid as a controlled
single-run diagnostic: it used one frozen corpus, query, retrieval-term set,
query embedding, plan, and exact window partition.

In this run, ordinary semantic suggestions did not improve recall:
`terms_only` found all seven provisional known-positive events,
`semantic_ranges` found five, and `semantic_ranges_censored` found six despite
having all known-positive suggestions removed. The more important diagnostic
did succeed: the model continued to inspect the complete assigned windows
instead of limiting itself to suggested ranges. In the normal semantic arm,
all 13 ranges used by synthesis were outside the suggestions. In the censored
arm, 11 of 13 used ranges were outside the suggestions, and it recovered six
of seven known-positive events with zero known-positive suggestion overlap.

This is one stochastic provider run, not a statistical quality conclusion.
It does show that suggestions are nonbinding attention aids in the implemented
path. It also gives no present evidence that the normal semantic suggestions
improve this query. The normal semantic arm was faster, but it also returned
less evidence and output, so that timing difference must not be attributed to
retrieval assistance without repeated runs.

Debug capture stopped cleanly with zero pending records and no writer failure.
The server was stopped after the run. EVW and Flutter state were not changed.
