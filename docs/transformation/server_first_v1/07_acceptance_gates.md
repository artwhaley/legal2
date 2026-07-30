# Acceptance gates and closeout evidence

The executor installs required development dependencies and runs every command.
Do not hand dependency installation or automated tests to the user.

Use repository-local `.tmp` paths for generated control DBs, keys, logs, and
large fixtures. Never modify the only real EVW during automated tests.

## Gate A — Static boundaries and public surface

- `python -m compileall -q server message_evidence_workstation tests`
- `python scripts/verify_package_boundaries.py`
- route enumeration proves exactly three `/v1` product POST routes plus private
  `/admin/*` and `/internal/live`;
- FastAPI default docs, redoc, and OpenAPI routes are disabled;
- no `/v2`, `/capabilities`, public whole/window/retrieval/ledger route;
- server has no EVW/client import;
- Python client has no provider/model/prompt/window/retry/server-batch policy;
- no Qt import in server package;
- `git diff --check`.

## Gate B — Control plane and secrets

- fresh DB, draft, validation, activation, concurrent snapshot, rollback,
  restart, schema mismatch, quick/foreign-key check, clean WAL close;
- fresh bootstrap exposes admin but every product route fails
  `CONFIGURATION_REQUIRED`; first activation enables requests without restart;
- an existing invalid active version aborts startup and is never treated as a
  fresh bootstrap;
- exactly one active config and immutable prior versions;
- successful legacy import then redacted source receipt;
- incomplete legacy mapping creates a visible bootstrap draft, preserves source,
  and finishes redaction only after completed draft activation;
- failed import leaves source byte-identical;
- secret ciphertext round-trip and rotation;
- recursive scan of DB dump, admin HTML, stdout capture, errors, audit, receipts,
  and repository output finds no supplied secret sentinel;
- usage table/column allowlist and sentinel scan prove no corpus, question,
  output, vector, prompt, or secret content is durable;
- every provider attempt is one immutable row; every terminal embedding
  workload is one row; forced accounting failure prevents retry/success;
- cumulative dashboard totals survive restart and match SQL rows while
  since-process totals reset;
- file-permission tests for supported local platform.

## Gate C — Admin web

- FastAPI TestClient covers routes/forms and a Python Playwright headless
  Chromium test opens the dashboard and executes the complete JavaScript flow;
- every configurable field in ownership matrix is present and persists to draft;
- every fixed schema is visible in full and cannot be edited;
- prompts are visible/editable/versioned;
- secret fields are write-only/masked;
- validate/test/save/activate/rollback/reset actions are real and audited;
- invalid config cannot activate;
- admin never calls a provider except explicit test;
- non-loopback startup is rejected while auth disabled.

## Gate D — Strict provider/model behavior

Mocked async provider matrix:

- 200 valid output;
- 200 `{}`, missing, extra, wrong type, malformed JSON, forbidden fence/prose;
- 400/401/403/404/408/409/422/429/500/502/503/504;
- connect/read/write/pool timeout;
- disconnect/cancellation;
- usage present and absent;
- configured structured-output modes;
- explicit retry and no-retry statuses;
- deadline preventing another retry;
- no model fallback.

Every case must assert status/code, attempt count, event/log sequence, redaction,
and circuit impact.

## Gate E — Accounting and whole/window decision

- exact test tokenizer fixtures count system prompt, schema, chat overhead, user
  payload, output reservation, and safety margin;
- a request one token inside uses whole strategy;
- a request one token outside uses window strategy;
- provider-reported usage overrides estimates but retry usage is aggregated;
- total cost estimate includes retrieval, every window, reductions, synthesis,
  and retries;
- unsupported/misconfigured tokenizer strategy fails, never falls back.
- serialized-payload tiktoken and pinned HuggingFace chat-template modes count
  the complete generated provider payload and report their estimated source;
- missing price produces null aggregate cost with `cost_complete=false`, never
  zero or a misleading partial total.

## Gate F — Evidence ledger

- every message appears in exactly one deterministic window;
- thread boundaries preserved when possible and large thread splits only between
  messages;
- no overlap/truncation/drop;
- single oversize message fails;
- empty-evidence versus evidence invariant;
- cross-thread/reversed/unknown/duplicate ranges fail;
- stable global range IDs independent of concurrent completion order;
- exact transcript excerpts and immutable records;
- full synthesis bijection;
- whole-path range rationales come from required model fields, never generated
  defaults;
- all-window no-evidence case still performs synthesis against complete window
  coverage and validates an empty-to-empty range bijection;
- hierarchical grouping preserves every original range ID exactly once at every
  level;
- unknown/missing/duplicate disposition fails;
- one oversize ledger record and depth overflow fail noisily;
- both strategies produce identical final schema.

## Gate G — Streaming

For conversation and embeddings:

- sequence is monotonic and events flush;
- every event matches the exact endpoint-specific envelope/payload union and
  rejects missing, extra, or wrongly typed fields;
- exactly one terminal completed/failed;
- premature EOF is treated as interrupted by Python harness;
- pre-stream failures use HTTP error; post-stream failures use failed event;
- cancellation stops queued/future work;
- no stream terminal failure is persisted as success;
- configuration version remains fixed throughout stream.

## Gate H — Embeddings at scale

- >32 items prove public requests are not model-batch limited;
- 10,000 deterministic synthetic items in one request;
- internal batches follow active server configuration;
- vector batches preserve input identity and dimensions/finite values;
- server does not retain complete output collection;
- admin/liveness and chat mocks remain responsive during encoding;
- exact failed batch bounds emitted;
- Python commits completed batches and resumes by missing IDs;
- profile change creates correct local partition/stale status;
- changing actual model weights changes artifact fingerprint/profile ID even
  when configured model name is unchanged;
- no long EVW transaction or runaway WAL.

## Gate I — Twelve-user mixed load

Run one deterministic load harness with at least twelve concurrent logical
users combining:

- keyword calls;
- whole conversational calls;
- windowed conversational calls with multiple windows;
- large embedding streams;
- concurrent admin dashboard reads.

Provider and embedding work may use controlled fakes for repeatability. Assert
configured in-flight maxima are never exceeded, queues remain bounded/FIFO,
admin responds during load, no event-loop stall, every request terminates, and
metrics equal observed events. Record p50/p95/max queue wait and latency.

## Gate J — Python EVW integration

Use a copied real V14 fixture or the existing test V14 artifact. Prove:

- active working-corpus scope only;
- FTS5, keyword-expanded FTS, existing vector search;
- server whole strategy and server windowed-ledger strategy through one client
  action;
- strict local returned-ID/scope recheck and visible-history persistence;
- embedding stream, partial failure, resume, profile, local search;
- clean client close and V14/WAL verification.

The executor launches/configures services and test data. User action is reserved
only for final visual browser/client confirmation after automated gates pass.

## Gate K — Live configured-provider smoke

After all deterministic gates pass, use the imported active configuration to
run small explicit admin tests for every operation and one bounded end-to-end
conversation/embedding smoke. Do not echo credentials or real corpus text.

External provider capacity failure is not “fixed” with fallback. Record exact
safe status/body, circuit/retry behavior, and deterministic mock proof. It may
block only this live gate, not excuse failures in local gates. Do not repeatedly
spend provider calls after configured attempts are exhausted.

## Final closeout requirements

`closeout_report.md` must include:

- all ticket statuses;
- git status/diff identity and preserved unrelated dirty files;
- public/private route list;
- final file map and deleted legacy paths;
- control DB schema/config version and secret-source path (never secret value);
- exact test commands/counts/timings;
- load metrics;
- live smoke results;
- Python harness and EVW/WAL state;
- remaining risks limited to facts demonstrated by evidence.
