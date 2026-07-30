# Authoritative ticket stack

Execute sequentially. A ticket may deliberately break the old v2 server or
Python harness; do not add compatibility to keep old tests green. Rewrite or
delete tests that specify removed architecture. Every ticket must satisfy its
targeted gate before the next ticket begins.

## SFV1-000 — Baseline, inventory, and execution log

Read this complete packet, repository `AGENTS.md`, current server, Python
gateway/workflows, tests, and git status. Record dirty files without reverting
them. Create `execution_log.md` with baseline commands/results. Add a temporary
architecture test enumerating the target three product routes and mark it
expected-red until implemented; do not change runtime.

Gate: baseline tests and package-boundary result recorded; no unexplained file
mutation.

## SFV1-100 — Control-plane SQLite and immutable config models

Implement `server/config_store.py`: control schema/version, explicit config
models for every field in files 01–04, WAL lifecycle, short transactions,
draft/version/activation/rollback, immutable snapshots, admin audit, and the
append-only content-free usage ledger.
Validate exactly one active version. No user-content tables. Add temp-database
tests for schema, activation atomicity, rollback, restart, corruption, and WAL.

Delete no current runtime path yet.

Gate: control-store tests pass; table/column allowlist proves no user-content
storage and usage rows are immutable.

## SFV1-101 — Secrets and verified legacy import

Add master-key resolution, secured key-file creation, Fernet encryption,
write-only secret metadata, config bindings, and the exact legacy JSON import
transaction from file 03. Tests must use temporary keys/paths and prove
plaintext never appears in DB, admin projections, logs, exception text, or
receipts. Test failed import leaves source untouched; verified import replaces
source with a redacted receipt.

Gate: secret/import tests and repository secret scan pass. Never print the real
current API key during tests or logging.

## SFV1-102 — Active configuration service and lifespan

Add a lifespan-owned configuration service that loads one validated immutable
snapshot, atomically swaps after activation, and gives each request a captured
version. Add startup/close/checkpoint handling. Startup fails loudly when no
previously active version can be loaded validly. A genuinely fresh DB starts
loopback in bootstrap mode: admin works, product routes fail
`CONFIGURATION_REQUIRED`, and first activation swaps in the snapshot without
restart. Enforce loopback bind while admin auth is disabled.

Rewrite `server/__main__.py` to use the control store. Runtime must stop reading
`server.json` except the one-shot importer.

Gate: bootstrap/first-activation tests and concurrent snapshot/activation tests
prove product blocking, no-restart activation, and old in-flight/new request
version isolation.

## SFV1-200 — Strict contracts and schemas

Rewrite `server/contracts.py` for the three public requests, NDJSON events,
common errors, and exact internal model schemas from file 02. Set all required,
forbid extras, implement the exact endpoint-specific discriminated event union,
and disable coercions that mask wrong model types. Export schemas for admin
display. Remove every default-filled response construction.

Add corruption tests for `{}`, missing fields, wrong types, extra fields,
malformed JSON, prose/fences in disallowed modes, duplicate IDs, invalid
ranges, and terminal stream semantics.

Gate: all corrupt outputs and malformed event variants fail with stable codes;
no `.get(..., default)` model response assembly remains.

## SFV1-201 — Prompt/config registry

Replace frozen prompt-file runtime with prompts from active operation config.
Seed initial prompts by importing the current prompt text, then update the
window and ledger prompts to the strict extraction/bijection schemas. Prompt
editing is config-versioned; schemas remain code-versioned/read-only.

Remove any independent prompt path after migration. Add tests proving every
operation prompt is nonblank, included in snapshot/version hashing, displayed
fully in admin projection, and paired with its exact schema.

Gate: one active prompt path and no response defaults.

## SFV1-300 — Async provider and tokenizer accounting

Replace `server/routing.py` with `server/provider.py` and
`server/token_accounting.py`. Use shared lifespan `httpx.AsyncClient`, explicit
OpenAI-compatible payloads, structured-output mode, safe provider error
parsing, provider request IDs, cancellation, strict output parsing, configured
accounting modes, complete canonical-provider-payload preflight, usage
aggregation, and nullable/complete cost estimation.

Persist each provider attempt through the required usage-ledger commit before
retry or success. Accounting failure is terminal and never repaired from logs.

Do not implement fallback or implicit tokenizer strategy changes. Mock tests
cover timeout, connect/read failures, every relevant HTTP status, cancellation,
malformed provider JSON, usage present/absent, context accounting, schema
overhead, and safety margin.

Gate: event loop remains responsive during a delayed mocked provider; no
`urllib` in server runtime.

## SFV1-301 — Queues, retries, and circuits

Implement `server/resilience.py` exactly as file 04: global admission,
per-operation FIFO bounded queues/semaphores, deadline-aware configured retry,
observable backoff, no forbidden retries, in-memory circuit states, half-open
probe, manual reset hook, and metrics projections. Configuration version scopes
all state.

Gate: deterministic fake-clock tests cover queue full/timeout, ordering,
attempt counts, backoff/jitter bounds, circuit transitions, cancellation, and
no model fallback.

## SFV1-302 — Observability and centralized errors

Implement structured stdout events, redaction, request/stage timing, token/cost
fields, recent-event ring, aggregate dashboard metrics, config audit hooks, and
central exception/status mapping. Convert FastAPI validation errors to common
shape. Add `/internal/live` with process-only semantics.

Gate: log-redaction tests inject recognizable corpus/question/key/vector/output
sentinels and prove none occur; every known failure maps to its specified code.

## SFV1-400 — Web admin foundation and complete editors

Implement `server/admin.py` and one `server/templates/admin.html`. Build the
dashboard, operation/config/prompt/schema views, embedding editor, draft
validate/save, activation, rollback, secret replace/remove, explicit test, and
circuit reset actions from file 03. Use server-rendered HTML and minimal inline
JavaScript only. Add CSRF protection using an in-memory session token even on
loopback; no account/auth system.

Every form field must map to one defined control setting; no decorative/no-op
controls. Tests exercise forms/actions and verify masked secrets/read-only
schemas. Use FastAPI TestClient for route/form units and Python Playwright with
headless Chromium for one complete JavaScript/browser workflow; these are test
dependencies, not product frontend dependencies. Do not delete Qt until final
admin gate.

Gate: all meaningful settings are visible/editable where specified; every
fixed invariant/schema is visible/read-only; browser actions work headlessly.

## SFV1-500 — Keyword expansion product endpoint

Compose the app and implement only `POST /v1/keyword-expansion` against active
snapshot/provider/resilience/accounting/strict schema. Implement exact term
normalization from file 02. No capabilities endpoint or fallback.

Gate: endpoint contract/error/retry/log/usage/config-version tests pass.

## SFV1-510 — Deterministic evidence-ledger core

Implement `server/evidence_ledger.py` independent of HTTP/provider: message and
window identity maps, strict range validation, same-thread/order checks,
duplicate detection, deterministic `r000001` IDs, exact excerpts, immutable
records, group partitioning by accounted budget, covered-ID propagation,
range-disposition bijection, final assembly including required whole-path
rationales, empty-ledger coverage, and every failure code from file 02. Never
truncate or repair.

Gate: property/fixture tests prove deterministic output, complete coverage,
stable IDs, malformed-range rejection, group recursion, depth/budget failure,
and no input mutation.

## SFV1-511 — Unified conversational orchestration

Implement `server/conversation.py` and `POST /v1/conversational-analysis`:
request integrity/preflight, exact whole fit decision, strict whole call,
retrieval assistance, deterministic no-overlap windows, bounded concurrent
window extraction, completion-order-independent ledger IDs, full/hierarchical
ledger synthesis, usage aggregation, NDJSON progress, cancellation, and final
common result. Intermediate state is request RAM only.

All windows are required. A failed required stage emits terminal failure; never
return partial answer. Use injected provider/accounting/resilience services for
tests.

Gate: small corpus uses exactly one whole call; oversized corpus uses every
window and synthesis; both return identical final schema; full failure matrix,
all-windows-no-evidence synthesis, stale/disconnect cancellation, and ledger
bijection tests pass.

## SFV1-600 — Server-owned embedding workloads

Rewrite `server/embeddings.py` and implement `POST /v1/embeddings`: request
ceilings, unique IDs, accepted metadata, internal configured batches, dedicated
executor/model lifecycle, actual-artifact fingerprint/profile ID,
finite/count/dimension validation, NDJSON vector batches/progress/terminal,
queue/cancellation, and prevalidated atomic profile swap on config activation.
Remove public model-batch rejection.

Persist one terminal content-free embedding-workload usage row before emitting
the terminal event.

Gate: tests process more than 32 and at least 10,000 synthetic items without
client batching, bound peak retained vector batches, keep event loop/admin
responsive, and identify exact failed batch bounds.

## SFV1-700 — Final admin integration and operational tests

Wire live queue/circuit/provider/accounting/embedding/config state and recent
events into the admin dashboard. Implement explicit synthetic operation tests
that use draft settings without activation and show raw output only in that
response. Verify model/config activation behavior under in-flight requests.

Gate: headless browser/TestClient admin workflow configures, tests, activates,
observes, rolls back, and never leaks a secret or user payload.

## SFV1-800 — Python gateway clean break

Only now modify the Python harness. Replace gateway contracts with the three v1
product endpoints and NDJSON parser. Remove capabilities and every method for
public internal operations. Keep server URL only. Add interrupted/malformed/
failed/completed stream tests.

Gate: Python gateway has no provider/model/prompt/batch/window/retry policy and
contains no removed route strings.

## SFV1-801 — Python conversational harness

Replace client orchestration with one scoped message snapshot and unified
stream consumption exactly as file 05. Remove client strategy/window/retrieval/
ledger/retry/session code and related UI controls. Preserve UI progress and
strict local scope recheck/persistence.

Gate: real fixture proves whole and windowed server strategies through the same
client action; no EVW transaction spans network; only completed result persists.

## SFV1-802 — Python keyword harness

Retarget keyword-expanded local FTS to v1 keyword endpoint. Prove active and
narrowed scope locally. No fallback; normal FTS remains a separate user action.

Gate: scoped keyword workflow and server failure behavior pass.

## SFV1-803 — Python embedding harness

Send all locally missing active-corpus items in one server workload, consume
metadata/vector batches, commit short local batches, handle profile changes,
show server/local counts, preserve completed vectors on terminal/interrupted
failure, and resume by resending only locally missing IDs. Delete all client
server-batch knowledge.

Gate: real V14 fixture with >32 items builds, fails after committed batches,
and resumes without duplicate/wrong-profile vectors; no long transaction/WAL.

## SFV1-900 — Delete replaced architecture

Delete Qt server GUI, v2 capabilities and public internal routes, old router,
old prompt file/runtime, old contracts, current client capabilities classes,
client conversational coordinator/retries/windows, and tests/docs that assert
them. Remove dependencies used only by deleted Qt server GUI. Keep PySide only
if the temporary Python harness still needs it.

Update root README to the new server/admin/Python-harness commands and mark old
transformation folders historical. Do not leave aliases, feature flags, dead
classes, commented code, or dual config paths.

Gate: recursive searches prove removed symbols/routes are absent outside
historical docs and this packet.

## SFV1-901 — Full verification and closeout

Run all gates in `07_acceptance_gates.md`, including 12-user mixed load, large
conversation, 10k embedding workload, provider fault matrix, control DB/WAL,
admin workflow, package boundaries, Python live integration, and log/secret
scans. Fix every failure in target architecture; do not restore deleted paths.

Complete `closeout_report.md` with ticket table, changed/deleted files, exact
commands/results, active control/config versions, public route enumeration,
live test results, measured concurrency/throughput, known external provider
limitations, and any genuine blocker.

Gate: every mandatory gate passes or executor stops under the explicit protocol
with reproducible blocker evidence.
