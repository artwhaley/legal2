# Orchestration, retries, and partial results

## Retry ownership

Retries are operation-local. Never repeat completed upstream work merely to
repair a downstream output.

```text
planning failure       -> retry planning only under configured policy
window N transport     -> retry window N only
window N unusable body -> retry window N only
compaction group N     -> retry group N only when output is empty/unusable
synthesis empty body   -> retry synthesis only
readable synthesis     -> return it; do not retry for conformance warnings
```

Existing explicit provider HTTP retry rules remain. Extend model-runtime
execution with a clearly named empty/unusable-output retry category only for
operations requiring machine-readable source identity. Do not make every
schema warning retryable.

## Window task isolation

Current batch orchestration allows one task exception to cancel siblings and
terminate the request. Replace that behavior.

Each window task returns a typed outcome rather than throwing ordinary
provider/model failures through the entire batch:

```text
WindowCompleted(validated output, usage, diagnostics)
WindowUnavailable(error code, attempts, usage, diagnostics)
```

Internal programming errors and cancellation may still raise.

The batch:

- continues collecting every task;
- preserves deterministic window order;
- emits completion/unavailable events;
- builds the ledger from completed outcomes;
- includes unavailable windows in coverage;
- never reassigns range IDs based on completion order.

## Synthesis input with partial coverage

Synthesis receives:

- exact frozen analysis plan;
- complete planned-window coverage report;
- accepted canonical ledger records;
- rejected-range counts/reasons;
- unavailable-window counts/reasons;
- explicit instruction that answer completeness may be affected.

The synthesis model must answer from available evidence and mention material
coverage limitations. Failure to mention them becomes a warning, never a
discard gate.

## Empty ledger

A usable exhaustive scan may produce zero accepted ranges.

If every window completed:

- synthesis still runs;
- it may answer that no responsive evidence was found;
- result may be `complete` or `complete_with_warnings`.

If windows were unavailable and the ledger is empty:

- synthesis may run with coverage warnings if any window outputs are usable;
- if no window produced any usable output, exhaust targeted retries and then
  return `failed` because no useful evidence basis exists.

## Synthesis invocation API

The generic current `run_model_operation` returns only a strictly parsed
Pydantic model. Synthesis needs a result-preserving invocation path that
returns:

- raw provider content;
- usage/accounting;
- provider metadata;
- exact-parse result or validation error;
- normalization records.

Implement this as a narrow extension or explicit synthesis wrapper, not a
second provider stack. Transport, resilience, debug capture, secrets,
admission, accounting, and cancellation remain shared.

Do not weaken strict parsing for analysis planning, keyword expansion, or other
operations globally.

## Readable synthesis completion

When nonblank synthesis content arrives:

1. emit `ledger_synthesis_received`;
2. persist/account the provider attempt as transport success;
3. parse/salvage/validate components;
4. emit `synthesis_validation_completed`;
5. assemble result;
6. emit terminal `completed`.

No post-receipt warning may convert this to `failed`.

## Synthesis unavailable completion

When configured synthesis attempts exhaust without nonblank content:

1. preserve ledger and usage;
2. produce `answer_source=synthesis_unavailable`;
3. place all canonical ranges in unclassified evidence;
4. set `completion_status=partial`;
5. emit warning and terminal `completed`.

If the ledger is empty and no useful window output exists, emit `failed`.

## Compaction orchestration

Keep current direct-fit preflight and loud compaction events.

For each compaction output:

- exact known IDs may be reordered deterministically to canonical order;
- unknown/duplicate/missing IDs make the compacted group unusable;
- unusable empty output may retry that group;
- exhausted group failure stops compaction but preserves original ledger.

If original synthesis payload cannot fit after compaction failure:

- do not send an incomplete ledger;
- return partial ledger-only result;
- emit `COMPACTION_UNAVAILABLE` and `SYNTHESIS_UNAVAILABLE`.

## Status derivation

Derive status from facts:

```text
partial if:
  unavailable windows > 0
  OR rejected ranges > 0
  OR compaction prevented synthesis
  OR synthesis unavailable

else complete_with_warnings if:
  any source normalization occurred
  OR synthesis was raw/nonconformant
  OR any citation is partial/unverified
  OR any result is unclassified
  OR any ledger range was omitted by synthesis
  OR any other result warning exists

else complete
```

Never let a model-supplied field choose terminal status.

## Usage and retries

The final usage summary includes every planning/extraction/compaction/synthesis
attempt. If provider cost is incomplete, retain current explicit incomplete
accounting. Warnings must not erase usage.

Model-output retries must be visible as `retry_wait` or a new exact
`model_output_retry` event with operation/window/group identity. Do not pretend
the first attempt succeeded invisibly.

