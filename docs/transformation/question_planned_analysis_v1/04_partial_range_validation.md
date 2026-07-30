# Partial range validation

## Purpose

Keep independently valid evidence when a provider returns one malformed sibling
range. This is not permissive ID repair. It is strict validation at the correct
granularity.

## Two-stage parser

Do not pass the complete extraction response directly into a Pydantic model
whose nested range failure rejects the envelope.

Implement:

1. exact JSON-object parsing and top-level envelope validation;
2. independent exact schema and semantic validation for each range element.

The parser returns one internal `ValidatedWindowEvidence` value containing:

- `window_id`;
- ordered accepted ranges;
- ordered rejected-range diagnostics;
- window uncertainties;
- accepted normalization records;
- `status=complete|partial`.

This internal result, not the raw provider model, is the input to canonical
ledger construction.

## Atomic envelope failures

The complete extraction operation fails when any of these is true:

- output is not exactly one JSON object;
- top-level keys are missing or extra;
- `window_id` is missing, blank, non-string, or does not equal the requested
  window;
- `evidence_ranges` is not a list;
- `uncertainties` is not a list of bounded nonblank strings;
- response exceeds existing provider/output ceilings.

These failures remain `MODEL_OUTPUT_INVALID` or the existing more specific
structural error. Existing configured operation retries may run and remain
visible.

## Independent range schema

Every array element is evaluated in its original zero-based `range_index`.

It must be an object with exactly:

```text
thread_id
start_message_id
end_message_id
summary
relevance
```

All five values must be bounded nonblank strings. An element with missing,
extra, or wrong-typed fields is rejected with a stable code. Other elements
continue.

## Semantic validation order

Validate each schema-valid element in this exact order:

1. `start_message_id` exists in the supplied window;
2. `end_message_id` exists in the supplied window;
3. both endpoints resolve to the same supplied thread;
4. declared `thread_id` exactly equals that supplied thread;
5. endpoint order is checked against message-array order;
6. every message inside the resulting inclusive interval has that thread;
7. the accepted endpoint pair has not already been accepted in this window.

Use stable rejection codes:

```text
RANGE_NOT_OBJECT
RANGE_SCHEMA_INVALID
UNKNOWN_START_MESSAGE_ID
UNKNOWN_END_MESSAGE_ID
CROSS_THREAD_RANGE
THREAD_ID_MISMATCH
NONCONTIGUOUS_THREAD_RANGE
DUPLICATE_RANGE
```

Do not expose transcript text in these diagnostics.

## One deterministic normalization

If and only if:

- both endpoint IDs exist;
- both belong to the declared thread;
- every message in the reverse interval belongs to that thread; and
- start appears after end in the supplied array,

swap the endpoints and accept the range.

Record:

```json
{
  "code": "ENDPOINT_ORDER_SWAPPED",
  "window_id": "w000001",
  "range_index": 2,
  "original_start_message_id": "source:9",
  "original_end_message_id": "source:4"
}
```

The final ledger exposes `normalizations:["endpoint_order_swapped"]`.

Do not normalize:

- unknown or fabricated IDs;
- an ID prefix that resembles another source;
- thread IDs;
- cross-thread intervals;
- summaries or relevance;
- ambiguous repeated IDs;
- a range inferred from model prose.

## Duplicate handling

The first independently valid occurrence of an exact normalized endpoint pair
is accepted. A later identical pair is rejected as `DUPLICATE_RANGE`.

Do not merge overlapping but nonidentical valid ranges. Both remain accepted.
Synthesis may classify one as context or nonresponsive, but extraction
validation does not decide redundancy.

## Window and request status

- zero proposed ranges and zero rejected ranges: complete empty window;
- one or more proposed ranges and zero rejected ranges: complete window;
- one or more rejected ranges: partial window, even if accepted ranges remain;
- all proposed ranges rejected: partial window with zero accepted ranges.

A partial window still emits `window_completed` with exact counts. After all
required windows finish, the server emits `evidence_validation_completed`.

The complete conversational request proceeds to ledger construction and
synthesis with accepted ranges. Its final status is
`partial_evidence_validation`.

## Canonical range identity

Assign final range IDs only after every required window has completed:

- iterate windows in deterministic planned order;
- within each window iterate accepted ranges by original `range_index`;
- assign `r000001` onward without gaps.

Every ledger record retains:

- final `range_id`;
- `window_id`;
- original `source_range_index`;
- exact normalized endpoints;
- exact model summary and relevance;
- normalization codes;
- exact source messages request-locally.

Rejected ranges receive no `range_id` and never appear in ledger metadata,
compaction, findings, dispositions, overlap counts, or evidence blocks.

## Observability

Normal event/log fields may include:

- request/window identifiers;
- validation status;
- accepted/rejected/normalized counts;
- stable rejection and normalization codes.

Normal logs must not include:

- question or plan text;
- transcript text;
- summaries or relevance;
- rejected IDs.

When exact debug capture is active, capture:

- raw provider output;
- accepted ranges;
- rejected diagnostics including supplied IDs;
- normalization records;
- final accepted ledger.

Admin activity shows process-lifetime totals and recent content-free partial
validation warnings.

## No automatic repair call

This packet does not add a second provider call for malformed ranges.

The final result gives enough explicit information to evaluate whether a later
targeted repair operation is worthwhile. Do not invent that operation now.

