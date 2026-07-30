# Authoritative ticket stack

Execute sequentially. Complete implementation, focused tests, relevant
regression, residue scan, and `execution_log.md` evidence before beginning a
dependent ticket. Update or delete conflicting old tests in the same ticket
that changes their production contract.

## RPV1-000 - Baseline, authority, and destructive-gate inventory

Read repository `AGENTS.md` and this complete packet. Inspect:

- dirty worktree, branch, HEAD, and upstream without modifying them;
- running server/client/diagnostic processes and ports;
- active configuration/schema and model assignments with secrets redacted;
- current product routes;
- synthesis prompt/schema/parser/post-validation/error mapping;
- extraction envelope and range validator;
- window task exception behavior;
- compaction failure behavior;
- server/client stream contracts;
- Python result parser/workflow/UI;
- live/experiment scripts;
- every obsolete literal from file 07.

Run and record baseline:

```powershell
.\.venv\Scripts\python.exe -m compileall -q server message_evidence_workstation scripts tests
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\verify_package_boundaries.py
git diff --check
```

If full pytest has documented deselections/scale markers, record and run their
relevant explicit commands. Do not make real provider calls.

Record overlapping user changes in every expected file. Record the latest GLM
failure artifact path if present, without copying private transcript content.

Gate: complete inventory, exact baseline, no unexplained mutation.

## RPV1-100 - New contracts and obsolete disposition deletion

Implement file 03 contracts:

- new model synthesis output;
- new public result items, unclassified evidence, unverified statements,
  synthesis validation, warnings, coverage, status, and answer-source models;
- new stream events;
- evidence validation unavailable-window fields;
- remove all disposition classes/literals;
- remove direct-only finding invariants;
- remove obsolete generic ledger-bijection error;
- update schema registry;
- remove arbitrary synthesis answer cap.

Use strict public contracts. Do not fill omitted model fields with production
defaults. Model-output salvage is implemented in RPV1-200.

Update configuration default prompt and atomic stored-prompt migration/
activation validation per file 03. Decide and record whether a control-schema
bump is mechanically required; the packet preference is no bump unless needed
for atomic/auditable migration.

Tests:

- exact valid new model/public/event shapes;
- missing/extra/wrong/coerced public fields;
- each enum;
- raw versus structured versus unavailable answer-source invariants;
- verified/unverified subset invariants;
- status consistency;
- long synthesis content beyond 20,000 characters;
- old shapes/literals rejected;
- configuration settings/secrets preserved;
- custom obsolete prompt activation rejected rather than silently overwritten;
- known default prompt migrated;
- rollback/restart/clean control-store close.

Gate: focused contracts/config/store tests pass; old runtime literals rejected.

## RPV1-200 - Result-preserving synthesis parser and citation verifier

Implement a cohesive synthesis inspection/assembly module from files 03-04.

It must:

- retain raw provider content;
- parse exact schema when possible;
- perform only permitted fence/object normalization;
- salvage known result components independently from parseable nonconforming
  objects;
- preserve readable non-JSON content as raw answer;
- verify each result citation independently;
- split reported/verified/unverified IDs;
- preserve mixed-citation findings;
- isolate all-unverified statements from corpus-backed results;
- group high then lower, preserving model order;
- retain unknown classifications as unclassified;
- append every synthesis-omitted ledger range to unclassified evidence;
- derive warnings and completion status from facts;
- never raise an ordinary conformance warning as terminal failure.

Remove old `validate_dispositions`, `validate_findings`, and synthesis-coupled
ledger assembly.

Tests:

1. exact new synthesis is `complete`;
2. a synthetic shape matching the latest GLM contradiction returns useful
   output rather than failing;
3. high results precede lower;
4. model order is stable inside each group;
5. mixed valid/fabricated citations preserve valid linkage and statement;
6. all-fabricated citations become unverified statements;
7. duplicate citations are normalized and warned;
8. missing/unknown probability is unclassified, not dropped;
9. omitted ledger ranges appear in canonical order;
10. fenced JSON is normalized and raw content preserved;
11. readable prose is `raw_synthesis_output`;
12. parseable partial object salvages useful components;
13. malformed JSON is not heuristically rewritten;
14. zero-result structured answer survives;
15. long output survives;
16. no fabricated ID enters verified results/ledger/navigation.

Use synthetic IDs/text. No private corpus fixtures.

Gate: focused result-validation tests pass and no synthesis warning can erase
readable content.

## RPV1-300 - Source-integrity range salvage and correction

Implement file 04 extraction behavior:

- dedicated top-level extraction salvager;
- retain strict generic model parsing elsewhere;
- independently validate every range;
- derive authoritative thread from valid endpoints;
- correct wrong declared thread when endpoints unambiguously agree;
- correct reversed endpoints under the existing deterministic contiguous rule;
- preserve real ranges with missing model summary/relevance as source ranges
  with explicit description warnings, not fabricated text;
- reject only unknown, cross-thread, discontinuous, or ambiguous ranges;
- preserve valid siblings;
- all-invalid parseable envelope remains usable;
- deterministic range IDs remain window-order based.

Tests:

- valid siblings around malformed first/middle/last entries;
- unknown start/end;
- wrong declared thread corrected;
- valid endpoint reversal corrected;
- cross-thread rejected;
- discontinuity rejected;
- exact duplicate keeps first and reports later duplicate;
- overlapping nonidentical ranges survive;
- malformed uncertainty/extra top-level fields warn without losing ranges;
- missing summary/relevance retains source identity;
- all-invalid parseable envelope yields usable partial window;
- non-JSON envelope is machine-unusable;
- normal logs are content-free; active debug capture is exact.

Gate: focused range/ledger/debug tests pass.

## RPV1-400 - Isolated windows, targeted retries, and partial coverage

Refactor orchestration per file 05:

- typed completed/unavailable window outcomes;
- one ordinary window failure cannot cancel completed/sibling windows;
- targeted retry for structurally unusable window output;
- existing provider retries remain visible;
- exhausted window becomes unavailable;
- continue all remaining windows;
- exact unavailable-window coverage reaches synthesis;
- ledger builds from valid completed outputs;
- range IDs remain independent of task completion order;
- partial result status derives correctly.

Do not retry a window merely because it returned zero ranges or some rejected
ranges. Retry only machine-unusable top-level output or configured transport
failure.

Tests:

- one malformed window succeeds on targeted second attempt;
- retry event identifies exact window/attempt;
- one exhausted window plus good siblings returns `partial`;
- concurrent sibling tasks survive failure;
- completed output is not called twice;
- every planned window has one terminal outcome;
- deterministic range IDs under out-of-order completion;
- all windows unavailable produces hard failure only after attempts;
- all windows completed with zero evidence still synthesizes;
- cancellation remains cancellation;
- every attempt is accounted.

Gate: orchestration/resilience/stream/accounting tests pass.

## RPV1-500 - Synthesis receipt, raw fallback, and compaction preservation

Integrate the RPV1-200 parser into the shared provider runtime and unified
conversation:

- obtain raw synthesis content without duplicating provider transport;
- emit `ledger_synthesis_received` before conformance inspection;
- readable content always reaches terminal completed result;
- readable schema-invalid content is not retried automatically;
- empty/absent synthesis retries only synthesis;
- exhausted synthesis returns `partial` ledger/unclassified evidence;
- no upstream planning/window call repeats;
- compaction output may reorder known IDs deterministically;
- unusable compaction stops and preserves original ledger;
- original-ledger overflow after compaction failure returns partial ledger-only
  result;
- exact events/warnings/usage/debug records.

Tests:

- readable malformed synthesis completes with warning;
- latest GLM-shaped response completes with warning;
- empty first synthesis retries only synthesis and second succeeds;
- exhausted synthesis returns ledger-only partial result;
- no ledger and no usable window output is hard failure;
- compaction missing/unknown/duplicate IDs never modifies canonical ledger;
- compaction failure preserves every original range;
- direct and compacted paths share one result contract;
- `ledger_synthesis_received` occurs on provider success even when validation
  warns;
- terminal completed contains answer whenever nonblank content was received;
- no hidden provider/model fallback.

Gate: conversation/compaction/runtime/stream tests pass.

## RPV1-600 - Prompts, admin, observability, and accounting

Implement file 06 server work:

- new extraction/compaction/synthesis prompts;
- prompt migration/activation behavior finalized;
- human admin explanations and exact new schema;
- remove disposition UI/help;
- result-preservation process metrics;
- precise warning and hard-error mapping;
- distinguish provider success, synthesis receipt, validation warnings, and
  final request status;
- preserve next-request activation with no restart;
- preserve temporary debug capture and content-free ordinary logs.

Admin/browser tests must:

- show exactly the new categories/behavior;
- show no obsolete disposition text;
- edit/save/validate/activate the synthesis prompt and see it on next request;
- show exact model schema;
- show warning/partial counters after synthetic requests;
- preserve CSRF, masking, rollback, paid-test warning, and debug controls;
- prove every editable control is real.

Observability tests prove warning codes/counts without message/question/model
content leakage. Accounting includes all failed/retried/successful attempts.

Gate: prompt/admin/browser/observability/accounting tests pass.

## RPV1-700 - Python test equipment and diagnostic runners

Update only current Python gateway/workflow/UI and scripts per file 06:

- strict new event/result parser;
- high/lower/unclassified/unverified rendering;
- visible divider;
- warnings without failure popup;
- verified-ID-only navigation;
- progress and elapsed timer through retries/synthesis/validation;
- partial and warning outcomes persist as visible successful history;
- raw synthesis is presented/persisted as the visible answer only;
- no debug/provider internals persisted in EVW;
- runners write actual answers and all sections for review;
- no automatic expensive rerun.

Tests:

- exact new result accepted; old result rejected;
- warning and partial terminal events are successful;
- high/lower visual ordering;
- lower/unclassified results visible;
- fabricated ID cannot navigate;
- elapsed timer/progress remain active;
- raw synthesis displayed;
- ledger-only partial displayed;
- no EVW WAL/content side effect beyond existing visible-history contract;
- runners preserve artifacts and do not rerun.

Do not expand Python product behavior or revive deleted modules.

Gate: gateway/workflow/UI/runner tests pass.

## RPV1-800 - Full regression, scale, and residue proof

Run all deterministic tests and fix real failures:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Run explicit scale/mixed-load/browser tests if deselected by default.

Mixed load includes:

- concurrent planning calls;
- embeddings/local retrieval;
- one-window complete;
- multi-window complete-with-warnings;
- one unavailable-window partial;
- raw synthesis fallback;
- synthesis-unavailable ledger result;
- forced compaction failure/preservation;
- admin reads;
- cancellation.

Prove:

- bounded queues/concurrency;
- event-loop responsiveness;
- request-local immutable config snapshots;
- monotonic exact streams;
- no content persistence outside explicit debug capture/visible client result;
- no EVW writes from server;
- every provider attempt accounted;
- no real provider calls;
- no large embedding rebuild.

Run:

```powershell
.\.venv\Scripts\python.exe -m compileall -q server message_evidence_workstation scripts tests
.\.venv\Scripts\python.exe scripts\verify_package_boundaries.py
git diff --check
```

Run the file-07 obsolete-literal scan. Allowed hits are historical packet
documents and explicit migration-input tests only.

Gate: all local tests/gates pass with no known in-scope defect.

## RPV1-900 - One live GLM proof and closeout

Only after RPV1-000 through RPV1-800 pass, execute file 10 exactly.

Use existing configured GLM 5.2 credentials and the established large revision
4 working corpus. One live sequence is authorized. Existing configured
provider retries may occur; do not automatically repeat the complete sequence.

The run must prove:

- readable synthesis is returned regardless of conformance warnings;
- high results precede lower results;
- every accepted range remains inspectable;
- fabricated IDs, if any, are isolated;
- lower/unclassified results remain visible;
- warning/partial status is not a failure popup;
- complete usage/timing/artifacts survive;
- server/config/debug/process cleanup.

Run final deterministic regression afterward. Create `closeout_report.md` with:

- every ticket/gate;
- changed/deleted files;
- exact commands/results;
- config/prompt migration;
- final contract/event/error inventory;
- source-integrity and result-preservation proofs;
- live actual answer/artifact paths and quality assessment;
- debug stop/flush and config restoration;
- no-write EVW/WAL evidence;
- factual residual risks;
- lean manual test instructions.

Gate: every mandatory local criterion passes and live outcome or exact external
provider blocker is documented without invented success.

