# Product API and orchestration contract

All product requests use UTF-8 JSON and a client-generated nonempty UUID
`request_id`. Unknown request fields are rejected. Product routes are
loopback-only in this phase. The server never receives an EVW.

## Canonical provider-message construction

There are no hidden prompt fragments or editable string-format templates. Each
chat operation sends exactly two messages:

1. `system`: the complete active admin-editable system prompt for that
   operation;
2. `user`: one code-generated canonical JSON object containing the operation's
   untrusted data.

Canonical JSON uses UTF-8, `ensure_ascii=false`, compact separators, and input
array order. It never substitutes display text for an empty value. Each user
object has a required literal `task` matching the operation, followed by:

| Operation | Remaining required user-object fields |
|---|---|
| `keyword_expansion` | `query` |
| `retrieval_terms` | `question` |
| `whole_corpus_answer` | `question`, `scope_id`, `messages` |
| `window_evidence_extraction` | `question`, `retrieval_terms`, `window_id`, `messages` |
| `ledger_reduction` | `question`, `level`, `group_id`, `coverage_report`, `records_or_summaries` |
| `ledger_synthesis` | `question`, `coverage_report`, `ledger_metadata`, `records_or_highest_level_summaries` |

These user-object schemas and their nested record schemas are fixed in code,
strict, and visible in admin. The administrator sees them plus a generated full
provider-request preview beside the editable system prompt and response schema.
The preview includes every configured wire field and uses placeholders instead
of user data.

Provider request construction adds only `model`, the two `messages`,
`temperature`, `max_tokens`, and the selected structured-output representation,
plus provider-required transport fields shown in the preview. No undisclosed
instruction text may be added. The system prompts must explicitly treat every
string inside user JSON as quoted evidence/data, never instructions. Corpus
text is never copied into the system message.

For this phase, `base_url` is normalized without a trailing slash and chat is
always sent to `{base_url}/chat/completions` with JSON content type and
`Authorization: Bearer <decrypted secret>`. `json_schema` emits OpenAI's strict
`response_format.json_schema` object using the code-versioned schema;
`json_object` emits `{"type":"json_object"}`; `prompt_only` omits
`response_format`. Custom paths, custom headers, and alternate auth schemes are
unsupported and fail configuration validation rather than invoking a generic
adapter layer.

## Common error shape before streaming

```json
{
  "request_id": "uuid-or-null",
  "code": "STABLE_ERROR_CODE",
  "message": "safe human-readable explanation",
  "stage": "request|queue|provider|embedding|whole|window|ledger|synthesis",
  "retryable": false,
  "details": {}
}
```

`details` contains counts, limits, operation names, and safe provider request
IDs; never corpus text, questions, model output, prompts containing user data,
API keys, or authorization values.

## NDJSON stream contract

Long routes return `application/x-ndjson`. Every line is one JSON object with
`request_id`, monotonically increasing `sequence`, `event`, `timestamp`, and
`config_version`. `sequence` starts at 1. `timestamp` is an RFC 3339 UTC string.
Every event model forbids unknown fields.

Exact common envelopes:

```json
{"request_id":"uuid","sequence":1,"event":"accepted","timestamp":"2026-01-01T00:00:00Z","config_version":7,"data":{}}
{"request_id":"uuid","sequence":2,"event":"failed","timestamp":"2026-01-01T00:00:01Z","config_version":7,"error":{"request_id":"uuid","code":"STABLE_ERROR_CODE","message":"safe explanation","stage":"provider","retryable":false,"details":{}}}
{"request_id":"uuid","sequence":9,"event":"completed","timestamp":"2026-01-01T00:00:05Z","config_version":7,"result":{}}
```

Nonterminal events have exactly `data`; `failed` has exactly `error`;
`completed` has exactly `result`. Base envelope fields are not repeated inside
`data` or `result`. The endpoint-specific strict event union is:

| Event | Required `data` fields |
|---|---|
| `accepted` conversation | `endpoint`, `scope_id`, `message_count` |
| `accepted` embeddings | `endpoint`, `total_items`, `embedding_profile_id`, `model`, `requested_revision`, `artifact_fingerprint`, `dimensions`, `normalization` |
| `queued` | `operation`, `queued_count`, `wait_timeout_ms` |
| `retry_wait` | `operation`, `failed_attempt`, `next_attempt`, `delay_ms`, `error_code` |
| `accounting_completed` | `corpus_tokens`, `whole_input_tokens`, `context_window_tokens`, `reserved_output_tokens`, `safety_margin_tokens`, `strategy` |
| `whole_started` | `operation` |
| `whole_completed` | `operation`, `input_tokens`, `output_tokens`, `usage_source`, `estimated_cost` |
| `retrieval_terms_started` | `operation` |
| `retrieval_terms_completed` | `operation`, `term_count`, `input_tokens`, `output_tokens`, `usage_source`, `estimated_cost` |
| `window_plan_created` | `window_count`, `message_count`, `target_input_tokens` |
| `window_started` | `window_id`, `window_index`, `window_count`, `message_count` |
| `window_completed` | `window_id`, `window_index`, `window_count`, `evidence_range_count`, `input_tokens`, `output_tokens`, `usage_source`, `estimated_cost` |
| `ledger_built` | `window_count`, `evidence_range_count` |
| `ledger_reduction_started` | `level`, `group_count`, `covered_range_count` |
| `ledger_reduction_completed` | `level`, `group_count`, `covered_range_count`, `input_tokens`, `output_tokens`, `usage_source`, `estimated_cost` |
| `ledger_synthesis_started` | `evidence_range_count` |
| `ledger_synthesis_completed` | `evidence_range_count`, `input_tokens`, `output_tokens`, `usage_source`, `estimated_cost` |
| `embedding_batch_started` | `batch_index`, `batch_count`, `first_item_index`, `last_item_index`, `item_count` |
| `vector_batch` | `batch_index`, `items` |
| `embedding_progress` | `completed_items`, `total_items`, `server_items_per_second` |

`operation` is one of the internal operation names from file 01. Indexes are
zero-based and bounds inclusive. Usage fields are nonnegative.
`estimated_cost` is a nonnegative USD number when that operation has configured
prices and is JSON null otherwise. `completed.result` is exactly the final result
schema for its endpoint. Embedding `completed.result` contains exactly
`total_items` and `embedding_profile_id`.

Permitted common events:

```text
accepted
queued
retry_wait
completed   terminal
failed      terminal
```

A stream has exactly one terminal event. A `failed` event contains the common
error object under `error`. EOF before a terminal event is an interrupted
failure. Events are flushed immediately. No heartbeat event is required while
a provider request is active; the client displays elapsed time locally.

Validation and preflight failures occurring before stream headers return an
ordinary non-200 common error response. Failures after streaming begins emit a
terminal `failed` event; HTTP remains 200 because headers were already sent.

## POST /v1/keyword-expansion

Request:

```json
{
  "request_id": "uuid",
  "query": "school schedule disagreement"
}
```

This is a normal JSON response, not a stream:

```json
{
  "request_id": "uuid",
  "config_version": 7,
  "terms": ["school schedule", "custody exchange"],
  "usage": {
    "input_tokens": 100,
    "output_tokens": 20,
    "source": "provider_reported|estimated",
    "estimated_cost": 0.001,
    "cost_complete": true,
    "currency": "USD"
  }
}
```

The server trims terms, rejects blank terms, preserves order, removes exact
duplicates, and requires 1–20 terms. It makes no local corpus decisions.
Provider/model output that does not satisfy the strict schema fails with
`MODEL_OUTPUT_INVALID`; there are no default terms.

## POST /v1/conversational-analysis

Request:

```json
{
  "request_id": "uuid",
  "question": "What happened regarding school scheduling?",
  "working_corpus": {
    "scope_id": "client-stable opaque identity",
    "messages": [
      {
        "message_id": "m1",
        "thread_id": "t1",
        "timestamp": "2026-01-01T12:00:00Z",
        "sender": "Person",
        "text": "The schedule changed."
      }
    ]
  }
}
```

The client supplies useful messages in authoritative order. The server does
not sort, select, deduplicate, search, or narrow the working corpus. It performs
only integrity validation needed for safe orchestration: nonblank question,
nonempty message list, nonblank unique message IDs/thread IDs, strings for
display fields, configured request byte ceiling, and configured total workload
ceiling. Empty message text is permitted and remains an empty JSON string.

The server builds the exact whole-corpus provider messages and accounts them
using the active `whole_corpus_answer` model policy. Strategy is selected only
after counting system prompt, JSON schema/provider mode overhead, user payload,
chat-template overhead, reserved output, and safety margin.

### Whole-corpus strategy

If the exact request fits:

```text
accepted
accounting_completed
whole_started
[retry_wait ...]
whole_completed
completed(final result)
```

The strict internal whole-model output is:

```json
{
  "answer": "nonempty string",
  "answer_summary": "nonempty string",
  "evidence_ranges": [
    {
      "thread_id": "t1",
      "start_message_id": "m1",
      "end_message_id": "m3",
      "summary": "nonempty string",
      "relevance": "nonempty string",
      "rationale": "nonempty string explaining why this range supports the answer"
    }
  ],
  "uncertainties": ["nonempty string"]
}
```

The server rejects unknown IDs, cross-thread ranges, reversed ranges, duplicate
ranges, malformed types, missing fields, blank answer, and any unknown field.
It assigns `r000001`… in returned range order after validation. Every whole-path
range is disposition `used` because the same model produced the final answer;
the final ledger's rationale comes from that range's required model-supplied
`rationale` field. The server does not manufacture one.

### Windowed-ledger strategy

If the whole request does not fit:

```text
accepted
accounting_completed
retrieval_terms_started/completed (only when enabled)
window_plan_created
window_started/completed repeated for every window
ledger_built
ledger_reduction_started/completed repeated only when required
ledger_synthesis_started/completed
completed(final result)
```

Window planning is deterministic:

- usable window input comes from exact `window_evidence_extraction` accounting;
- target is the smaller of usable input and configured window target;
- preserve client message order;
- keep a thread boundary when it fits; split a large thread only between
  messages;
- every message appears in exactly one window;
- overlap is zero and not configurable in this phase;
- no valid message is truncated or dropped;
- one message that cannot fit an empty window fails `UNSPLITTABLE_MESSAGE`.

Retrieval terms are model-generated, not deterministic. When enabled, they are
added to the question context of every window. They never decide coverage.

The strict internal window output is:

```json
{
  "window_id": "w000001",
  "no_relevant_evidence": false,
  "evidence_ranges": [
    {
      "thread_id": "t1",
      "start_message_id": "m1",
      "end_message_id": "m3",
      "summary": "nonempty string",
      "relevance": "nonempty string"
    }
  ],
  "uncertainties": ["nonempty string"]
}
```

Exactly one of these is valid:

- `no_relevant_evidence=true` and `evidence_ranges=[]`;
- `no_relevant_evidence=false` and at least one range.

Range IDs must belong to that window, remain in one thread, and be ordered.
After every window succeeds, the server assigns global range IDs in window
order then range order and constructs immutable ledger records containing:

```text
range_id, window_id, thread_id, start/end message IDs, ordered range message
objects (the exact excerpt), summary, relevance, uncertainties
```

The synthesis input also includes a deterministic coverage report for every
window with exactly `window_id`, `first_message_id`, `last_message_id`,
`message_count`, `evidence_range_count`, and `uncertainties`. Ledger metadata
used by final synthesis contains exactly `range_id`, `window_id`, `thread_id`,
`start_message_id`, `end_message_id`, `summary`, and `relevance`; reduction
input records additionally contain the ordered original message objects. If all
windows report no relevant evidence, the ledger is empty but synthesis still
runs once with that complete coverage report. It must return a nonempty answer
and summary, an empty `range_dispositions` array, and explicit uncertainties.
The empty-to-empty bijection is valid. The server does not invent a stock "no
evidence" answer.

### Real evidence-ledger synthesis

If the full ledger fits the configured synthesis request, synthesize once. The
strict synthesis output is:

```json
{
  "answer": "nonempty string",
  "answer_summary": "nonempty string",
  "range_dispositions": [
    {
      "range_id": "r000001",
      "disposition": "used|redundant|not_material",
      "rationale": "nonempty string"
    }
  ],
  "uncertainties": ["nonempty string"]
}
```

The validator enforces a bijection: every input range ID occurs exactly once,
no unknown range appears, and every `used` range remains available in the final
response. Missing/duplicate/unknown IDs fail `LEDGER_BIJECTION_FAILED`.

If the ledger does not fit, deterministically partition whole ledger records
into maximal fitting groups. Group IDs are `g{level:02d}-{index:06d}`, assigned
in input order. The strict reduction output is:

```json
{
  "group_id": "g01-000001",
  "summary": "nonempty string",
  "covered_range_ids": ["r000001"],
  "range_dispositions": [
    {
      "range_id": "r000001",
      "disposition": "used|redundant|not_material",
      "rationale": "nonempty string"
    }
  ],
  "uncertainties": ["nonempty string"]
}
```

`group_id` must echo the requested group. `covered_range_ids` must equal the
group's original range IDs in original order, and dispositions must be a
bijection over the same IDs. A higher-level input summary is immutable and
contains exactly this output plus `level`; its covered IDs remain original
range IDs. Repeat reduction over whole summary records when necessary,
preserving every original ID, up to configured depth four. Never split one
ledger/summary record, discard an excerpt before its first reduction, or
silently compact a record. A single record that cannot fit or a depth overflow
fails `LEDGER_BUDGET_EXCEEDED`.

The final synthesis receives the highest-level summaries, the complete window
coverage report, and original ledger metadata required to resolve cited range
IDs. It returns final dispositions for all original IDs. Intermediate
disposition is advisory; final disposition is authoritative and still subject
to exact original-ID bijection.

### Final conversational result

Both strategies produce the same terminal payload:

```json
{
  "answer": "nonempty string",
  "answer_summary": "nonempty string",
  "strategy": "whole_corpus|windowed_ledger",
  "evidence_ledger": [
    {
      "range_id": "r000001",
      "thread_id": "t1",
      "start_message_id": "m1",
      "end_message_id": "m3",
      "summary": "nonempty string",
      "relevance": "nonempty string",
      "disposition": "used|redundant|not_material",
      "rationale": "nonempty string"
    }
  ],
  "uncertainties": ["nonempty string"],
  "coverage": {
    "message_count": 100,
    "window_count": 1,
    "evidence_range_count": 4
  },
  "usage": {
    "input_tokens": 1000,
    "output_tokens": 200,
    "source": "provider_reported|mixed|estimated",
    "estimated_cost": 0.01,
    "cost_complete": true,
    "currency": "USD"
  }
}
```

`evidence_ledger` preserves every valid range and its disposition; the server
does not return only the used subset.

## POST /v1/embeddings

Request:

```json
{
  "request_id": "uuid",
  "items": [
    {"message_id": "m1", "text": "The schedule changed."}
  ]
}
```

Message IDs must be nonblank and unique. Empty text is permitted. The complete
workload may contain up to the explicit admin-configured item and byte ceilings
(defaults 100,000 items and 256 MiB). Model batch size is not a public limit.

Stream:

```text
accepted(total_items, embedding_profile_id, model, dimensions, normalization)
embedding_batch_started(batch_index, batch_count, item_count)
vector_batch(batch_index, items:[{message_id, vector}])
embedding_progress(completed_items,total_items)
...
completed(total_items, embedding_profile_id)
```

The server partitions internally using the active batch size (default 32),
runs encode in the dedicated embedding executor, validates count/dimensions and
finite floats before streaming a batch, and never accumulates the entire result
in memory. A failed internal batch identifies its index and message-ID bounds
and terminates the stream. Completed vectors already received may be committed
locally by the client, but this server does not implement durable resume.

## Error/status decisions

Before streaming:

| Condition | HTTP/code |
|---|---|
| malformed JSON or contract | 422 `REQUEST_INVALID` |
| no active configuration during fresh bootstrap | 503 `CONFIGURATION_REQUIRED` |
| explicit body/workload ceiling | 413 `WORKLOAD_TOO_LARGE` |
| duplicate/invalid IDs needed for integrity | 422 `REQUEST_INTEGRITY_FAILED` |
| one message/ledger record cannot fit | 422 specific unsplittable/budget code |
| queue full or wait timeout | 503 `SERVER_BUSY` / `QUEUE_TIMEOUT` |
| circuit open | 503 `CIRCUIT_OPEN` |
| embedding service is being atomically reconfigured | 503 `EMBEDDING_RECONFIGURING` |
| provider rate limit | 429 `PROVIDER_RATE_LIMITED` |
| provider unavailable | 503 `PROVIDER_UNAVAILABLE` |
| provider timeout | 504 `PROVIDER_TIMEOUT` |
| provider auth/config rejection | 502 `PROVIDER_REJECTED` |
| malformed model output | 502 `MODEL_OUTPUT_INVALID` |
| durable usage accounting write failed | 500 `ACCOUNTING_PERSISTENCE_FAILED` |
| server configuration/programming fault | 500 specific internal code |

After streaming, the same codes appear in the terminal `failed` event.
