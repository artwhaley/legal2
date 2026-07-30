# Source integrity and deterministic normalization

## Separate evidence identity from model judgment

The canonical evidence ledger answers only:

- which real messages form this candidate range;
- where the range came from;
- what extraction said it may show;
- what mechanical corrections/rejections occurred.

The synthesis result answers:

- what the model thinks the range(s) mean;
- how likely the result is to answer the frozen plan;
- what uncertainty the model sees.

Never use a synthesis category to decide whether a verified evidence range
exists or remains visible.

## Extraction envelope parsing

Preserve the current two-stage approach:

1. parse one top-level extraction envelope;
2. validate each item in `evidence_ranges` independently.

Extend handling as follows:

- A valid JSON object with the supplied `window_id` and a list-valued
  `evidence_ranges` is usable even if `uncertainties` is missing or malformed.
  Preserve valid uncertainty strings and record a warning for unusable values.
- Extra top-level fields are ignored only for extraction salvage and are
  reported. Generic model parsing for planner/keyword operations remains
  strict.
- A non-JSON or no-object extraction response is machine-unusable and invokes
  targeted window retry from file 05.

Do not add loose global Pydantic coercion. Implement a dedicated extraction
salvager.

## Candidate range validation order

For each proposed range:

1. require an object;
2. collect only exact string values for start/end IDs;
3. verify both IDs exist in the supplied window;
4. derive the authoritative thread from source messages;
5. require both endpoints to share that thread;
6. correct endpoint order when reversed and contiguous;
7. verify the resulting inclusive interval contains only that thread;
8. deduplicate exact normalized endpoint pairs;
9. retain nonblank model summary/relevance when present;
10. if summary/relevance is missing, keep the real source range and report
    missing model description rather than fabricate text.

The current behavior that rejects a range solely because the declared
`thread_id` is wrong must change when both valid endpoints prove one
unambiguous real thread. Use the source thread and emit `THREAD_ID_CORRECTED`.

Reject only the candidate range when:

- either endpoint is unknown;
- endpoints belong to different threads;
- the inclusive interval crosses a thread boundary;
- the range object has no recoverable endpoints;
- the intended interval remains ambiguous.

## Synthesis JSON normalization

Before treating synthesis as raw prose, permit only:

- trim outer whitespace;
- remove one complete outer Markdown JSON fence;
- parse one complete JSON object when all non-whitespace outside it is a
  Markdown fence or an explicitly captured explanatory prefix/suffix;
- preserve the complete raw provider content whenever anything was removed.

Do not:

- repair malformed JSON punctuation heuristically;
- rename guessed fields;
- fill omitted required fields with empty values;
- rewrite result statements;
- invent probability;
- invent citations.

If a JSON object contains useful known fields but fails the exact model schema,
salvage each known component independently and return warnings.

## Result-level citation validation

For each model result:

1. preserve `statement`, `probability`, `range_ids`, and `uncertainty` exactly
   in reported fields;
2. compare every reported range ID to the canonical request-local ledger;
3. build `verified_range_ids` in first-reported order;
4. build `unverified_range_ids` in first-reported order;
5. record exact duplicate IDs without repeating links;
6. assign citation status:
   - all known, at least one: `verified`;
   - mixed known/unknown: `partial`;
   - none known or no usable IDs: `unverified`.

Unknown IDs never appear as verified links, ledger records, overlap counts, or
source-message navigation targets.

## Result classification

- Known `high_probability` and `lower_probability` values are preserved.
- Missing/unknown/malformed probability does not remove the result.
- Such a result receives `classification_status=unclassified`, retains its
  reported value in diagnostics, and appears after lower-probability results.
- The server never silently relabels an unknown result.

## Unverified statements

If a model result has no verified range:

- do not present it as corpus-backed high/lower evidence;
- preserve it under `unverified_model_statements`;
- include exact statement, reported IDs, and warnings;
- never create a source-navigation action for it.

This preserves what the model said while eliminating fabricated messages from
the evidence presentation.

## Omitted ledger ranges

After validating all synthesis results, calculate canonical range IDs not
present in any verified result citation.

Return every omitted range in `unclassified_evidence` using:

- exact canonical range ID;
- exact extraction summary/relevance if present;
- exact boundaries and source metadata already in the ledger;
- reason `not_referenced_by_synthesis`.

Do not ask the server to infer probability. The UI presents this material after
the lower-probability section.

## Model quotations

Do not attempt semantic quote validation in this packet. It is brittle.

Instead:

- prompts tell synthesis to paraphrase and cite range IDs;
- model prose remains advisory;
- evidence details are rendered from the EVW by verified IDs;
- no model-generated message body is stored or displayed as canonical
  transcript text.

## Accounting and observability

Every provider attempt is accounted regardless of conformance. Distinguish:

- provider transport outcome;
- provider content received;
- parse/conformance outcome;
- source-citation verification outcome;
- final request outcome.

Normal logs contain only counts/codes/IDs already allowed by current
content-free policy. Exact model inputs/outputs remain available only through
explicit temporary debug capture and the public response being returned to its
requesting client.

