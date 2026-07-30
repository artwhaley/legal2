# Mission and non-negotiable invariants

## Mission

Build the server before the Flutter product client. The server accepts dumb,
complete requests, owns every provider/model/orchestration decision, and is
maintained through a browser-based administration surface suitable for a
headless VPS. Keep the Python client functional only so the finished server
behaviors can be exercised against the real local EVW workflow.

## Product boundary

The client owns:

- the EVW and every read/write transaction;
- full-corpus and working-corpus construction and membership;
- local FTS5 and sqlite-vec indexes and searches;
- local persistence of embeddings and user-visible conversation history;
- selection of the working corpus and construction of useful, ordered request
  messages;
- rendering streamed progress, terminal errors, and final results.

The server owns:

- provider credentials and routes;
- models, prompts, tokenizer/accounting policy, and strict model-output schemas;
- whole-corpus versus windowed conversational strategy;
- retrieval-term generation used only to assist exhaustive analysis;
- deterministic window planning;
- window execution, real evidence-ledger construction, synthesis, validation,
  retry, concurrency, queue, and circuit behavior;
- internal embedding batches, model workers, and streamed vector results;
- operational configuration, configuration versions, admin audit, metrics,
  durable content-free usage accounting, and safe logs.

The server never:

- opens, accepts, uploads, stores, or migrates an EVW;
- stores corpus messages, user questions, model responses, evidence, or chat
  history after a request ends;
- asks a client to choose a model, context limit, batch size, window size,
  retry policy, or analysis strategy;
- silently truncates, drops, defaults, repairs, retries, falls back, or returns
  a partial answer as success.

Request-local Python objects containing corpus text, windows, vectors, or model
outputs are permitted only for the lifetime of the HTTP request. They are not
durable state. A process crash or disconnected request loses them. Durable job
resume is explicitly out of scope for this phase.

## Public API invariant

Exactly three product endpoints survive:

```text
POST /v1/keyword-expansion
POST /v1/conversational-analysis
POST /v1/embeddings
```

There is no public capabilities endpoint. Whole-corpus, retrieval-term,
window-extraction, ledger-reduction, and ledger-synthesis operations are
internal server functions, not HTTP endpoints.

Private `/admin/*` routes form the web control plane. A private machine
liveness endpoint may exist only for process supervision. It is not a product
or human status surface.

Disable FastAPI's default `/docs`, `/redoc`, and `/openapi.json` routes. The
admin schema views are the sole human contract surface in this unauthenticated
loopback phase.

## Strategy invariant

Conversational analysis has one public operation and two internal strategies:

```text
fits whole-corpus model -> one strict whole-corpus answer call
does not fit           -> exhaustive windows -> deterministic ledger -> synthesis
```

Evidence ledger is not a third mode. It is the strict merge representation for
the windowed strategy. Retrieval terms may enrich window prompts but never
select, omit, rank away, or suppress windows or messages.

## Failure invariant

Every required field and state transition is real. Model output that is empty,
missing a required field, wrongly typed, contains unknown IDs, violates a
range, or fails ledger coverage is a terminal model-output failure unless an
explicitly configured retry policy applies to the provider transport status.
No response defaults exist.

Once an NDJSON stream has begun, HTTP status can no longer change. Therefore a
stream has exactly one terminal event: `completed` or `failed`. EOF without a
terminal event is an interrupted failure. Clients must never infer success from
HTTP 200 alone.

## Scope exclusions

Do not add in this phase:

- Flutter screens or Flutter server integration;
- EVW schema changes or migrations;
- user authentication, accounts, Clerk, billing, Stripe, subscriptions, API
  token purchasing, BYOK, or public internet exposure;
- durable conversational jobs, Redis, Celery, Kafka, or a user-data database;
- model fallback chains;
- a JavaScript SPA or frontend build toolchain;
- compatibility aliases for v2 server endpoints;
- changes to the Python client beyond the explicit harness tickets.

The app and admin server remain loopback-only while authentication is absent.
