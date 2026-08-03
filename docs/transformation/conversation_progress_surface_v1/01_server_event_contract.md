# Server event contract

## Why one server change is required

Existing `window_completed` events contain:

- window identity and position;
- accepted/rejected/normalized counts;
- validation status;
- token usage and estimated cost.

They do not contain the accepted range summaries or endpoints. Those values
exist in server memory as `ValidatedWindowEvidence` but do not reach the client
until final synthesis completes.

The client must never manufacture provisional evidence from counts. Therefore
extend the existing event rather than inventing model status text.

## New exact model

Add a strict `ProvisionalWindowRange` model with exactly:

```text
source_range_index: nonnegative integer
thread_id: nonblank bounded string
start_message_id: nonblank bounded string
end_message_id: nonblank bounded string
summary: nonblank string or null
relevance: nonblank string or null
normalizations: list containing only "endpoint_order_swapped"
```

Use existing repository length bounds and strict-model behavior. Do not add a
provisional `range_id`: final IDs are assigned only when the complete ledger is
built in deterministic window order.

## Extended `window_completed`

Add exactly:

```text
accepted_ranges: list[ProvisionalWindowRange]
window_uncertainties: list[nonblank string]
```

Additional invariants:

- `accepted_range_count == len(accepted_ranges)`.
- `source_range_index` values are unique within the event.
- List order follows source-range order.
- Every item has the event's `window_id` implicitly; do not repeat it in each
  item.
- Empty `accepted_ranges` is valid only with `accepted_range_count == 0`.
- `window_uncertainties` contains the validated window uncertainty list once;
  do not repeat it per range.

## Emission source

Populate the new fields from the already validated
`ValidatedWindowEvidence` object at the current `window_completed` yield.

For each accepted range use the validated:

- source index;
- authoritative thread ID;
- normalized endpoint order;
- summary;
- relevance;
- normalization record.

Do not emit rejected ranges. Their count remains visible and full diagnostics
remain in final evidence validation.

## Cost and behavior invariants

The change must not alter:

- provider request payloads;
- provider call count;
- retry behavior;
- concurrency;
- window packing;
- ledger construction;
- synthesis input;
- final result;
- usage accounting;
- debug-capture policy.

No accepted range may be truncated or capped for display convenience. The
client may collapse presentation, but the contract carries all accepted
ranges.

## Temporary Python contract mirror

Update only the `window_completed` validation branch in
`message_evidence_workstation/client_api/contracts.py` so server contract tests
continue to compare strict implementations. Apply the same exact keys and
invariants. This is not authorization to change the Python application.

