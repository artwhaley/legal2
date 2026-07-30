# Authoritative ticket stack

Execute sequentially. A ticket may update or delete conflicting old tests in
the same ticket. Complete implementation, focused tests, relevant regression,
and execution-log evidence before beginning a dependent ticket.

## QPA1-000 - Baseline and contact-surface inventory

Read repository `AGENTS.md` and this entire packet. Inspect the dirty worktree,
current routes, config/migrations, planner endpoint, prompts, range validation,
ledger assembly, compaction, synthesis, admin, debug capture, accounting,
Python gateway/workflow/UI, scripts, and tests.

Record in `execution_log.md`:

- branch, HEAD, upstream status, and dirty files without modifying them;
- running server/client/diagnostic processes and ports;
- active config schema/version and final operation assignments, with secrets
  redacted;
- current product route inventory;
- current deterministic compile/focused/full-test baseline;
- every runtime/client contact for all v3 names listed in file 06;
- current debug-capture status without printing content;
- preserved live comparison artifact paths;
- exact overlapping user changes in every file expected to be edited.

Gate: complete inventory, no unexplained mutation, and no destructive cleanup.

## QPA1-100 - Configuration v4 and strict contract foundation

Implement file 03 configuration and data contracts:

- schema v4;
- final five operation names;
- `none|semantic_ranges` retrieval mode;
- atomic v3-to-v4 migration;
- plan, analysis-context, extraction-envelope, partial-validation,
  finding/disposition, final-result, diagnostics, and stream models;
- revised schema registry;
- remove runtime v3 aliases and literals.

Migration must preserve non-prompt operation settings while replacing the
incompatible planning prompt as specified.

Tests cover:

- every v3 retrieval-mode mapping;
- operation rename and setting preservation;
- planner prompt replacement;
- active/draft/version/rollback behavior;
- invalid migration byte-for-byte rollback;
- secret masking/encryption;
- restart and clean control-store WAL;
- missing/extra/wrong/coerced fields for every new public/model/event shape;
- exact disposition/finding invariants;
- old runtime literals rejected.

Gate: focused config, store, and contract tests pass.

## QPA1-200 - Real analysis-planning operation and endpoint

Replace the shallow retrieval-term call with
`POST /v1/conversational-plan` and operation `analysis_planning`.

Implement:

- strict planner prompt and model output;
- exact bounds and uniqueness;
- deterministic `q0001` query IDs;
- `none` versus `semantic_ranges` response behavior;
- actual embedding metadata only in semantic mode;
- canonical compatibility fingerprint;
- standard admission, provider runtime, configured retries, cancellation,
  debug capture, and usage accounting;
- old route deletion.

Tests cover:

- a valid generic plan;
- strict rejection of missing, extra, blank, duplicate, or over-limit plan
  values;
- no fallback when retrieval queries are missing/invalid;
- fingerprint sensitivity to every specified field and insensitivity to
  unrelated extraction/synthesis settings;
- no embedding runtime preparation in `none`;
- actual prepared geometry in semantic mode;
- provider failures/retries/cancellation;
- config snapshot isolation;
- exact debug capture;
- no question/plan text in normal logs/accounting;
- exactly four product POST routes.

Gate: endpoint, provider, accounting, debug, and route tests pass.

## QPA1-300 - Dumb-client plan execution and local retrieval

Update only current Python test-equipment surfaces:

- call `/v1/conversational-plan`;
- strictly validate the returned plan;
- do not modify/reorder/add plan fields or retrieval queries;
- obey returned retrieval mode;
- skip embedding/search entirely for `none`;
- for `semantic_ranges`, embed all queries in one workload and run existing
  exact selected-revision message lookup;
- echo the complete analysis context and candidate hits;
- keep network work outside EVW transactions;
- preserve cancellation and visible progress.

Delete old plan gateway/workflow contracts rather than aliasing them.

Tests prove:

- exact plan round trip;
- no client-authored query;
- no embedding call in `none`;
- one embedding workload in semantic mode;
- exact revision-scoped hits and deterministic ranks;
- geometry/readiness failure before analysis;
- no vector/text in hit payload;
- no automatic embedding build or clear;
- no EVW write or WAL growth;
- cancellation during planning, embedding, and local search.

Gate: client contract, retrieval, and workflow tests pass.

## QPA1-400 - Frozen-plan unified orchestration

Wire the complete analysis context into the existing unified path:

- validate plan compatibility and policy at ingress;
- include the exact plan in payload token accounting;
- pass it unchanged to every extraction, compaction, and synthesis call;
- preserve current deterministic minimum-window balanced packing;
- preserve fixed semantic-suggestion reservation and exhaustive coverage;
- replace old analysis-context/event/diagnostic names;
- keep one-window and multi-window behavior identical except window count and
  strategy literal.

Do not yet change atomic range validation in this ticket; use v4-shaped valid
outputs so orchestration can be proven independently.

Tests prove:

- stale/edited/client-supplemented plans fail;
- unchanged frozen plan reaches every operation byte-equivalently;
- a fitting corpus makes one extraction plus synthesis;
- a larger corpus makes every required extraction plus synthesis;
- every message appears exactly once;
- retrieval mode/hits do not change message coverage;
- exact plan overhead affects token/window calculation;
- one/many outputs share one strict result shape;
- stage failure and cancellation remain terminal;
- no old route/operation/path is invoked.

Gate: unified conversation, window, token, streaming, and cancellation tests
pass.

## QPA1-500 - Independent range validation and partial completion

Implement file 04 completely:

- two-stage extraction parser;
- strict atomic envelope;
- independent exact range schema;
- ordered semantic validation;
- one deterministic endpoint-swap normalization;
- accepted/rejected internal result;
- deterministic accepted-range IDs;
- validation summary, events, observability, debug capture, and final partial
  status.

Integrate it without weakening generic strict model parsing for other
operations.

Tests must include:

- three valid ranges plus one fabricated ID yields three accepted, one
  rejected, and partial completion;
- a malformed first/middle/last range does not poison valid siblings;
- missing/extra/wrong-type range fields are locally rejected;
- unknown start/end IDs;
- wrong thread and cross-thread range;
- reversed valid endpoints are swapped and reported;
- ambiguous/unknown endpoints are never repaired;
- duplicate exact interval keeps first and rejects later duplicate;
- overlapping nonidentical ranges both survive;
- all proposed ranges rejected still synthesizes with partial status;
- structurally malformed envelope still fails the operation;
- accepted IDs are deterministic regardless concurrent window completion;
- rejected ranges never enter ledger, compaction, findings, overlap, or
  evidence counts;
- normal logs are content-free and active debug capture is exact.

Use a synthetic fixture shaped like the observed MiniMax failure. Do not copy
private corpus text or depend on `.tmp` artifacts.

Gate: focused validator, ledger, stream, concurrency, and observability tests
pass.

## QPA1-600 - Answer-oriented synthesis and findings

Implement file 05:

- revised extraction, compaction, and synthesis prompts;
- remove global contradictory-evidence instruction;
- remove compaction dispositions;
- final categorical relevance dispositions;
- structured findings;
- strict finding/disposition validation;
- all accepted ranges preserved in the final ledger;
- answer-relevant retrieval diagnostics;
- partial-validation warning supplied to synthesis.

Tests prove:

- every accepted range receives one ordered disposition;
- direct/context/not-responsive records all remain returned;
- findings cite only accepted direct/context IDs;
- each finding includes direct evidence;
- not-responsive IDs cannot appear in findings;
- zero direct evidence requires zero findings;
- compaction preserves every ID and makes no final relevance decision;
- direct and forced-compaction paths return the same synthesis schema;
- prompts contain exact plan, answer-oriented policy, exhaustive extraction,
  and no generic contradiction requirement;
- no numeric score/rank/confidence is added;
- synthesis failures are noisy and never default-filled.

Add a deterministic high-recall fixture containing real conflicts plus
cooperative on-topic noise. The fake synthesis result must classify conflicts
as direct and cooperative passages as not responsive while preserving both.

Gate: prompt, synthesis, ledger, compaction, and retrieval-diagnostic tests
pass.

## QPA1-700 - Admin, operational visibility, and Python result display

Update the server-rendered admin:

- explain the universal planning step and exact client/server boundary;
- show exactly five operation cards and four product routes;
- replace retrieval-terms card with analysis planning;
- expose planner model profile, prompt, response schema, reasoning,
  temperature, output budget, retry, timeout, and paid synthetic test;
- explain `none|semantic_ranges`;
- show exact extraction, compaction, and synthesis schemas;
- explain high-recall extraction and categorical synthesis dispositions;
- display content-free process totals/recent warnings for accepted, rejected,
  normalized, complete, and partial ranges;
- preserve next-request activation with no restart;
- remove old fields/help/text.

Update Python test UI:

- human-readable planning progress;
- visible partial-validation warning and rejected count;
- findings and complete ledger rendering;
- elapsed timer continues through planning/extraction/compaction/synthesis and
  terminal handling;
- only a terminal completed result persists, retaining its explicit partial
  status.

Headless browser/TestClient tests must save, validate, activate, invoke, inspect,
and roll back planner/retrieval settings without restart. Every control must
affect runtime.

Gate: admin, browser, Python integration, progress, and persistence tests pass.

## QPA1-800 - Regression, boundaries, and mixed load

Update the experiment runner to v4 names/contracts without preserving a second
product workflow. Run and fix all deterministic tests.

Add mixed load containing:

- concurrent plan calls;
- semantic query embeddings and local lookup;
- one-window and multi-window analyses;
- complete and partial range-validation results;
- forced compaction;
- admin reads;
- cancellation.

Assert:

- configured provider/embedding/window bounds;
- event-loop responsiveness;
- immutable per-request snapshots;
- exact monotonic streams;
- no content persistence outside active debug capture;
- no EVW writes;
- all usage attempts accounted;
- partial status preserved end to end.

Run static boundaries proving:

- exactly four product POST routes;
- server imports no EVW/client package;
- client owns no provider/model/prompt/window/RRF/retry/planning policy;
- no Flutter/EVW diff;
- no forbidden v3 runtime residue except documented migration tests/history.

Gate: complete deterministic suite, explicit scale test, compile, package
boundaries, and `git diff --check` pass.

## QPA1-900 - Live synthesis proof and closeout

After every local gate passes, execute file 09 exactly.

Required outcomes:

- one full GLM large-corpus planning/extraction/synthesis run;
- at least six windows;
- active exact debug capture;
- complete preserved plan, prompts, range validation, ledger, findings,
  dispositions, answer, usage, and timing artifacts;
- explicit review of whether synthesis distinguishes conflict from cooperative
  on-topic noise;
- exact partial-range behavior proven locally from the MiniMax-shaped fixture;
- no automatic provider reruns or provider fallback;
- server/capture/process cleanup;
- final deterministic regression after live work.

Update README/manual test as needed and create `closeout_report.md` containing
every ticket/gate, changed/deleted files, exact commands/results, migration,
route/operation inventory, live artifacts and answer, quality findings,
partial-validation proof, test totals, residual risks, and lean human manual
test instructions.

Gate: all mandatory local criteria pass and the live result or exact external
provider blocker is documented without invented success.

