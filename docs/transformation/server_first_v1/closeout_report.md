# Server-First V1 closeout report

Date: 2026-07-22

## Ticket disposition

| Ticket | Disposition |
|---|---|
| SFV1-000 | Complete — baseline, inventory, log, expected-red route test |
| SFV1-100 | Complete — immutable SQLite control plane and usage ledger |
| SFV1-101 | Complete — Fernet secrets and one-shot legacy importer |
| SFV1-102 | Complete — lifespan snapshots and bootstrap activation |
| SFV1-200 | Complete — strict v1 contracts and schemas |
| SFV1-201 | Complete — snapshot-owned editable prompts |
| SFV1-300 | Complete — async provider and exact accounting |
| SFV1-301 | Complete — bounded queues, retry policy, circuits |
| SFV1-302 | Complete — redacted events, metrics, centralized errors |
| SFV1-400 | Complete — FastAPI/Jinja admin foundation |
| SFV1-500 | Complete — keyword expansion route |
| SFV1-510 | Complete — deterministic evidence ledger |
| SFV1-511 | Complete — unified conversational orchestration |
| SFV1-600 | Complete — streamed server-owned embeddings |
| SFV1-700 | Complete — admin persistence/tests/reset integration |
| SFV1-800 | Complete — Python v1 gateway |
| SFV1-801 | Complete — one-shot scoped conversation harness |
| SFV1-802 | Complete — keyword-expanded local FTS harness |
| SFV1-803 | Complete — streamed/resumable embedding harness |
| SFV1-900 | Complete — deleted v2/Qt/legacy client architecture |
| SFV1-901 | Complete for deterministic/local gates; Gate K executed and stopped on configured-provider failures |

## Acceptance commands and results

- `python -m compileall -q server message_evidence_workstation tests` — PASS.
- `python scripts/verify_package_boundaries.py` — PASS.
- `python -m pytest -q --basetemp .tmp/pytest-sfv1-final` — PASS, 31 passed,
  1 known Starlette/httpx deprecation warning.
- `git diff --check` — PASS; only existing Git LF/CRLF warnings.
- Route enumeration — exactly `POST /v1/keyword-expansion`, `POST
  /v1/conversational-analysis`, `POST /v1/embeddings`, private `/admin/` and
  `/admin/*`, and `/internal/live`. `/docs`, `/redoc`, `/openapi.json`, `/v2`,
  and capabilities routes are absent.
- Control plane: `tests/test_sfv1_control_store.py` — 7 passed, including
  schema allowlist, append-only usage triggers, activation/rollback/restart,
  secret round-trip, incomplete import, bootstrap, and corruption.
- Contracts/provider/resilience/admin/ledger/conversation/embedding focused
  tests — all included in the 31-test result above.
- Stream contract replay: every emitted conversation and embedding event was
  parsed by `parse_ndjson_event`; monotonic sequences and terminal envelopes
  passed.
- 10,000 synthetic embeddings in one public request — HTTP 200, 941 NDJSON
  lines, 313 internal batches, completed terminal event, approximately 0.31 s
  under the deterministic fake model.
- Twelve-user mixed ASGI load — 12/12 HTTP 200 across keyword, whole
  conversation, embeddings, and concurrent admin reads; p50 16.73 ms, p95
  19.52 ms, max 84.30 ms under controlled fakes.
- Copied V14 fixture: `python scripts/verify_evw_v14.py
  .tmp/sfv1-fixture-copy.evw` — PASS. The source EVW was not modified.
- Gate K live smoke: five of six explicit admin operation tests passed;
  `ledger_reduction` returned safe provider status `HTTP 503` with no retry or
  fallback; bounded conversation emitted terminal `MODEL_OUTPUT_INVALID` after
  strict validation; bounded embedding smoke completed successfully.

## Final API and startup

Admin URL: `http://127.0.0.1:8710/admin/`

Stable server command:

```powershell
python -m server
```

Temporary Python harness command:

```powershell
python -m message_evidence_workstation.app `
  --db C:\path\to\workspace.evw `
  --dataset C:\path\to\normalized_dataset
```

Manual end-to-end sequence: start the server; open `/admin/`; complete every
operation, embedding, global, and secret field; validate and explicitly test a
draft operation; save and activate; start the Python harness against a copied
V14 EVW; run FTS5, keyword-expanded FTS, conversation, and embedding build;
observe NDJSON progress; confirm local history/vector commits; induce a
terminal stream failure and rebuild to resume missing local IDs.

## Configuration migration and secrets

The synthetic legacy-import tests passed both branches: complete mapping
creates an encrypted active version and replaces the source with a redacted
receipt; incomplete mapping preserves the source byte-for-byte and exposes a
bootstrap draft. No real API key was printed, logged, stored in test output,
or included here.

The default user state directory's historical `server.json` was imported
through the packet-authorized migration path. Active configuration version 1
is encrypted in `control.sqlite3`; the legacy source is now a redacted receipt.
No `EVW_SERVER_MASTER_KEY` environment value was required because the local
state-directory master key was available through the supported secret manager.
No credential value was printed, logged, or written to this report. Gate K was
executed, but the configured provider returned HTTP 503 for `ledger_reduction`
and non-schema-valid output for the bounded conversation; the server correctly
made no fallback calls. A literal
`python -m server` attempt was also unable to bind 8710 because preexisting
process PID 28952 owns that loopback port; that process was not terminated.
An isolated Uvicorn startup on 8711 passed `/internal/live` and `/admin/` with
a fresh state directory.

## Deleted legacy paths and proof

Deleted: `server/gui.py`, `server/routing.py`, `server/prompt_set_v2.json`,
`tests/test_server_v2.py`, and the old v2 EVW integration test. The gateway no
longer has capabilities, v2, whole/window/retrieval/ledger public methods; the
client has no server/model/legacy-model imports. Recursive production scans
outside packet/history folders found no old v2 routes, Qt server path, legacy
router import, or client conversational session symbols.

## Final file map

`server/app.py`, `contracts.py`, `config_store.py`, `config_service.py`,
`admin.py`, `templates/admin.html`, `provider.py`, `resilience.py`,
`token_accounting.py`, `conversation.py`, `evidence_ledger.py`,
`embeddings.py`, `observability.py`, `prompts.py`, and `__main__.py` form the
lean server control plane. The Python harness uses
`message_evidence_workstation/client_api/gateway.py` and the local
`services/client_workflows.py` path only.

## Deferred work

Only the packet exclusions remain deferred: Flutter server integration and UI,
EVW schema/migrations, authentication/accounts, billing/subscriptions/BYOK,
public internet exposure, durable jobs/resume, and provider fallback chains.

The only demonstrated remaining Gate K issue is external configuration
compatibility/capacity: the configured provider must serve `ledger_reduction`
without HTTP 503 and return the strict conversational v1 output schema. The
packet forbids hiding either issue with fallback or repair.

## 2026-07-22 corrective audit and final verification

This section supersedes the earlier test counts and Gate K observations above.
The post-executor audit corrected production behavior instead of weakening the
packet gates:

- all six operation prompts now specify the exact JSON contract and active
  configuration version 2 contains those prompts; version 1 is superseded and
  draft version 3 is the editable copy;
- one strict model execution/accounting path now handles all chat operations;
- conversation planning includes retrieval payload cost, exact evidence text,
  deterministic hierarchical range coverage, bounded concurrency, visible
  queue/retry events, cancellation, and immutable config snapshots;
- embedding workers now use bounded reservation-aware admission. Activation
  drains both running and already accepted queued work, atomically swaps a
  validated model, and reopens the prior model if candidate activation fails;
- a FIFO cancellation race that could release an ungranted product lease and a
  concurrent admin-draft creation race were found by the twelve-user gate and
  fixed in the production paths;
- expanded keywords are local FTS alternatives (`OR`); ordinary FTS query terms
  remain conjunctive (`AND`);
- failed explicit admin tests now show raw model output only in that response,
  append a failure usage row and content-free audit row, and never persist or
  log the raw response;
- the Python boundary gate now uses a real Uvicorn socket, strict gateway,
  actual V14 EVW, local FTS5/sqlite-vec, both server-selected conversation
  strategies, embedding stream, and local history persistence.

Final gates:

- compile, package boundaries, and `git diff --check`: PASS;
- Python non-scale suite: 84 passed, 2 scale tests deselected, one known
  FastAPI/Starlette TestClient deprecation warning;
- Python scale suite: 2 passed (10,000-item public embedding workload and
  twelve-user mixed load), 84 deselected;
- Flutter dependency resolution, static analysis, and tests: PASS, 2 tests;
- Flutter Windows release build: PASS;
- Flutter native compatibility probe against
  `.tmp/sfv1-fixture-copy.evw`: 28 passed, 0 failed;
- V14 verifier: PASS;
- final wheel: PASS and contains the server admin template, server runtime, and
  strict client gateway.

The current headless server is running on `127.0.0.1:8710`, active version 2,
with the configured 384-dimensional embedding model loaded, accepting work,
and no in-flight or queued workload. Live strict-gateway keyword and embedding
requests passed. Explicit live operation tests passed for retrieval terms,
window evidence extraction, ledger reduction, and ledger synthesis. A later
keyword test passed after an earlier malformed-output failure was correctly
rejected. Whole-corpus analysis received provider HTTP 503; this remains an
external model availability/configuration fact and was not hidden with retry,
fallback, output repair, or a substitute model.

The visual-only acceptance sequence is `manual_test.md`; it contains no
dependency installation or automated-test work for the user.
