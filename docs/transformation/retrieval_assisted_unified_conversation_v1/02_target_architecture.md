# Target architecture

## End-to-end sequence

### Phase A: server retrieval plan

The client sends only the question to
`POST /v1/conversational-retrieval-plan`.

The server:

1. captures the active immutable configuration;
2. calls the configured `retrieval_terms` operation once;
3. returns ordered query IDs and text;
4. returns the active embedding geometry/fingerprint;
5. returns the active local-search and fusion policy;
6. returns a compatibility fingerprint for the retrieval-relevant settings.

The server stores no plan or user content.

### Phase B: server query embeddings

The client sends all extracted queries in one `/v1/embeddings` workload. The
server owns the embedding implementation and returns vectors under the existing
strict streaming contract.

The client verifies profile/fingerprint, dimensions, and normalization against
the selected EVW embedding cache.

### Phase C: exact local retrieval

For each query vector, the client performs an exact message-level vector search
within the selected immutable working-corpus revision. It preserves rank and
distance for every returned candidate.

The client sends only query ID, message ID, rank, and distance with the normal
conversational request. It never duplicates message text in candidate data.

### Phase D: one server analysis path

The server:

1. validates the request, plan compatibility, and every candidate;
2. fuses candidates deterministically;
3. selects and groups compact attention suggestions;
4. plans one or more balanced windows using the extraction model's exact
   payload budget;
5. assigns each suggestion only to the window containing its hit messages;
6. exact-checks every generated provider payload;
7. runs `window_evidence_extraction` for every window;
8. builds one immutable canonical ledger;
9. preflights direct synthesis with the complete ledger;
10. uses direct synthesis when it fits;
11. otherwise invokes the retained, loudly reported hierarchical ledger
    compaction fallback;
12. synthesizes the final answer;
13. validates one disposition for every original range ID;
14. returns one final ledger entry for every original range ID using the
    original boundaries, summary, and relevance;
15. computes retrieval-overlap diagnostics.

## Window planning

There is no whole-corpus router branch.

`window_evidence_extraction` is the only transcript-analysis operation. Its
active model profile, prompt, output reservation, safety margin, tokenizer, and
configured utilization determine packing.

- If all messages fit one extraction payload, plan exactly one window.
- Otherwise compute the minimum safe window count and pack balanced,
  chronological, no-overlap windows.
- Preserve thread boundaries when possible.
- Split large threads only between messages.
- Reject an individually unsplittable message.
- Every input message must appear exactly once across planned windows.

The result strategy is:

- `single_window_ledger`; or
- `multi_window_ledger`.

## Retrieval payload reservation

An A/B run must not change window boundaries merely because one arm exposes
suggestions and another does not.

When a non-null retrieval plan accompanies analysis, the planner reserves the
same deterministic worst-case suggestion overhead for every mode:

- all extracted queries at their contract maximum;
- the configured maximum selected suggestion messages;
- maximum legal ID lengths;
- the exact canonical JSON suggestion structure.

Use the active extraction tokenizer to calculate the reserve. Display the
calculated reserve read-only in admin. This is not a manually entered token
guess.

After assignment, exact-check the real payload. Exceeding the configured input
budget is a server/configuration failure; never drop suggestions or messages to
make it fit.

The planner emits a stable `window_plan_hash` over ordered window IDs and their
ordered message IDs. A/B comparison is invalid if hashes differ.

## Request-local state

Retrieval plans, vectors, candidates, windows, model outputs, ledgers,
compaction summaries, and overlap diagnostics remain request-local RAM only
except:

- the client may persist the final user-visible conversation under existing
  EVW rules;
- content-free server usage/accounting remains durable;
- exact content may be temporarily captured only while admin debug capture is
  active;
- the diagnostic runner writes explicit `.tmp` artifacts outside the EVW.

## Concurrency and cancellation

Keep the existing server admission, operation queues, retry policy, circuits,
deadlines, and bounded concurrent-window execution.

- Retrieval-plan calls use `retrieval_terms` operation limits.
- Query embedding workloads use existing embedding limits.
- Analysis captures one config snapshot at ingress.
- Every required window must complete.
- Cancellation stops queued/future work and cancels active request tasks.
- A required-stage failure produces one terminal failure, never a partial
  answer.
