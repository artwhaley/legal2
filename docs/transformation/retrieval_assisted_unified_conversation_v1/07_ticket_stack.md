# Authoritative ticket stack

Execute sequentially. A ticket may break conflicting old tests; update those
tests in the same ticket. Complete implementation, focused tests, and execution
log evidence before beginning a dependent ticket.

## RAUC1-000 - Baseline and contact-surface inventory

Read this complete packet and repository `AGENTS.md`. Inspect git status,
current server/config/control-store migrations, app routes, contracts,
conversation/evidence-ledger implementation, admin, debug capture, embedding
metadata, Python gateway/workflow/UI, relevant tests, and current fixtures.

Record in `execution_log.md`:

- branch, HEAD, upstream status, and dirty files without modifying them;
- baseline compile and relevant test results;
- every `whole_corpus_answer`, `whole_corpus`, `windowed_ledger`,
  `ledger_reduction`, and `retrieval_assistance_enabled` runtime contact;
- current debug-capture session/file inventory and active status without
  printing corpus content;
- current control schema/config version and active operation names with secrets
  redacted;
- message-embedding readiness/geometry for fixture revisions 3 and 4;
- current product route list.

Gate: complete inventory and no unexplained mutation.

## RAUC1-100 - Configuration v3 and clean operation migration

Implement file 03 configuration decisions:

- schema v3;
- final five chat operations;
- delete whole assignment;
- rename reduction to compaction;
- add retrieval mode/policy settings;
- atomic migration for all stored versions;
- preserve secrets, active identity, audit, and usage;
- one v3 runtime path only.

Update config validation, serialization, fingerprints, admin projections needed
by tests, and bootstrap defaults.

Tests must cover:

- true/false Boolean migration;
- whole removal;
- compaction assignment preservation;
- every old version transformed;
- active/draft/rollback behavior after migration;
- invalid migration rollback;
- restart and clean WAL;
- no plaintext secret exposure;
- no schema-v2 runtime aliases.

Gate: focused config/control-store tests pass and current real control store can
be migrated through a safe copied state directory.

## RAUC1-110 - Strict retrieval-plan and analysis contracts

Implement all request/response/event/result models from file 03. Register the
fourth product route schema and exact event unions. Remove whole events and old
strategy literals. Add retrieval and ledger-processing diagnostics.

Tests cover:

- missing/extra/wrong/coerced fields;
- ID/text length bounds;
- null/object mode invariants;
- nonfinite/negative distance;
- duplicate/unknown/noncontiguous ranks;
- excess hits;
- malformed fingerprints;
- exact new stream payload fields;
- removed events rejected.

Gate: strict contract tests pass with no response default filling.

## RAUC1-120 - Conversational retrieval-plan endpoint

Implement `/v1/conversational-retrieval-plan` in the existing FastAPI app and
admission/debug/error/accounting infrastructure.

Use the configured `retrieval_terms` operation, existing prepared embedding
runtime metadata, canonical compatibility fingerprint, strict normalization,
and normal content-free usage accounting.

Update admission middleware route allowlist and static route tests.

Do not call embeddings here; the client calls `/v1/embeddings` with returned
queries so the existing streaming embedding boundary remains exercised.

Tests cover:

- valid response;
- exact normalization/order/query IDs;
- empty-after-normalization failure;
- malformed model output;
- provider failures/retries/cancellation;
- config snapshot isolation;
- fingerprint changes for every relevant field and not for unrelated/mode
  changes;
- debug capture exact records;
- normal logs contain no question/term content.

Gate: endpoint tests and four-route enumeration pass.

## RAUC1-200 - Multi-query local vector candidate workflow

Extend the Python gateway and workflow:

- call retrieval-plan endpoint;
- submit all queries in one embedding workload;
- verify plan/server/EVW geometry;
- run exact local message-vector search per query;
- add deterministic rank;
- build strict candidate payload;
- keep network calls outside EVW transactions;
- preserve cancellation/progress.

Keep standalone embedding search working.

Do not rebuild embeddings automatically or add chunk/FTS/full-question search.

Tests use two corpora with cross-scope closer vectors and prove:

- exact selected-revision membership;
- one embedding request for all terms;
- expected top-K per query;
- deterministic rank/ties;
- geometry/readiness failure before analysis;
- no body text in candidate payload;
- no long transaction/WAL growth.

Gate: Python focused integration tests pass.

## RAUC1-300 - One extraction-ledger-synthesis orchestration

Rewrite conversational orchestration to remove the direct whole branch:

- validate retrieval plan/candidates;
- plan one or many extraction windows;
- run the same `window_evidence_extraction` call for every window;
- build the same canonical ledger;
- direct-preflight and synthesize;
- return `single_window_ledger` or `multi_window_ledger`.

Preserve current bounded concurrency, retries, cancellation, usage aggregation,
strict window output, deterministic completion-order-independent range IDs,
empty-evidence synthesis, and all required-window behavior.

Delete whole operation runtime/model/prompt/events/tests and `build_whole_ledger`.

Implement fixed retrieval payload reservation and `window_plan_hash`.

Tests prove:

- 100K-like payload produces exactly one extraction call then synthesis;
- larger payload produces all balanced windows then synthesis;
- no direct whole call exists;
- every message appears exactly once;
- one-token and boundary payload behavior uses extraction budget;
- one/many paths return identical schema;
- same retrieval plan under terms/semantic configurations yields identical
  window hashes;
- all-window no-evidence still synthesizes;
- any required-stage failure terminates without partial answer.

Gate: conversation/evidence-ledger tests pass and static scan finds no runtime
whole path.

## RAUC1-310 - Semantic fusion, suggestion ranges, prompts, and overlap

Implement file 04 exactly:

- strict candidate validation;
- deterministic RRF;
- selected/unselected accounting;
- adjacent-only per-window range grouping;
- prompt query/suggestion fields;
- advisory exhaustive prompt;
- actual-payload exact check;
- deterministic overlap diagnostics.

Tests include:

- multi-query duplicate fusion;
- RRF/tie ordering;
- explicit prompt cap without corpus/evidence filtering;
- adjacent merge and gap/thread/window separation;
- suggestion distribution across one and many windows;
- prompt contains no scores or duplicated transcript;
- evidence inside and outside suggestions;
- used/not-material/redundant overlap counts;
- suggestions with no evidence;
- hints do not alter message/window coverage.

Gate: retrieval-assistance tests pass and prompt snapshots are exact.

## RAUC1-400 - Retain, rename, harden, and expose ledger compaction

Rename the current fallback and implement file 05:

- exact direct synthesis preflight every request;
- conditional hierarchical compaction;
- immutable canonical ledger;
- complete ID/order validation every group/level;
- final assembly from original records;
- explicit failure codes;
- loud events/logs/admin metrics/result metadata;
- usage/accounting for every compaction call.

Do not remove this fallback. Do not call model summarization mathematically
lossless in user-facing text.

Tests force:

- direct 40-range-sized ledger fits and makes no compaction call;
- exact one-token-over direct budget triggers compaction;
- multiple groups and levels;
- every original ID survives;
- canonical request-local records/excerpts remain byte-identical through
  compaction, and final range entries retain original
  IDs/boundaries/summary/relevance;
- missing/duplicate/reordered/unknown IDs fail;
- one oversize record fails;
- depth overflow fails;
- compaction warning and progress are visible;
- normal logs remain content-free;
- debug capture contains exact group inputs/outputs only when enabled.

Gate: evidence-ledger, accounting, streaming, and observability tests pass.

## RAUC1-500 - Admin usability and runtime configuration

Update the existing server-rendered admin:

- four-route explanation;
- unified one/many-window flow;
- remove whole operation card;
- rename and explain compaction;
- retrieval mode and numeric policy fields;
- read-only calculated retrieval reserve;
- operation prompt/schema views;
- compaction recent warning and since-process count;
- practical 40-range reference;
- next-request activation behavior.

Every control must affect runtime. Keep current CSRF, masked secrets, draft,
validation, activation, rollback, explicit provider test, and debug page.

Headless browser and TestClient tests edit, validate, activate, invoke, inspect,
and roll back retrieval settings without restart.

Gate: admin tests pass; no no-op/duplicate/whole/reduction UI remains.

## RAUC1-600 - Python conversation integration and visible progress

Wire `ConversationalWorkflow` and the existing Python GUI to the full sequence:

```text
retrieval plan
-> query embeddings
-> local candidate search
-> conversational stream
```

Update strict gateway contracts for the new endpoint/events/result. Preserve
request cancellation, elapsed timer, completed-window counts, and final visible
history persistence.

Compaction progress must explicitly show required/available tokens, level/group
progress, and keep elapsed time moving.

Only a completed final result persists. Diagnostic runner bypasses visible
history persistence.

Gate: Python integration tests prove one-window, multi-window, provider retry,
cancel, interrupted stream, semantic hits, outside-hit evidence, and forced
compaction UI progress.

## RAUC1-700 - Regression, mixed load, and boundary proof

Run and fix all relevant deterministic tests. Add a mixed-load test covering at
least:

- concurrent retrieval-plan calls;
- query embedding workloads;
- one-window analyses;
- multi-window analyses;
- a forced-compaction analysis;
- admin reads.

Assert configured provider/embedding/window limits, bounded queues, snapshot
isolation, monotonic exact streams, cancellation, accounting, no event-loop
stall, and no persisted content.

Run package boundary scans proving:

- server imports no EVW/client package;
- Python owns no model/prompt/window/retry/RRF policy;
- no removed whole/reduction symbols remain outside migrations/historical docs;
- exactly four product routes.

Gate: full deterministic suite and static scans pass.

## RAUC1-800 - Reproducible retrieval investigation runner

Implement `scripts/run_retrieval_hint_experiment.py` exactly as file 09.

It must:

- open the selected EVW read-only;
- make no history/evidence/settings writes;
- verify scope and embedding readiness before provider calls;
- freeze one plan, query-vector set, and complete candidate pool;
- run terms-only, full semantic, and conditional censored semantic arms;
- verify identical retrieval fingerprint, model assignments, and window hash;
- calculate provisional-gold retrieval rank and final recall;
- calculate evidence found outside shown suggestions;
- write complete `.tmp` artifacts and a human-readable report;
- refuse to run unless server debug capture is active;
- never repeat expensive arms automatically.

Tests use fake HTTP/provider/vector fixtures and make no real model calls.

Gate: deterministic runner tests pass and its report detects deliberately
omitted known positives.

## RAUC1-900 - Live investigative run, documentation, and closeout

After every local gate passes:

1. migrate/activate current copied then real server configuration safely;
2. configure retrieval terms, extraction, compaction, synthesis, and embeddings
   through admin;
3. start a fresh temporary exact debug-capture session;
4. run one-window 100K smoke;
5. run the large revision investigation from file 09;
6. stop capture and wait for bound requests/writer flush;
7. inspect exact prompts, candidates, outside-suggestion results, retries,
   ledger preflights, and compaction status;
8. stop unnecessary test processes;
9. run full final regression and `git diff --check`;
10. update README/manual test;
11. create `closeout_report.md`.

The live investigation is authorized for one pass per arm using already
configured credentials. Do not run automatic repeats. If credentials are
unavailable or the provider remains externally unavailable after configured
attempts, complete all local work and record the live gate as the sole external
blocker. Never invent a fallback provider/model.

Closeout includes ticket status, changed/deleted files, exact commands/results,
route/config inventory, control migration, one/many-window proof, candidate and
gold-rank summary, A/B/C comparison, outside-suggestion recall, complete debug
capture path, ledger sizing/compaction result, regression totals, and lean
manual test instructions.

Gate: every mandatory local criterion passes and no known in-scope deficiency
remains.
