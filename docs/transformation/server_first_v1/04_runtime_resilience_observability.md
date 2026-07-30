# Runtime, resilience, accounting, logging, and errors

## Async runtime

Replace blocking `urllib` with one lifespan-owned `httpx.AsyncClient` using
configured connect/read/write/pool timeouts and bounded connection pools.
Provider functions are async and make exactly one outbound call per attempt.
Never call blocking provider or embedding work on the event-loop thread.

The dedicated embedding service loads one SentenceTransformer instance per
configured replica worker. Default worker count is one. A count above one creates independent
SentenceTransformer model replicas, one single-thread executor worker per
replica; never invoke one model object concurrently. All replicas must produce
the same fingerprint/dimensions in activation validation. Admin shows the
resulting memory/device cost. Changing model/profile drains the embedding queue,
constructs and validates a new service, then atomically swaps it for new
workloads; accepted workloads finish against their captured service or fail
clearly during controlled stop.

Client disconnect cancels queued work and cancels active async provider calls.
An already-running embedding encode may finish in its executor, but its result
is discarded and no further batches start.

## Queue and concurrency policy

Use explicit FIFO bounded queues and semaphores. A product request first obtains
a global admission slot at ASGI middleware entry, before its body is buffered
or parsed, then operation queue/concurrency slots as internal calls occur.
Enforce the configured byte ceiling while reading the body even when
`Content-Length` is missing or false; an over-limit body is rejected and its
admission slot released. Queue state is visible in admin.

Window calls may execute concurrently up to the smaller of conversation
`maximum_concurrent_windows` and active operation/provider limits. Results are
stored and ledger IDs assigned in deterministic window order, never completion
order.

Queue full fails immediately with `SERVER_BUSY`; queue wait expiry fails
`QUEUE_TIMEOUT`. Do not create hidden unbounded asyncio tasks.

## Retry policy

The server owns retries. The product client never retries a model stage inside
one accepted request.

Retry only when all are true:

- operation policy has attempts greater than one;
- failure HTTP status is explicitly listed as retryable;
- stream/client remains connected;
- circuit policy permits the attempt;
- request deadline leaves enough time for backoff and another configured call.

Emit `retry_wait` before sleeping. Backoff is
`min(base * multiplier^(attempt-1), cap)` plus bounded configured jitter.
Log every attempt. Never retry schema/model-output failure, provider auth
failure, local validation failure, cancellation, or a status not explicitly
listed. Never switch provider/model.

## Circuit breaker

Maintain one in-memory circuit per operation route/config version. When enabled,
count configured transient failures in a rolling observation window. At the
threshold, open for configured cooldown and fail new calls `CIRCUIT_OPEN`.
After cooldown, permit one half-open probe; success closes and clears counts,
failure reopens. Activation creates fresh circuits for the new version. Admin
shows state and provides an explicit manual reset with audit entry.

Circuit state is operational memory and resets on process restart. Do not
persist it in the control DB.

## Token and cost accounting

Each chat operation selects exactly one accounting mode:

- `serialized_payload_tiktoken`: canonical-serialize the complete outbound JSON
  provider body, including messages and `response_format`, and count it with the
  required configured tiktoken encoding;
- `huggingface_chat_template`: load the required pinned tokenizer/revision,
  count the two messages with its chat template, then count canonical
  `response_format` JSON with that tokenizer and add the required configured
  provider-wrapper token constant.

Both are preflight estimates because an OpenAI-compatible transport does not
standardize a token-count endpoint. Report the selected mode and
encoding/revision. Do not implement a fictional generic count endpoint. There
is no automatic fallback between modes. Failure to load/use the configured mode
fails config validation/test or the request.

Preflight constructs the actual system/user messages and configured structured
output payload before counting. Account for system prompt, request JSON, schema
overhead, chat template, max output reservation, and safety margin. The fit
test is:

```text
counted provider input + max output + safety margin <= context window
```

Capture provider response `usage` when present. Aggregate all attempts and all
internal stages; retry usage is real cost. When provider usage is absent, store
the configured estimate and mark source. Estimated cost uses admin-configured
input/output price and is operational telemetry, not billing. If any included
operation lacks either price, aggregate `estimated_cost` is null and
`cost_complete=false`; never present a partial known subtotal as the total.

Persist one append-only `usage_event` after every chat provider attempt,
including retry failures, and one summary row for each terminal embedding
workload. Use the control store's single short-write lock; no provider call or
embedding encode overlaps a SQLite transaction. A provider attempt does not
advance to retry/stage completion or emit successful completion until its usage
row commits. An accounting write failure stops orchestration immediately with
`ACCOUNTING_PERSISTENCE_FAILED`; it is never hidden or reconstructed with a
zero. Embedding per-batch throughput remains in redacted events/metrics, while
the terminal workload row avoids thousands of durable rows per build.

The admin dashboard reports cumulative durable token/cost/workload totals and
separate since-process-start metrics. SQL aggregation reads immutable usage
rows. It never derives billing from stdout logs or in-memory counters.

Before any conversational provider call, enforce the configured total corpus
workload ceiling using the active whole-model accounting strategy. Do not
enforce an inferred/hardcoded product limit elsewhere.

## Embedding artifact identity

Load the configured SentenceTransformer model/revision once, validate the
configured output dimension, and compute a stable SHA-256 artifact fingerprint
over sorted state-dict entries (parameter name, dtype, shape, and contiguous CPU
bytes) plus canonical SentenceTransformer module/config JSON. Compute it at
candidate-service construction, never per request. The profile ID is
`emb-sha256:` plus SHA-256 of canonical JSON containing model name, requested
revision (which may be blank for a migrated local model), artifact fingerprint,
normalization, dimensions, and sentence-transformers package version. Thus a
changed downloaded model cannot reuse an old local vector partition even when
its configured name is unchanged.

## Strict model output

Internal schemas are Pydantic models and exported JSON Schemas with every field
required and `extra='forbid'`. Provider-native JSON Schema is used only when
the operation explicitly selects it. `json_object` and `prompt_only` still pass
through the same strict local parser.

Accept a single optional outer Markdown JSON fence only in `prompt_only` mode.
Do not repair malformed JSON, coerce wrong types, fill missing fields, silently
drop extra fields, or parse prose around JSON. Save raw output only in the
explicit admin test result held in memory for that browser response.

## Structured operational logging

Emit one JSON object per line to stdout. Uvicorn access logging remains off;
application events provide the useful record. Required fields when applicable:

```text
timestamp, severity, event, request_id, config_version, product_endpoint,
internal_operation, provider, model, strategy, stage, attempt, queue_wait_ms,
latency_ms, input_tokens, output_tokens, usage_source, estimated_cost,
http_status, error_code, provider_request_id
```

Required events include request accepted/rejected/terminal, queue enter/leave,
provider attempt start/success/failure, retry wait, circuit transition, window
plan/start/success, ledger validation/reduction/synthesis, embedding batch
start/success, client cancellation, and config validate/test/activate/rollback.

Never log corpus/message text, user questions, user-content prompts, model
outputs, vectors, API keys, authorization values, decrypted secrets, or raw
request/response bodies. Safe provider errors are normalized and capped.
Internal exceptions include stack traces in stdout logs but product responses
use safe stable messages.

Feed the same redacted events into a bounded in-memory ring for admin display.
Only config actions are durably audited in control SQLite. Deployment is
responsible for stdout retention through systemd/Docker/log collection.

## Admin status versus machine liveness

Humans use `/admin/`. Provide private `GET /internal/live` only for supervisor
checks; it returns process alive and API version without loading models or
calling providers. Admin readiness is a dashboard state composed from active
config validation, embedding load state, circuits, and last explicit provider
tests. Do not claim provider readiness from liveness.

## Error mapping

Centralize exceptions and mappings; endpoint handlers do not create arbitrary
error dictionaries. FastAPI request-validation errors are converted to the
common error shape. Preserve provider status only through safe mapped codes.

```text
400 REQUEST_INVALID for malformed JSON semantics not represented by 422
413 WORKLOAD_TOO_LARGE
422 REQUEST_INVALID / REQUEST_INTEGRITY_FAILED / UNSPLITTABLE_MESSAGE /
    LEDGER_BUDGET_EXCEEDED
429 PROVIDER_RATE_LIMITED
500 CONFIGURATION_ERROR / ACCOUNTING_PERSISTENCE_FAILED / INTERNAL_ERROR
502 PROVIDER_REJECTED / MODEL_OUTPUT_INVALID / LEDGER_BIJECTION_FAILED
503 SERVER_BUSY / QUEUE_TIMEOUT / CIRCUIT_OPEN / PROVIDER_UNAVAILABLE /
    CONFIGURATION_REQUIRED / EMBEDDING_RECONFIGURING
504 PROVIDER_TIMEOUT
```

Pre-stream errors use HTTP. Post-stream errors use the same code in terminal
`failed`. No known failure is flattened to generic 500.
