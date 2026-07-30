# Target behavior and failure policy

## One result-preserving pipeline

The server keeps the current unified single/multi-window architecture:

```text
frozen plan
-> exhaustive windows
-> independently verified ranges
-> immutable canonical ledger
-> optional compaction
-> synthesis
-> granular result inspection
-> complete / complete_with_warnings / partial
```

Validation has two jobs only:

1. prove which citations and source ranges map to real supplied data;
2. explain structural/model-output limitations to the user and operator.

Validation does not decide whether a model judgment is good enough to publish.

## Normal successful result

The synthesis model returns an overview and a list of result objects. Each
result contains its own probability category and citations. There is no
parallel disposition list.

The server:

1. preserves the model's overview verbatim;
2. validates each result independently;
3. separates exact cited IDs into verified and unverified lists;
4. preserves model order inside each probability group;
5. returns high probability first;
6. returns lower probability second;
7. appends any valid ledger ranges omitted by synthesis as unclassified
   candidates after lower-probability model results;
8. attaches warnings without replacing the answer.

## Readable but nonconforming synthesis

Readable means provider content containing an intelligible nonblank statement.
It does not require valid JSON. A refusal, limitation, or plain-language error
from the model is still readable and must be returned.

If the response is not exact schema JSON:

- preserve complete raw provider content;
- use it as the returned answer;
- attempt only explicitly specified deterministic parsing/normalization from
  file 04;
- expose any safely recovered structured results;
- return `complete_with_warnings` when all windows were available, otherwise
  `partial`;
- do not automatically repeat synthesis.

Malformed JSON is not proof that the answer is unintelligible.

## Empty or absent synthesis

An output is machine-defined as unusable for synthesis retry only when:

- the provider response has no string content;
- content is empty or whitespace-only; or
- the provider response envelope is invalid and supplies no content;
- content contains only formatting/punctuation; or
- a parseable object contains no nonblank overview, result statement, or other
  human-readable statement.

Do not create a subjective gibberish classifier.

Retry only `ledger_synthesis` under the operation's explicit configured
attempt/deadline policy. The retry is visible in stream/log/accounting.

If synthesis remains unavailable:

- return `partial`;
- return the complete validated canonical ledger;
- return validated extraction summaries as unclassified candidates;
- set answer source to `synthesis_unavailable`;
- state that narrative synthesis was unavailable;
- do not fabricate an answer or silently switch model/provider.

## Per-window failure

Every window is independent. A window outcome is:

- `completed`;
- `completed_with_rejected_ranges`;
- `unavailable_after_retries`.

A structurally unusable extraction envelope retries only that window. A
transient provider failure follows existing explicit provider retry policy.

After attempts are exhausted:

- record the window as unavailable;
- do not cancel or discard completed sibling windows;
- continue remaining windows;
- build the ledger from validated ranges;
- synthesize with an exact coverage report;
- return `partial`.

If all windows are unavailable and no validated evidence exists, the request
may fail after every targeted attempt is exhausted.

## Range-level behavior

Within a parseable extraction envelope:

- validate each candidate range independently;
- preserve valid sibling ranges;
- correct only deterministic endpoint order/thread identity cases from file
  04;
- quarantine unknown/ambiguous IDs;
- report rejected candidate diagnostics;
- continue.

All-valid, some-invalid, and all-invalid parseable envelopes are usable window
outputs. An all-invalid envelope contributes no ledger records and explicit
warnings; it does not terminate the search.

## Compaction failure

Compaction is optional orchestration required only to fit final synthesis.

If compaction cannot preserve exact original range coverage:

- stop compaction;
- preserve the original ledger byte-for-byte;
- do not submit incomplete compacted material to synthesis;
- if the original ledger cannot fit, return `partial` with the original
  ledger and `synthesis_unavailable`;
- report exact compaction diagnostics.

No extracted evidence is discarded.

## Result ordering

The server deterministically outputs:

1. all model results labeled `high_probability`, preserving model order;
2. all model results labeled `lower_probability`, preserving model order;
3. all unclassified validated ledger ranges in canonical range order.

Unknown probability labels do not drop a result. They are normalized to
unclassified presentation after the lower-probability section and receive a
warning. They are not silently relabeled `lower_probability`.

The Python GUI and future Flutter client render a visible boundary between
high-probability and all later material. Unclassified candidates are a labeled
subsection beneath lower-probability results, not a third competing confidence
category.

## Terminal statuses

### `complete`

- all planned windows produced usable outputs;
- synthesis returned exact structured output;
- every reported citation is verified;
- every ledger range is cited by at least one result;
- no corrective normalization or warning occurred.

### `complete_with_warnings`

- all planned windows produced usable outputs;
- readable synthesis exists;
- one or more model-structure, classification, citation, normalization, or
  omitted-ledger-range warnings occurred.

### `partial`

- useful answer text or validated evidence exists;
- one or more windows were unavailable, ranges were rejected, compaction
  prevented synthesis, or final synthesis was unavailable.

### `failed`

- no useful answer and no validated evidence can be returned after targeted
  retries; or
- request/planning/budget/internal execution cannot produce a result.

`complete_with_warnings` and `partial` terminate with a `completed` stream
event. Only `failed` emits `failed`.

## Cancellation

Preserve current explicit cancellation behavior. Cancellation is not silently
converted into a persisted partial answer. Completed provider calls remain
accounted and debug-captured according to current policy. Resume support is
outside this packet.
