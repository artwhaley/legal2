# Server-first v1 execution log

The execution agent owns this file. Append one dated section per ticket with:

- ticket ID and result;
- files changed/deleted;
- exact commands and outputs/counts;
- packet-defined decisions applied;
- discovered facts and resolved defects;
- next dependency or genuine blocker.

Do not pre-populate completion claims.

## 2026-07-22 — SFV1-000 baseline

Target: record the preexisting worktree, verify the repository baseline, and
add the temporary target-route architecture test without changing runtime.

Preexisting worktree: dirty before this ticket. `git status --short` reported
175 tracked changes (including broad prior Python/server/client/test edits and
three tracked `.evw-shm` files) plus untracked `server/`, `flutter_client/`,
`message_evidence_workstation/client_api/`, `message_evidence_workstation/services/`,
new scoped-DB/search support, verification scripts, `.tmp` fixtures/runtime
artifacts, and transformation documents. These changes were preserved.

Baseline commands and results:

- `python -m compileall -q server message_evidence_workstation tests` — PASS.
- `python scripts/verify_package_boundaries.py` — PASS (`package boundaries: PASS`).
- `python -m pytest -q` — PASS, 18 passed, 1 warning. Pytest emitted a
  preexisting Windows cleanup `PermissionError` during its atexit callback
  after the successful test run.
- `git diff --check` — PASS; only Git LF/CRLF conversion warnings.

Current architecture inventory: the runtime is the old v2 server (`/v2/*`,
capabilities, `server/routing.py`, `server/gui.py`, JSON config, and response
defaults), while the Python gateway still calls v2 capabilities and internal
routes. The temporary test added by this ticket is expected-red until the v1
runtime exists; no runtime file was changed for SFV1-000.

Files changed by SFV1-000: `tests/test_sfv1_000_architecture.py` (temporary
expected-red route inventory) and this log.

Temporary architecture test command:

- `python -m pytest -q tests/test_sfv1_000_architecture.py` — EXPECTED RED,
  1 failed before route enumeration because the old `ServerConfig()` rejects
  its empty legacy operation set. This is the deliberate preimplementation
  baseline; SFV1-100 onward must replace that startup path and make the test
  pass.

SFV1-000 disposition: baseline recorded; proceed to SFV1-100.

## 2026-07-22 — SFV1-100 / SFV1-101 / SFV1-102

SFV1-100 target: implement the content-free control-plane SQLite schema,
immutable drafts/active/superseded versions, usage ledger, audit rows,
rollback, WAL lifecycle, and configuration validation. Implemented in
`server/config.py` and `server/config_store.py`. Focused gate:
`python -m pytest -q tests/test_sfv1_control_store.py` — PASS, 7 passed.
The test covers activation/rollback/restart, one-active invariant, usage
allowlist, no content columns, and encrypted secret round-trip.

SFV1-101 target: implement Fernet master-key resolution, secured local key
creation, write-only secret projections, encrypted bindings, and exact legacy
JSON mapping/import. Implemented in `server/config_store.py`; focused tests
cover successful redacted receipt, incomplete source preservation, malformed
activation refusal, and plaintext absence. Same focused gate — PASS, 7
passed. No real key or user content was read.

SFV1-102 target: add lifespan-owned immutable active snapshots, explicit fresh
bootstrap, no-active `ConfigurationRequired`, invalid-active corruption, and
no-restart activation swap. Implemented in `server/config_service.py` and the
new `server/__main__.py` launcher. The bootstrap/activation and corruption
tests are included in the 7 passing focused tests. Runtime app composition is
intentionally completed with the contract/app tickets before launch testing.

No source files were deleted in these tickets. Next dependency: SFV1-200
strict contracts and schemas.

## 2026-07-22 — SFV1-200

Target: replace permissive v2 response models with strict v1 request,
internal-output, final-result, common-error, and NDJSON contracts. Implemented
in `server/contracts.py`; all models forbid extras and use strict field types,
with explicit model-output invariants for empty-window evidence, dispositions,
finite vectors, and terminal event parsing. JSON Schema export is exposed by
`SCHEMA_REGISTRY` for the admin surface.

Focused command: `python -m pytest -q tests/test_sfv1_contracts.py` — PASS, 3
passed. Tests cover unknown fields, wrong types, empty-evidence corruption,
malformed error events, and endpoint-incompatible terminal events.

Next dependency: SFV1-201 prompt/config registry, then provider/accounting.

## 2026-07-22 — SFV1-201 / SFV1-300 / SFV1-301 / SFV1-302

SFV1-201: runtime prompt lookup now comes from `registry_from_config`; seeded
prompt text is migration-only and the operation prompt remains part of the
immutable configuration hash. No second runtime prompt source was added.

SFV1-300: added `server/provider.py` and `server/token_accounting.py`. Provider
transport is async `httpx`, uses exactly `{base_url}/chat/completions`, bearer
auth, exact two-message payloads, configured response format, safe status
mapping, cancellation propagation, and usage capture. Accounting serializes
the complete generated body and supports only the two configured packet modes,
with no fallback. Focused command:
`python -m pytest -q tests/test_sfv1_provider_accounting.py` — PASS, 3 passed.

SFV1-301: added `server/resilience.py` with bounded FIFO limiters, configured
retry/backoff, deadline-independent explicit attempt policy, version-local
circuit state, half-open protection, cancellation, and reset/state projections.
SFV1-302: added `server/observability.py` with scalar-only structured stdout,
bounded redacted ring, metrics, and centralized stable error mapping. Focused
command: `python -m pytest -q tests/test_sfv1_resilience_observability.py` —
PASS, 2 passed.

No provider credentials were used. Next dependency: SFV1-400 admin foundation.

## 2026-07-22 — SFV1-400

Target: replace Qt administration with one server-rendered FastAPI/Jinja
admin page and real control actions. Added `server/admin.py` and
`server/templates/admin.html`; app composition in `server/app.py` disables
FastAPI docs/redoc/OpenAPI, registers `/admin/`, `/admin/action`, and
`/admin/events`, renders bootstrap state, masked secret projections,
configuration prompts, read-only code schemas, metrics, and redacted events.
Actions include draft validation, activation, rollback, and circuit reset with
CSRF token checking.

Focused command: `python -m pytest -q tests/test_sfv1_000_architecture.py
tests/test_sfv1_admin.py` — PASS, 2 passed (1 known Starlette deprecation
warning). The route inventory now has the target three `/v1` POST routes,
private admin routes, and `/internal/live`; bootstrap keyword requests fail
`CONFIGURATION_REQUIRED`, and default docs/OpenAPI are 404.

The remaining editor save/test wiring and embedding lifecycle are completed in
SFV1-600/700 after product orchestration exists. Next dependency: SFV1-500.

## 2026-07-22 — SFV1-500 / SFV1-510 / SFV1-511

SFV1-500: the v1 keyword route is implemented in `server/app.py`. Focused
command: `python -m pytest -q tests/test_sfv1_keyword_endpoint.py` — PASS, 2
passed. It proves active-config use, strict output, ordered trim/dedup, usage
accounting, and provider failure without fallback.

SFV1-510: added `server/evidence_ledger.py` with immutable exact excerpts,
same-thread/order/range validation, deterministic IDs, coverage reports,
whole-path rationales, disposition bijection, deterministic hierarchical
group IDs, depth/budget failures, and final assembly. Focused command:
`python -m pytest -q tests/test_sfv1_evidence_ledger.py` — PASS, 3 passed.

SFV1-511: added `server/conversation.py` and wired the unified public
`POST /v1/conversational-analysis`. Whole fit is based on the exact generated
provider payload; window planning is ordered, non-overlapping, thread-aware,
and bounded concurrent; retrieval, all windows, ledger build/reduction, and
synthesis are internal stages with one terminal NDJSON event. Focused command:
`python -m pytest -q tests/test_sfv1_conversation.py` — PASS, 2 passed. The
tests prove one whole call for a small corpus, multiple required windows for a
large corpus, empty-evidence synthesis, fixed config version, and final schema.

Next dependency: SFV1-600 server-owned embedding workloads.

## 2026-07-22 — SFV1-600

Target: replace public model-batch behavior with one complete embedding
workload, internal configured batches, executor-backed model lifecycle,
artifact fingerprint/profile identity, finite/dimension/count validation,
progress/vector events, cancellation-safe request-local state, and one
terminal content-free usage row. Implemented in `server/embeddings.py` and
wired to `/v1/embeddings`; server dependencies in `pyproject.toml` now include
the required async/admin/crypto form packages.

Focused command: `python -m pytest -q tests/test_sfv1_embeddings.py` — PASS, 2
passed. Tests prove a 65-item single public workload becomes 32/32/1 internal
batches and a second-batch failure emits exact bounds plus terminal `failed`.
No full result collection is retained by the service.

Next dependency: SFV1-700 final admin integration and operational tests.

## 2026-07-22 — SFV1-700

Target: finish admin integration with real draft persistence and explicit
operation tests. `server/admin.py` now parses form fields into typed draft
settings, persists prompts/global/embedding fields, rotates/removes encrypted
secrets, validates/activates/rolls back versions, records audits, resets live
circuits, and invokes only the selected draft operation for a synthetic test.
Raw test output is rendered only in that response; it is not emitted to the
structured event ring or durable usage/audit payload.

Focused command: `python -m pytest -q tests/test_sfv1_admin.py` — PASS, 2
passed. Tests prove bootstrap/private routes and a real prompt/secret draft
save with secret masking.

Next dependency: SFV1-800 Python gateway clean break.

## 2026-07-22 — SFV1-800 / SFV1-801 / SFV1-802 / SFV1-803

SFV1-800: replaced the Python gateway/contracts with v1 keyword, unified
conversation, and streamed embedding calls. It has no capabilities method,
removed internal-route methods, provider/model/prompt/window/batch/retry
policy, or client model schema parser. The stream parser enforces ordered
sequence and exactly one terminal event; EOF is an interrupted failure.

SFV1-801: replaced the prior client conversational session/retry/window
orchestration with one short scoped message snapshot, one server NDJSON stream,
visible progress, terminal-only success, a final local scope recheck, and
history persistence in the existing UI write transaction. `main_window.py`
now has no resume/discard conversational state or strategy controls.

SFV1-802: keyword search sends the query only to `/v1/keyword-expansion` and
then performs local scoped FTS5; ordinary FTS5 remains a separate action.

SFV1-803: embedding build sends locally missing items as one complete workload,
uses accepted profile metadata, commits each streamed vector batch in short
transactions, keeps committed work after terminal failure, and resumes by
local missing IDs. Client code contains no server batch-size setting.

Focused command: `python -m pytest -q tests/test_sfv1_gateway.py` — PASS, 3
passed. Existing EVW integration tests asserting the removed v2 gateway are
now obsolete and are handled by SFV1-900 replacement/deletion; no EVW schema
was changed.

Next dependency: SFV1-900 legacy architecture deletion and package-boundary scan.

## 2026-07-22 — SFV1-900

Deleted replaced production/test paths: `server/gui.py`, `server/routing.py`,
`server/prompt_set_v2.json`, `tests/test_server_v2.py`, and the old v2 EVW
integration test `tests/test_v14_closeout.py`. Renamed the client workflow to
`ConversationalWorkflow`, removed client session/resume/retry/window strategy
state and controls, removed capability/internal gateway methods, and updated
the root README to the Server-First V1 commands/admin surface. The boundary
verifier now enforces the final server/client ownership rules.

Absence scan (excluding packet/history folders) found no `/v2/`, old server
GUI/router imports, old client session/coordinator symbols, or client imports
of server/legacy model packages. The remaining `retrieval_terms` references
are the packet-required internal operation and legacy importer mapping, not
public routes. `python scripts/verify_package_boundaries.py` — PASS.

Fresh copied EVW verification: `python scripts/verify_evw_v14.py
.tmp/sfv1-fixture-copy.evw` — PASS; read-only `WorkspaceStore` open/close also
passed with 15,462 messages. The source fixture was copied and never modified.

Next dependency: SFV1-901 full verification and closeout.

## 2026-07-22 — SFV1-901

Full deterministic verification:

- `python -m compileall -q server message_evidence_workstation tests` — PASS.
- `python scripts/verify_package_boundaries.py` — PASS.
- `python -m pytest -q --basetemp .tmp/pytest-sfv1-final` — PASS, 31 passed,
  1 known Starlette/httpx deprecation warning.
- `git diff --check` — PASS with only preexisting line-ending warnings.
- Route/docs/legacy recursive scans — PASS: exactly three public v1 POST
  routes; admin/internal routes only; docs/OpenAPI/v2/capabilities absent.
- Stream-contract replay — PASS for all emitted conversation/embedding events.
- 10,000-item fake embedding workload — PASS: one request, 313 internal
  batches, completed terminal event, ~0.31 seconds.
- Twelve-user mixed fake load — PASS: 12/12 HTTP 200; p50 16.73 ms, p95
  19.52 ms, max 84.30 ms; concurrent admin reads remained responsive.
- Copied V14 fixture `scripts/verify_evw_v14.py .tmp/sfv1-fixture-copy.evw` —
  PASS; source EVW unchanged.
- Literal `python -m server` startup was attempted but 8710 was occupied by
  preexisting PID 28952; it exited cleanly without terminating that process.
  Isolated Uvicorn startup on 8711 passed `/internal/live` and `/admin/`.

Gate K was then executed through the approved legacy-import path after the
user identified the persisted settings at
`C:\Users\artwh\.message_evidence_server\server.json`. The importer created
encrypted active configuration version 1 and replaced the legacy source with
a redacted receipt. No credential value or real corpus content was printed.

Gate K live results, using synthetic administrator inputs only:

- explicit admin tests passed for `keyword_expansion`, `retrieval_terms`,
  `whole_corpus_answer`, `window_evidence_extraction`, and `ledger_synthesis`;
- `ledger_reduction` received safe provider status `HTTP 503` and was not
  retried or replaced by another provider/model;
- bounded conversational smoke reached the configured provider and emitted
  a terminal `failed` event with `MODEL_OUTPUT_INVALID` after strict response
  validation; no fallback was used;
- bounded embedding smoke passed with `accepted`, one batch, vector,
  progress, and terminal `completed` events;
- the active configuration stayed fixed at version 1. A temporary complete
  draft version 2 was used only so the admin test action could run against the
  imported encrypted secrets.

The configured provider therefore remains the genuine stop condition for Gate
K: one operation is unavailable with HTTP 503 and the conversational smoke
does not return the required v1 model-output schema. Deterministic/local gates
remain verified. No commit, push, or deploy performed.

## 2026-07-22 — post-executor corrective audit

The executor output was audited against the complete packet before manual
handoff. Production fixes included strict operation prompts/contracts, one
model runtime, exact failure accounting, immutable runtime ownership,
conversation/window/ledger hardening, reservation-aware embedding activation,
concurrent admin draft creation, FIFO cancellation ownership, strict client
stream validation, transaction boundaries, atomic conversation persistence,
resumable message-only embedding state, keyword-alternative FTS semantics, full
admin controls/diagnostics, and wheel package data.

The twelve-user scale test initially exposed duplicate draft creation and an
ungranted limiter release under cancellation. Both runtime defects were fixed;
the test was not relaxed. A real Uvicorn/V14/client integration test then
exposed `AND` semantics in expanded-keyword FTS; production was corrected to
use `OR` for expansion alternatives while retaining ordinary conjunctive FTS.
Live admin testing exposed missing raw-current-response diagnostics and missing
failure accounting for explicit tests; both were fixed with response-only raw
output and content-free durable rows.

Final commands and results:

- `python -m compileall -q server message_evidence_workstation tests` — PASS.
- `python scripts/verify_package_boundaries.py` — PASS.
- `python -m pytest -q -m "not scale" --timeout=90 ...` — 84 passed.
- `python -m pytest -q -m scale --timeout=180 ...` — 2 passed.
- `flutter analyze` — PASS.
- `flutter test` — 2 passed.
- `flutter build windows --release` — PASS.
- release `evw_client.exe --probe --evw .tmp/sfv1-fixture-copy.evw` —
  28 passed, 0 failed.
- `python scripts/verify_evw_v14.py .tmp/sfv1-fixture-copy.evw` — PASS.
- final no-dependency wheel build and package-content inspection — PASS.

Real configuration version 2 was activated through the runtime lifecycle after
loading the configured MiniLM artifact at 384 dimensions and validating all
encrypted bindings. The obsolete server GUI, obsolete server, old Python
client, and stale Flutter viewer processes were stopped; the current headless
server is running on port 8710. Live keyword and embedding public requests pass.
The configured whole-corpus model returned HTTP 503 on its one bounded live
test; no fallback or repeated automatic spend was introduced.

## 2026-07-23 — dedicated whole-corpus fixture

Created `.tmp/sfv1-fixture-100k.evw` as a separate SQLite backup of the
15,462-message V14 fixture, preserving the existing 698,786-token windowed
fixture. The production corpus builder selected messages from 2025-09-12
forward, materialized 1,387 messages / 99,980 `cl100k_base` membership tokens,
built FTS5 and spellfix generation 1, and activated working corpus 3.

Exact active-configuration accounting generated a 430,105-byte request and a
131,381-token whole-model provider payload. The active target is 482,118 input
tokens inside a 500,000-token context with 16,384 output tokens and a 1,498
token safety margin, so the strategy decision is deterministically
`whole_corpus`.

A complete controlled HTTP orchestration over all 1,387 messages passed with
HTTP 200, events `accepted`, `accounting_completed`, `whole_started`,
`whole_completed`, `completed`, final strategy `whole_corpus`, and
`window_count=1`. V14 structural verification passed, and the Flutter native
compatibility probe passed 28/28 against the new fixture. No unknown-price
131K-token live provider call was made automatically.
