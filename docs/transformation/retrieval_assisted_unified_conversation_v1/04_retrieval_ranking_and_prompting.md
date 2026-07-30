# Retrieval ranking and prompting

## Local query execution

The Python harness uses the retrieval-plan response exactly:

1. Submit every returned query in one `/v1/embeddings` workload using
   `query_id` as the embedding item identity.
2. Verify accepted profile/fingerprint, dimensions, and normalization against:
   - the retrieval plan; and
   - `embedding_cache_state` in the selected EVW.
3. For each vector, run the existing exact message-level local query with
   `top_k_per_query`.
4. Add deterministic 1-based rank in SQL result order.
5. Preserve all raw hits for the server and diagnostic artifacts.

Do not:

- embed the full question separately;
- run FTS5;
- run chunk embeddings;
- infer distance thresholds;
- search outside the selected immutable revision;
- return body text in candidate payloads;
- rebuild message embeddings automatically.

If the local message embedding index is not ready or geometry differs, fail
before conversational submission. The current large and small v15 fixture
revisions already have ready message embeddings.

## Server fusion

Validate hits before ranking.

For each unique message:

```text
RRF score = sum over matching queries of
            1 / (retrieval_rrf_constant + rank)
```

Order unique candidate messages by:

1. RRF score descending;
2. best distance ascending;
3. supplied corpus ordinal ascending;
4. message ID ascending.

Select the first
`retrieval_maximum_prompt_suggestion_messages`. This is an explicit limit on
advisory prompt hints, not evidence and not corpus filtering.

Log/capture every raw candidate and every selected/unselected decision. Do not
apply a distance threshold or silently discard malformed hits.

## Suggestion ranges

After windows are final:

- assign each selected message to its containing window;
- within each window and thread, merge only directly adjacent selected
  messages;
- never expand around a hit;
- never merge across an unselected gap, thread, or window;
- preserve selected anchor message IDs and matching query IDs;
- sort ranges by window message order.

Prompt shape:

```json
{
  "thread_id": "thread",
  "start_message_id": "m10",
  "end_message_id": "m11",
  "hit_message_ids": ["m10", "m11"],
  "matched_query_ids": ["q0001", "q0003"]
}
```

The window user object contains the ordered query ID/text list once and that
window's suggestion ranges. Do not expose distances or RRF scores to the model.

## Extraction prompt

Replace the current terms-only wording with this binding behavior, preserving
the existing legal-evidence injection policy and strict output JSON:

> Inspect every message in the supplied chronological window for the question.
> Retrieval queries and retrieval suggestions are attention aids only. A
> suggestion identifies messages that deserve specific inspection, but it is
> not evidence, may be incidental or nonresponsive, and is not exhaustive.
> You may reject any suggestion. Capture every materially distinct supporting,
> contradicting, weak, or qualifying passage anywhere in the complete assigned
> window, including passages outside all suggestions. Expand an evidence range
> beyond suggested boundaries whenever surrounding messages form the relevant
> exchange. Suggestions never justify omitting evidence.

The extraction prompt must also state that message and thread IDs are opaque.
`start_message_id` and `end_message_id` mean the first and last messages in the
supplied array, regardless of apparent numeric suffix order. `thread_id` must
be copied from the selected messages' `thread_id` field and may never be filled
with a message ID. This is a strict contract, not a repair rule.

Keep the existing strict evidence-range output schema.

The one-window case receives the complete corpus plus all suggestion ranges.
The multi-window case receives the complete assigned window plus only ranges
that intersect it.

## Synthesis prompt

Synthesis does not need retrieval suggestions. It receives the canonical
ledger, coverage report, and complete range metadata. Retrieval-overlap
analysis is deterministic server code after synthesis and must not influence
range dispositions.

## Diagnostic interpretation

For every final range, determine:

- whether it overlaps at least one suggestion;
- which suggestion IDs overlap;
- whether it was found outside all suggestions;
- its final disposition.

Also determine which shown suggestions overlap no final evidence.

Do not call suggestions successful merely because the final answer mentions
similar words. Comparison uses exact message-ordinal range overlap.
