# Web administration, configuration, and secrets

## Administration surface

Replace `server/gui.py`; do not keep Qt as an alternate control path. Implement
one server-rendered FastAPI/Jinja page at `/admin/` with inline minimal CSS and
vanilla JavaScript for form submission, test progress, and dashboard refresh.
There is no Node, npm, React, SPA state store, or generated frontend scaffold.

Authentication is intentionally deferred, so startup must reject a non-loopback
bind while admin auth mode is `disabled`. In this phase operators reach the
page locally or through an SSH tunnel. Do not claim this is safe for public
exposure.

On a fresh install with no active configuration, start loopback in bootstrap
mode and render the complete draft editor. Product routes return
`503 CONFIGURATION_REQUIRED` until the first valid version is activated. This
is the only no-active-config state that may start. If a previously active
version exists but fails schema, secret, or semantic validation, startup fails
and reports the precise redacted control-plane error.

## Admin page sections

### Dashboard

Show:

- process uptime and active control-schema/config version;
- pending draft and last activation/rollback result;
- each internal operation's provider/model, last explicit test, circuit state,
  in-flight/queued counts, recent success/failure and latency;
- embedding model/revision/device/load state/dimensions/profile, in-flight and
  queue counts, and measured items/second;
- cumulative durable and since-process-start provider-reported/estimated token
  use, embedding workloads/items, complete/incomplete cost, and failed attempts;
- bounded recent redacted operational events.

Provider tests are explicit administrator actions because they can incur cost.
The dashboard does not continuously call paid providers.

### Operation editor

Provide one complete editor per internal operation listed in
`01_architecture_and_ownership.md`. Every meaningful server-owned field is
present. Show the fixed active request and response JSON Schemas in full,
read-only, beside the editable full system prompt. Show a generated sample
provider payload with user data replaced by placeholders.

Actions are explicit:

- `Validate draft` performs no provider call;
- `Test operation` calls only the selected draft operation with a fixed small
  synthetic payload and displays raw test output, accounting, schema result,
  latency, and safe error detail;
- `Save draft` does not activate it;
- `Activate version` atomically changes new-request behavior;
- `Rollback` creates and activates a new version copied from the chosen prior
  version; history is immutable.

Never provide “copy settings to all” because it can destroy deliberately
different endpoint policies.

### Embedding editor

Show every embedding setting, profile preview, test result, throughput, and
queue/worker state. The test embeds fixed synthetic text and verifies profile,
dimensions, normalization, finite vectors, and configured device.

### Logs and events

Show only structured, redacted events. Raw prompts/responses are visible only
inside the explicit operation test result and are never added to the recent
event ring or durable audit.

## Control-plane storage

Use a server-only SQLite database at:

```text
<state-dir>/control.sqlite3
```

Default state dir is `~/.message_evidence_server`; override with
`EVW_SERVER_STATE_DIR`. This database is not an EVW and never stores user
requests or model data.

Implement a small explicit schema in `server/config_store.py` using stdlib
`sqlite3`, foreign keys, WAL, `synchronous=FULL`, short transactions, schema
versioning, startup quick/foreign-key checks, passive checkpoint monitoring,
and clean-close truncate checkpoint. One async lock serializes config writes;
reads return immutable snapshots and do not hold transactions during provider
calls.

Run all stdlib SQLite work in one lifespan-owned single-thread control-store
executor so FULL-synchronous commits never block the event loop. Configuration,
audit, and usage writes share that ordered writer. Read-only admin aggregates
use short read connections in the same executor; product requests use captured
in-memory snapshots and never read config from SQLite on their hot path.

Required conceptual tables:

```text
control_schema_version
config_version             immutable version metadata/status/timestamps
operation_config           complete per-operation nonsecret settings/prompt
embedding_config           complete embedding settings
global_config              complete global/workflow settings
encrypted_secret           ciphertext, key version, provider label, suffix
config_secret_binding      operation/version -> secret
admin_audit                config action metadata only
usage_event                append-only provider-attempt or embedding-workload accounting
legacy_import_receipt      one-time source hash/time/result
```

`usage_event` stores only: generated event ID, client request UUID, timestamps,
config version, product endpoint, internal operation, attempt, provider/model or
embedding profile, outcome/error code, input/output tokens and usage source,
the price snapshot used, nullable estimated cost/currency, latency, safe
provider request ID, and embedding item counts. It has no text/blob/JSON payload
field and no account/user field yet. Rows are immutable and are not pruned in
this phase. Later authentication may add account ownership without changing the
provider-attempt accounting grain.

Draft edits create or update a draft version. Active versions are immutable.
Activation transaction validates all required operations/settings/secrets,
marks the old active version superseded, and marks exactly one new version
active. The in-memory snapshot swaps only after commit.

Activation effects are fixed:

- host/port changes are saved but marked `restart_required`; the current socket
  never pretends to rebind, and admin shows current versus next listener;
- chat prompt/model/provider/budget/resilience changes affect only requests
  admitted after the snapshot swap;
- embedding changes first drain accepted old-profile workloads, build and fully
  validate the candidate model/fingerprint outside any SQLite transaction, then
  commit activation and atomically swap snapshot/service; new embedding
  admission pauses with visible `EMBEDDING_RECONFIGURING` during this operation;
- a candidate load/test failure leaves the draft unactivated and the old active
  service untouched;
- global/body/queue/event-ring changes affect only admissions/events after the
  snapshot swap.

Activation never performs a paid chat-provider call. Explicit operation tests
are separately recorded with the exact draft hash so admin can show whether a
draft was tested, but a provider outage does not make configuration history
uneditable.

## Secret handling

Use authenticated encryption from `cryptography` (Fernet is acceptable for
this phase). Master-key resolution order:

1. `EVW_SERVER_MASTER_KEY` environment value;
2. `<state-dir>/secrets/master.key` only for local/single-VPS operation.

If a key file is created, generate it with cryptographically secure randomness
and restrict it to the service account: mode 0600 on Unix; remove inherited
ACLs and grant only current service user and SYSTEM on Windows. Startup fails
if permissions cannot be secured. The master key is never stored in the
control DB, admin HTML, logs, audit rows, or test output.

API-key fields are write-only:

- blank submission preserves the existing binding;
- replace stores new ciphertext and suffix;
- remove is a separate confirmed action and prevents activation when required;
- display returns provider label, configured/not-configured, and final four
  characters only;
- decrypted values exist only while constructing an outbound provider request.

## Legacy JSON import

Implement one startup-safe, idempotent import from the current
`~/.message_evidence_server/server.json` when the control DB has no imported or
active version:

1. Read and validate the complete old config without logging it.
2. Apply the fixed mapping below, encrypt secrets, create one draft, and record
   the SHA-256 source hash.
3. If the mapped draft is complete, activate it and read/decrypt/validate the
   resulting immutable snapshot.
4. After verified activation, record success and atomically replace the old
   JSON with a redacted receipt containing no key.
5. If the mapped draft lacks a new required value, record `incomplete` against
   its source hash, keep the old JSON byte-identical, and expose that one draft
   in bootstrap admin. Do not reimport it on every restart. When that exact
   draft (or a descendant copied from it) is completed and activated, perform
   step 4.

A malformed source, encryption failure, or database failure rolls back every DB
change and leaves the original JSON untouched. Missing newly introduced fields
take the explicit incomplete-draft branch and are not treated as importer
corruption. After success, runtime code never reads JSON. Do not retain a
plaintext backup. This packet explicitly authorizes replacing the old plaintext
config only after verified encrypted import.

The importer performs this fixed schema mapping; it does not guess:

- `whole_transcript` becomes `whole_corpus_answer`;
- `window_scan` becomes `window_evidence_extraction`;
- `evidence_ledger_synthesis` becomes `ledger_synthesis`;
- `ledger_reduction` copies the nonprompt route/model/budget/secret fields from
  old evidence-ledger synthesis and receives the new seeded reduction prompt;
- old `max_request_tokens` becomes that operation's target input cap;
- migrated safety margin is exactly
  `context_window_tokens - max_request_tokens - max_output_tokens` and import
  fails if that value is negative, preserving the old accepted-input boundary;
- migrated structured-output mode is `prompt_only`, matching the old wire path;
- migrated chat operations use `serialized_payload_tiktoken` with
  `cl100k_base`, matching the old server's explicit tokenizer, and are visibly
  labelled estimated;
- missing new queue/retry/circuit fields receive only the fixed policy values
  listed below; absent price remains explicitly unconfigured and cost output is
  marked incomplete until the administrator supplies it.

If this mapping cannot produce a valid active version because a genuinely
required provider/model/accounting value is absent, import the secrets and mapped values
into a bootstrap draft, record an incomplete import receipt, keep the old JSON
untouched, and start loopback bootstrap. The admin page lists each missing
field. After the operator completes and activates that draft, perform the
verification/hash/redacted-receipt steps and never read JSON again. This is not
a silent default or a startup failure.

## Fixed initial values

Import existing values when available. For a fresh control DB, seed the current
repository prompts into the bootstrap draft as migration data, but use no fake
provider/model/tokenizer/context/price values: required chat operations remain
unconfigured and activation is impossible until completed. Nonsecret policy
defaults are:

```text
host=127.0.0.1, port=8710
maximum product request bytes=268435456
maximum conversational corpus tokens=768000
maximum embedding items=100000
maximum embedding request bytes=268435456
global product max in-flight=12
global product max queued=48
global queue wait timeout=30s
provider HTTP max connections=32
provider HTTP max keepalive connections=16
provider HTTP keepalive expiry=30s
window target input tokens=128000
maximum concurrent windows=2
retrieval assistance=true
ledger reduction max depth=4
recent event ring size=2000
default operation max in-flight=2
default operation max queued=24
default queue wait timeout=30s
default connect timeout=10s
default read timeout=600s
default write timeout=60s
default pool timeout=30s
default operation deadline=900s
default attempts=1 (no retry until explicitly configured/imported)
default circuit disabled until explicitly configured/imported
embedding internal batch=32, workers=1, max queued workloads=4,
embedding executor timeout=3600s, progress minimum interval=250ms
```

No provider/model/tokenizer/context/price value is invented for a fresh server.
The seeded prompts are the current tested prompt text, copied into the control
store so there is one runtime prompt path; they are not alternate hardcoded
runtime defaults.
