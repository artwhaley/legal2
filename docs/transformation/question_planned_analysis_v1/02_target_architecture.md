# Target architecture

## End-to-end sequence

### A. Plan the question

The client sends the question to `POST /v1/conversational-plan`.

The server:

1. captures the active configuration snapshot;
2. calls `analysis_planning` once;
3. validates the complete planning output;
4. assigns deterministic retrieval query IDs;
5. resolves the active semantic-retrieval policy and embedding geometry;
6. returns a complete frozen analysis plan and compatibility fingerprint;
7. persists no plan or question.

### B. Execute local retrieval, if configured

The plan response tells the client whether local semantic assistance is
`none` or `semantic_ranges`.

For `none`, the client performs no embedding call and returns no hits.

For `semantic_ranges`, the client:

1. submits every server-provided retrieval query in one `/v1/embeddings`
   workload;
2. validates embedding geometry against the selected EVW revision;
3. performs exact message-level local vector lookup for each query;
4. returns query ID, message ID, rank, and distance only.

This is deterministic execution of server policy, not client-side planning.

### C. Analyze the complete corpus

The client sends the complete selected working corpus plus the exact echoed
analysis context to `/v1/conversational-analysis`.

The server:

1. validates question, frozen plan, fingerprint, policy, geometry, and hits;
2. fuses semantic candidates exactly as the current server does;
3. constructs advisory suggestion ranges;
4. plans the minimum safe number of deterministic balanced windows;
5. passes the same frozen analysis plan to every window;
6. scans every message in every window;
7. parses each model response envelope;
8. validates and normalizes each proposed range independently;
9. retains valid ranges and quarantines invalid ranges;
10. builds one canonical ledger in window/range order;
11. preflights direct synthesis;
12. uses existing loud hierarchical compaction only if required by measured
    context;
13. passes the same frozen plan to compaction and synthesis;
14. synthesizes structured findings and one categorical disposition per
    accepted range;
15. returns the complete accepted ledger plus explicit rejected-range
    diagnostics.

## Plan identity and request-local state

The server is stateless between the planning and analysis requests.

- `analysis_plan_id` is a UUID used for correlation, not persistence.
- The client echoes the exact plan object and retrieval queries.
- The compatibility fingerprint is SHA-256 over canonical JSON defined in file
  03.
- The analysis endpoint recomputes the fingerprint against the active relevant
  configuration.
- A mismatch fails HTTP 409 `ANALYSIS_PLAN_STALE`.
- Unrelated configuration changes do not invalidate a plan.
- A planning prompt/model/policy/geometry change does invalidate it.
- Do not silently regenerate a stale plan inside the analysis endpoint.

All plans, vectors, hits, windows, raw model output, rejected ranges, ledgers,
and findings are request-local RAM except:

- content-free durable usage/accounting;
- temporary exact debug capture when explicitly enabled;
- client persistence of the final visible conversation under existing EVW
  rules;
- explicit diagnostic artifacts outside the EVW.

## Windowing

Keep the existing deterministic planner and fixed semantic-suggestion reserve.
The plan object itself is now part of every extraction payload and therefore
part of exact token accounting.

- Determine window count using the active extraction model/tokenizer and the
  exact frozen plan shape.
- Every message appears exactly once.
- Retrieval mode or suggested-hit content must not change message coverage.
- A fitting corpus remains one extraction window followed by synthesis.
- An oversized corpus remains multiple extraction windows followed by the same
  synthesis contract.

## Partial range acceptance

The provider response has two validation levels:

1. envelope validation, which is atomic;
2. range validation, which is independent per array element.

A bad JSON object, missing/extra top-level field, wrong `window_id`,
non-list `evidence_ranges`, or invalid `uncertainties` fails the window call.

A malformed range object, unknown ID, wrong thread, cross-thread interval,
duplicate interval, blank summary, or ambiguous boundary rejects only that
range. Valid sibling ranges continue.

If any range is rejected, the request may complete with
`completion_status=partial_evidence_validation`; it may never report
`complete`.

## Synthesis

The canonical ledger remains immutable. Compaction summaries may make the
ledger fit but cannot alter range identity, source text, summary, relevance, or
validation status.

Final synthesis returns:

- a reviewer-facing answer;
- a short summary;
- structured findings with cited range IDs;
- exactly one disposition for every accepted range;
- uncertainties.

There is no model-generated numeric relevance score. Retrieval ranking remains
an attention diagnostic and never becomes an evidence filter.

## Concurrency, retry, and cancellation

Keep current bounded window concurrency, provider queues, deadlines, configured
retries, circuits, heartbeats, cancellation, and usage aggregation.

- Each window is envelope-validated and range-validated before its completion
  event.
- A configured retry reruns a failed model operation, not individual malformed
  ranges.
- Do not add an automatic repair call in this packet.
- Cancellation stops active and queued work.
- A structural stage failure remains terminal.
- Partial range validation is a completed result with an explicit warning, not
  a hidden retry or a terminal provider failure.

