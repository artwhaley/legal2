# Target architecture and ownership

## Runtime topology

```text
Python EVW harness now / Flutter later
  |-- local EVW, working corpus, FTS5, vectors, visible history
  |-- POST one complete server request
  |-- consume NDJSON progress/data/terminal events
  v
FastAPI server, one process for this phase
  |-- three product routes
  |-- private server-rendered /admin
  |-- immutable active configuration snapshots
  |-- async provider HTTP and bounded operation queues
  |-- dedicated embedding executor
  |-- request-local conversational orchestration
  v
Configured OpenAI-compatible providers + local SentenceTransformer

Server control-plane SQLite
  |-- operational configuration versions
  |-- encrypted provider secrets
  |-- activation/admin audit and append-only content-free usage events
  `-- no corpus, question, model output, or user history
```

Use one Uvicorn process. Async network I/O and bounded executors provide
concurrency. Multiple Uvicorn workers are forbidden in this phase because they
would duplicate the embedding model and produce inconsistent in-memory active
configuration, circuits, queues, and dashboard state.

The stable operator command is `python -m server`. With default state, the
admin page is `http://127.0.0.1:8710/admin/`. Do not require environment
variables for the normal local path; `EVW_SERVER_STATE_DIR` and
`EVW_SERVER_MASTER_KEY` remain service/deployment overrides.

## Final lean server file map

Refactor toward this map; do not create one class per file or parallel legacy
paths:

```text
server/app.py                 app composition and three product routes
server/contracts.py           product request/event/error contracts and strict schemas
server/config_store.py        control DB, schema migration, secrets, snapshots, audit
server/admin.py               server-rendered admin routes/actions
server/templates/admin.html   one page; inline minimal CSS/JavaScript
server/provider.py            shared async OpenAI-compatible provider client
server/resilience.py          queues, semaphores, retries, circuits, cancellation
server/token_accounting.py    exact/declared tokenizer strategies and cost accounting
server/conversation.py        strategy decision, windows, orchestration, streaming
server/evidence_ledger.py     range validation, IDs, ledger, hierarchical synthesis
server/embeddings.py          model lifecycle, internal batches, executor, streaming
server/observability.py       structured events, metrics, recent-event ring
server/__main__.py            validated headless startup
```

Small helpers may remain in a nearby file when that makes the code clearer;
do not produce scaffolding or empty abstractions. Delete replaced files in the
same ticket that replaces them.

## Settings ownership matrix

### Server-admin configurable

Global:

- bind host/port (loopback enforced while auth is absent);
- maximum product request bytes;
- maximum conversational corpus tokens;
- maximum embedding request items and bytes;
- global request concurrency and queue wait policy;
- shared provider HTTP maximum/keepalive connection counts and keepalive expiry;
- recent admin-event ring size;
- active configuration version and explicit rollback.

Per internal chat operation (`keyword_expansion`, `retrieval_terms`,
`whole_corpus_answer`, `window_evidence_extraction`, `ledger_reduction`,
`ledger_synthesis`):

- enabled flag where meaningful (`retrieval_terms` only is optional);
- provider kind (`openai_compatible` is the only implementation in this phase);
- base URL, API-key secret, model ID;
- complete system prompt;
- structured-output mode: `json_schema`, `json_object`, or `prompt_only`;
- accounting mode: `serialized_payload_tiktoken` or
  `huggingface_chat_template`, with the exact encoding/model/revision fields
  required by that mode;
- context window, maximum output, safety margin, optional target input cap;
- connect/read/write/pool timeouts, overall operation deadline, temperature;
- max in-flight, max queued, queue wait timeout;
- retryable statuses, maximum attempts, backoff base/multiplier/cap, jitter;
- circuit threshold, observation window, cooldown;
- nullable input/output price per million tokens; null means cost is visibly
  unavailable, never zero.

Embedding:

- model name/revision, device, normalization, required dimensions;
- internal model batch size;
- independent model-replica worker count (default one), max queued workloads;
- request item/byte ceilings;
- executor timeout and progress cadence.

The embedding profile ID is derived from the actual loaded model artifact, not
only its configured name; file 04 defines the fingerprint.

Conversation workflow:

- retrieval-term assistance enabled (default true);
- window target input tokens (default 128,000, bounded by model accounting);
- maximum concurrent windows (also bounded by operation/provider semaphores);
- maximum ledger reduction depth (default four).

### Visible but versioned in code, not runtime-editable

- public API request/event/error schemas;
- internal model-output JSON Schemas;
- deterministic window/range/ledger integrity rules;
- evidence range-ID format and ledger bijection requirements;
- terminal stream semantics;
- error-code meanings.

The admin page shows every active schema in full beside its editable prompt.
Changing a schema requires an API/schema version patch and tests. Runtime schema
editing is forbidden because server validators and client parsers depend on it.

### Client-only

- server URL;
- EVW path and working-corpus selection;
- local FTS/vector search settings;
- local index state and embedding-profile partitions;
- local persistence and presentation choices.

The Python harness must contain no provider key, provider URL, model ID,
context limit, prompt, server batch size, window target, retry, or circuit
setting after this phase.

## Configuration snapshot behavior

Each accepted product request captures one immutable active configuration
snapshot and reports its version in events. Admin activation is atomic. In-flight
requests finish using their captured snapshot; requests accepted after
activation use the new snapshot. No request observes mixed versions.

A fresh control database with no active version starts in explicit bootstrap
mode on loopback. The admin page remains available, while all three product
routes fail `503 CONFIGURATION_REQUIRED` before accepting work. Activation of
the first valid version leaves bootstrap mode without a process restart. An
existing active version that cannot be decrypted or validated is corruption,
not bootstrap, and aborts startup noisily.
