# Acceptance gates

The executor installs dependencies, prepares temporary state, runs tests,
starts/stops processes, and captures evidence. Do not assign automated work to
the user.

Use only the repository environment:

```powershell
.\.venv\Scripts\python.exe
```

If incomplete, repair it from `pyproject.toml`. Do not use or modify system
Python packages as a substitute.

Routine automated gates use deterministic fake providers/embeddings. They make
no real model calls and do not rebuild the large EVW embedding cache.

## Gate A - Baseline and boundaries

Run:

```powershell
.\.venv\Scripts\python.exe -m compileall -q server message_evidence_workstation scripts tests
.\.venv\Scripts\python.exe scripts\verify_package_boundaries.py
git diff --check
```

Record:

- current test baseline;
- dirty-worktree preservation;
- process/port inventory;
- current config/route/operation inventory;
- no EVW/Flutter mutation.

## Gate B - Configuration v4

Focused config/control-store tests prove:

- every v3 mode maps exactly;
- `retrieval_terms` settings become `analysis_planning`;
- the incompatible prompt is deliberately replaced;
- active/draft/version identities and encrypted secrets survive;
- invalid migration is atomic and byte-for-byte rolled back;
- restart/checkpoint/clean close work;
- runtime accepts only v4 operations/modes.

## Gate C - Strict contracts

Contract tests prove:

- exact analysis plan/output bounds;
- exact public plan and analysis-context shape;
- exact extraction envelope;
- exact range diagnostic and validation summary;
- exact finding/disposition rules;
- exact compaction output;
- exact result and events;
- missing, extra, coerced, blank, duplicate, unknown, and incompatible values
  fail as specified;
- removed v3 literals fail.

No response default filling is allowed.

## Gate D - Planning endpoint

Endpoint/provider/debug/accounting tests prove:

- one planning provider call;
- faithful complete plan returned;
- deterministic query IDs;
- no fallback queries;
- correct `none`/semantic behavior;
- exact fingerprint inclusions/exclusions;
- configured retry and cancellation visibility;
- request-local configuration snapshot;
- exact debug capture only when active;
- content-free normal logs/accounting;
- old route returns 404;
- exactly four product POST routes.

## Gate E - Client plan execution

Gateway/workflow/EVW tests prove:

- plan is echoed byte-equivalently;
- client cannot add/edit/reorder queries;
- `none` makes no embedding or local lookup call;
- semantic mode sends one embedding workload;
- exact selected-revision message-level lookup;
- geometry/readiness mismatch fails before analysis;
- hits contain IDs/rank/distance only;
- no automatic embedding generation/clear;
- no network work inside EVW transactions;
- no EVW write or unexpected WAL growth.

## Gate F - Frozen-plan one/many orchestration

Conversation/window/token/stream tests prove:

- every conversational request requires a plan;
- one exact plan reaches every extraction, compaction, and synthesis call;
- one-window path is extraction plus synthesis;
- multi-window path scans every required window plus synthesis;
- every message appears exactly once;
- retrieval suggestions do not alter coverage;
- exact plan payload participates in token packing;
- one/many return one result schema;
- stage failure/cancellation remains terminal;
- no direct whole path or parallel planner exists.

## Gate G - Range-granular validation

Validator/ledger/observability tests prove:

- valid sibling ranges survive malformed siblings;
- unknown IDs are rejected, never guessed;
- endpoint swaps occur only under the exact deterministic rule;
- all rejection codes are stable;
- duplicate handling is deterministic;
- accepted global IDs are completion-order independent;
- rejected ranges never enter evidence;
- all-invalid produces explicit partial completion;
- malformed envelope still fails;
- normal logs are content-free;
- active debug capture is exact;
- final status, events, client, and persisted visible result all preserve
  partial status.

## Gate H - Answer-oriented synthesis

Prompt/synthesis/compaction tests prove:

- planner operationalizes rather than merely extracts terms;
- extraction seeks plan-responsive candidates and has no global contradiction
  policy;
- synthesis answers the plan;
- every accepted range receives one allowed disposition;
- all ledger records survive;
- findings cite valid direct/context IDs only;
- not-responsive candidates are absent from findings;
- no numeric evidence score/rank/confidence exists;
- compaction preserves complete ID coverage and does not classify relevance;
- direct and compacted synthesis use the same output contract;
- partial validation is disclosed to synthesis and answer;
- bad synthesis fails noisily.

## Gate I - Admin and Python test UI

TestClient/headless-browser/Python integration tests prove:

- exactly five operation cards and four route descriptions;
- full planner configuration and strict schema are visible;
- every editable control affects the next request after activation;
- no restart is required for operation/global changes;
- rollback works;
- retrieval modes are only `none|semantic_ranges`;
- partial-validation counts/warnings are visible without content leakage;
- paid synthetic planner test uses draft settings and warns about cost;
- Python progress/timer/cancel behavior covers every stage;
- answer, findings, complete ledger, and partial warning render clearly;
- only terminal completed visible results persist.

## Gate J - Mixed load and full regression

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Run the explicit scale/mixed-load test separately if default pytest deselects
it.

Prove:

- concurrent plan/embedding/one-window/multi-window/partial/compaction/admin
  work remains bounded;
- event loop remains responsive;
- streams are exact and monotonic;
- cancellation and retries remain visible;
- accounting covers every provider attempt/workload;
- no content persists outside active debug capture;
- no test weakened a production contract;
- no real provider call occurred;
- no large embedding rebuild occurred.

Repeat compile, package boundary, forbidden-residue scan, and
`git diff --check`.

## Gate K - Live validation

Only after Gates A-J pass, execute file 09 with already configured credentials.

This gate makes one authorized large live conversational run. It does not
automatically repeat a failed or low-quality arm.

## Final closeout

`closeout_report.md` must contain:

- every ticket/gate disposition;
- changed/deleted files and preserved unrelated dirty state;
- exact commands, test counts, timings, and failures fixed;
- v4 migration and active config;
- final route/operation/mode inventory;
- exact one/many and partial-validation proof;
- synthesis/disposition/finding proof;
- live artifact paths and actual answer/ledger review;
- debug capture stop/flush state;
- no-write EVW/WAL evidence;
- current startup/admin URLs and lean manual test;
- factual residual risks;
- no claim that model quality passed if the live result did not.

