# Mission and invariants

## Mission

Replace the two conversational implementations with one evidence-ledger
pipeline and add real retrieval assistance:

```text
server extracts retrieval queries
  -> server embeds those queries
  -> client performs exact local vector lookup in the selected EVW revision
  -> server validates and ranks candidate message IDs
  -> server plans one or more exhaustive windows
  -> every window is inspected
  -> one canonical evidence ledger is built
  -> the complete ledger is synthesized
  -> hierarchical ledger compaction is retained only as an explicit,
     loudly reported context-overflow fallback
```

The same behavior applies whether the complete working corpus fits one analysis
window or requires many. There is no separate whole-corpus answer path.

## Non-negotiable ownership

- The FastAPI server owns providers, models, prompts, query extraction,
  embedding generation, retrieval policy, ranking, candidate-range
  construction, window planning, evidence extraction, ledger validation,
  compaction, synthesis, retries, accounting, and operational visibility.
- The client owns the EVW, explicit working-corpus revision selection, local
  vector storage, and exact local vector-distance queries.
- The server never opens, receives, or persists an EVW.
- The Python client remains test equipment. Change only the gateway/workflow/UI
  surfaces needed to exercise this server contract.
- Flutter is not modified in this packet.
- EVW schema, migration, revision lifecycle, evidence blocks, and embedding
  artifact storage are not modified in this packet.

## Evidence completeness

- Every supplied corpus message is assigned to exactly one analysis window.
- Retrieval suggestions never select, skip, reorder, shrink, or prioritize
  windows.
- Retrieval suggestions are attention aids, not evidence and not filters.
- Models must inspect every message in their assigned windows.
- Every valid extracted evidence range remains in the canonical ledger.
- No top-N evidence cap, truncation, silent omission, or arbitrary evidence
  budget is permitted.
- Dispositions (`used`, `redundant`, `not_material`) annotate records; they do
  not remove records from the returned ledger.
- Ledger compaction never mutates the canonical ledger and must preserve every
  original range ID exactly once and in order at every level.

## One conversational path

Delete the `whole_corpus_answer` operation and its special prompt, output
contract, events, router branch, tests, and admin assignment.

The analysis planner produces:

- `single_window_ledger` when every message fits one extraction payload; or
- `multi_window_ledger` when deterministic balanced packing needs multiple
  extraction payloads.

Both then build the same ledger and call the same synthesis operation.

## Retrieval behavior

- Keep the server-side `retrieval_terms` model call.
- Expose it through one explicit conversational retrieval-plan endpoint.
- Embed every extracted query through the existing server embedding endpoint.
- Perform message-level local vector retrieval only for this experiment.
- Do not add FTS5, chunk retrieval, distance thresholds, or full-question
  embeddings to this first semantic experiment.
- Fuse multi-query hits deterministically with reciprocal-rank fusion.
- Send compact message-ID ranges only; never duplicate transcript text in
  retrieval suggestions.
- Measure evidence found outside suggestions as a first-class diagnostic.

## Failure behavior

- Fail noisy. Preserve the original cause.
- No silent fallback between retrieval modes, providers, models, strategies,
  or prompts.
- No automatic retry beyond the existing active server retry configuration.
- No malformed-output repair, response defaults, implicit candidate
  truncation, or compatibility aliases.
- If required embeddings are unavailable or geometrically incompatible, fail
  before submitting conversational analysis.
- If compaction cannot preserve complete range-ID coverage or cannot fit within
  configured depth, fail the request.

## Public surface

The final product API contains exactly four POST endpoints:

1. `/v1/keyword-expansion`
2. `/v1/conversational-retrieval-plan`
3. `/v1/conversational-analysis`
4. `/v1/embeddings`

Do not add capabilities, public window, public ledger, public synthesis, debug,
or compatibility product endpoints.

## Security and persistence

- Keep the current loopback-only rule while admin authentication is disabled.
- Existing temporary exact debug capture remains admin-controlled and
  server-side.
- Normal structured logs and durable accounting remain content-free.
- Exact corpus, prompt, provider, candidate, and response content appears only
  in an explicitly active temporary debug-capture session.
- Authentication, billing, subscriptions, and account-scoped debug capture
  remain deferred.

