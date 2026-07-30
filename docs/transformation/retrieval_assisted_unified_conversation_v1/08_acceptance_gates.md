# Acceptance gates

The executor installs dependencies, prepares temporary state, runs tests,
starts/stops processes, and captures evidence. Do not assign automated work to
the user.

Use:

```powershell
.\.venv\Scripts\python.exe
```

If the repository environment is missing or incomplete, repair it from
`pyproject.toml` before testing. Do not use or modify system Python packages as
a substitute for the repository environment.

No routine automated gate may call a real provider or regenerate the large EVW
embedding cache. Only Gate J is live.

## Gate A - Baseline, compile, and static boundaries

Run:

```powershell
.\.venv\Scripts\python.exe -m compileall -q server message_evidence_workstation scripts tests
.\.venv\Scripts\python.exe scripts/verify_package_boundaries.py
git diff --check
```

Prove:

- exactly four `/v1` POST product routes;
- no capabilities or public internal-operation route;
- server has no EVW/client import;
- Python has no provider/model/prompt/window/RRF/retry policy;
- no Qt import in server;
- no runtime `whole_corpus_answer`, `whole_corpus`, `windowed_ledger`,
  `ledger_reduction`, or `retrieval_assistance_enabled`;
- no EVW schema/Flutter diff.

Historical docs and explicit migration tests may name removed terms.

## Gate B - Configuration migration and admin

Run focused control/admin tests. Prove:

- schema v2 copies migrate atomically to v3;
- every historical config version remains listable/activatable after
  deterministic transformation;
- whole assignment is absent;
- compaction assignment retains its old resolved behavior;
- Boolean assistance maps exactly;
- v3 settings validate and activate next request without restart;
- rollback and in-flight snapshot isolation work;
- invalid migration rolls back;
- secrets remain encrypted/masked;
- WAL/checkpoint/close remain clean;
- admin contains every new field/help/schema and no removed operation/control;
- calculated reserve changes with tokenizer/configured candidate bounds;
- headless browser editing/activation works.

## Gate C - Retrieval-plan endpoint

Run strict contract, app, provider-fault, accounting, and debug tests. Prove:

- valid extraction produces stable ordered query IDs;
- plan response carries actual embedding geometry/fingerprint;
- canonical fingerprint includes every specified field only;
- mode-only config changes do not invalidate a frozen plan;
- query/prompt/model/embedding/policy changes do invalidate it;
- empty/malformed provider output fails;
- configured retries are visible and no fallback occurs;
- normal logs/accounting contain no question/term content;
- active exact debug capture contains the complete request/provider/response.

## Gate D - Local candidate retrieval

Run Python workflow and EVW tests with deterministic vectors. Prove:

- one embedding workload contains every extracted query;
- local search is message-level only;
- exact selected revision scope;
- per-query top-K and deterministic ranks;
- cross-corpus closest vectors cannot appear;
- geometry/readiness mismatch stops before analysis;
- no automatic embedding build/clear;
- candidate payload contains no text/vector;
- network work never occurs in an EVW transaction;
- no unexpected WAL growth.

## Gate E - Unified one/many-window analysis

Run conversation, token accounting, streaming, ledger, and failure tests.
Prove:

- a fitting corpus uses one extraction call plus one synthesis call;
- there is no direct answer call;
- an oversized corpus uses the minimum safe deterministic balanced windows;
- every message appears exactly once;
- no retrieval prefilter;
- all windows are required;
- one/many return the same schema and different exact strategy values;
- fixed retrieval reserve produces identical A/B window hashes;
- all-no-evidence still synthesizes complete coverage;
- cancellation/failure never returns partial success;
- event sequence is strict and terminal.

## Gate F - Semantic suggestions and outside-suggestion recall

Run retrieval-assistance tests. Prove:

- exact RRF score/order;
- deterministic selection and adjacent-only ranges;
- no threshold or hidden fallback;
- selected prompt cap affects hints only;
- all messages/windows remain unchanged;
- one-window receives all relevant suggestions;
- multi-window receives only intersecting suggestions;
- prompt explicitly requires complete scanning and permits rejection;
- model sees no distance/RRF score;
- deterministic diagnostics distinguish evidence inside and outside hints;
- suggestions without evidence are counted;
- final evidence outside hints remains in the canonical ledger.

## Gate G - Ledger compaction fallback

Run direct/forced compaction tests. Prove:

- every request emits exact direct-synthesis preflight;
- the measured 40-range-shaped fixture fits and does not compact;
- exact overflow triggers, never an arbitrary count;
- WARNING, stream, admin, debug, usage, final metadata, and Python progress are
  all visible;
- every group/level preserves all IDs once and in order;
- canonical request-local records/excerpts are unchanged through compaction,
  and final range entries use original IDs/boundaries/summary/relevance;
- malformed coverage fails;
- oversize record/depth fail noisily;
- no compaction provider/model fallback;
- no content leaks into normal logs/control DB.

## Gate H - Python integration and UI behavior

Run gateway/workflow/UI tests and a deterministic subprocess integration.
Prove:

- one conversational action performs the complete new sequence;
- strict new JSON and NDJSON contracts;
- cancellation works during plan, embeddings, windows, compaction, synthesis;
- elapsed time advances during all server work and after failures until
  terminal handling;
- retry events are visible;
- compaction warning/progress is human-readable;
- only completed visible result persists;
- test runner leaves EVW byte/WAL state unchanged.

## Gate I - Full regression and mixed load

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Also run the deterministic mixed-load harness required by RAUC1-700.

Record test count, duration, queue/latency metrics, and process cleanup. No
green gate may depend on weakening a production contract or hardcoding expected
model answers.

## Gate J - Live investigative run

Only after Gates A-I pass, execute file 09 using already approved configured
credentials.

Required:

- fresh active debug capture;
- 100K single-window smoke;
- one frozen retrieval plan/candidate pool;
- terms-only arm;
- full semantic arm;
- conditional censored semantic arm;
- no automatic repeated arms;
- same retrieval compatibility fingerprint;
- same model/prompt/policy settings except assistance mode;
- same window-plan hash across comparable arms;
- provisional known-positive retrieval ranks;
- final known-positive recall;
- outside-suggestion evidence counts;
- exact prompt/capture inspection;
- compaction status and synthesis size;
- stopped/flushed capture and artifact paths.

External provider failure cannot be disguised with fallback. If it prevents
this gate after configured attempts, record it as the sole external omission.

## Final closeout

`closeout_report.md` must contain:

- every ticket disposition;
- changed/deleted files and preserved unrelated worktree state;
- exact commands/results/timings;
- route and operation inventory;
- configuration migration and active version;
- one/many-window proof;
- direct/compaction proof;
- retrieval candidate/rank/overlap summary;
- live A/B/C result or exact external blocker;
- debug capture and diagnostic artifact paths;
- no-write EVW/WAL verification;
- current startup command, admin URL, and lean manual test;
- intentionally deferred work limited to auth/billing/BYOK/Flutter production
  integration and later FTS/chunk retrieval experiments.
