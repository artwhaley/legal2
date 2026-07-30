# Mission and invariants

## Mission

Move conversational analysis to this single explicit sequence:

```text
server plans how to answer the user's question
  -> client executes server-specified local semantic retrieval, if enabled
  -> server deterministically packs the complete corpus into one or more windows
  -> each extraction call receives the same frozen analysis plan
  -> valid evidence ranges are accepted independently
  -> malformed ranges are quarantined without poisoning valid sibling ranges
  -> one canonical ledger is built from every accepted range
  -> synthesis classifies every ledger range by answer relevance
  -> synthesis answers the planned question and cites structured findings
```

The goal is high-recall candidate collection followed by disciplined,
auditable synthesis. Over-collection is acceptable. Under-collection caused by
query literalism, hidden filtering, or discarding an otherwise valid model
response is not.

## Ownership

- The FastAPI server owns the planning model, planning prompt and schema,
  provider/model routing, retrieval policy, window packing, extraction prompt,
  range validation, normalization, ledger construction, compaction, synthesis,
  relevance dispositions, retries, accounting, and observability.
- The client owns the EVW, working-corpus revision selection, local vector
  cache, and exact local vector-distance lookup.
- The client executes the server's retrieval instructions; it does not invent,
  interpret, edit, rank, or supplement the analysis plan.
- The server never opens, receives, or persists an EVW.
- The Python client remains test equipment. Change only the gateway, workflow,
  progress, and result rendering needed to exercise the production server
  contract.
- Flutter, EVW schema, EVW lifecycle, stored embeddings, and evidence blocks
  are outside this packet and must not change.

## One conversational path

The existing unified path remains:

- a corpus that fits is one extraction window;
- a larger corpus is deterministically balanced into multiple windows;
- both build the same ledger and invoke the same synthesis operation;
- compaction remains a context-overflow fallback, not an evidence-reduction
  policy.

Do not restore a direct whole-corpus answer path or add a second orchestration
implementation.

## Planning invariants

- Every conversational analysis begins with one server-owned planning call.
- The planner sees the user's question, not the corpus.
- The plan operationalizes ambiguous concepts generically. It must not contain
  test-specific definitions hard-coded by application code or seed prompts.
- The plan preserves the user's intent. It may clarify ordinary manifestations
  of a concept but may not silently change the requested question.
- The plan defines what answers the question, what is in scope, what is out of
  scope, which semantic queries aid retrieval, and what the answer must deliver.
- There is no global instruction to collect contradictory evidence. Evidence
  that contradicts a proposition is sought only when the user's question or the
  resulting plan calls for it.
- One frozen plan is passed unchanged to every extraction window, every
  compaction call, and final synthesis.
- Planning failures fail noisily. There is no fallback to raw query terms.

## Evidence invariants

- Every supplied corpus message is assigned to exactly one extraction window.
- Retrieval suggestions remain advisory and never select or eliminate windows,
  messages, or evidence.
- Extraction favors recall: when a passage plausibly answers the plan but its
  significance is uncertain, include it and explain the uncertainty.
- Every independently valid range survives into the canonical ledger.
- A malformed sibling range does not invalidate a valid range.
- The server never guesses a fabricated message ID, repairs an unknown ID
  prefix, changes a declared thread, or invents a boundary.
- The only allowed identity normalization is a deterministic endpoint swap
  when both supplied IDs exist in one thread and their reversed array order is
  unambiguous.
- Rejected ranges remain visible as validation diagnostics but are not evidence
  and never enter synthesis as ledger records.
- No numeric model-generated evidence score or confidence score is introduced.
- No range is dropped because of a top-N count, score, desired answer length, or
  arbitrary evidence budget.

## Synthesis invariants

- Synthesis answers the frozen plan, not a generic evidence-review task.
- Every accepted ledger range receives exactly one categorical disposition:
  `direct_evidence`, `useful_context`, or `not_responsive`.
- All three categories remain in the returned ledger.
- `not_responsive` material is not presented as evidence answering the user.
- `useful_context` appears in the answer only where it helps explain direct
  evidence.
- Structured findings cite range IDs. Findings may cite only accepted ledger
  ranges and each finding must cite at least one `direct_evidence` range.
- Compaction never decides final relevance and never mutates original ledger
  records.

## Failure and visibility

- Top-level malformed model output still fails the operation.
- Independently malformed ranges produce an explicit partial-validation result.
- Partial validation is never labeled complete and never hidden in logs,
  stream progress, the final result, the Python test UI, or debug capture.
- Existing configured retries remain visible. Do not add silent retries,
  provider/model fallback, response defaults, or best-effort ID guessing.
- Normal structured logs and durable accounting remain content-free.
- Exact questions, plans, messages, prompts, ranges, and responses appear only
  in an explicitly active temporary server debug-capture session.

## Public product surface

The final server exposes exactly four product POST routes:

1. `/v1/keyword-expansion`
2. `/v1/conversational-plan`
3. `/v1/conversational-analysis`
4. `/v1/embeddings`

Remove `/v1/conversational-retrieval-plan`; do not retain an alias.

## Explicitly deferred

- Authentication, billing, subscriptions, account scope, and BYOK.
- Flutter production integration.
- EVW changes.
- FTS/chunk retrieval experiments.
- Numeric evidence scoring or learned reranking.
- Automatic user-query clarification.
- Automatic targeted repair calls for quarantined ranges.

