# Contracts and migration

## Model synthesis output

Replace `LedgerSynthesisOutput` with this exact conceptual shape:

```json
{
  "overview": "complete reviewer-facing answer overview",
  "results": [
    {
      "probability": "high_probability",
      "statement": "one responsive or plausibly responsive result",
      "range_ids": ["r000001"],
      "uncertainty": null
    }
  ],
  "uncertainties": []
}
```

Rules:

- `overview` is a nonblank string.
- `results` is a list and may be empty.
- `probability` is exactly `high_probability|lower_probability`.
- `statement` is nonblank.
- `range_ids` is a nonempty list in conforming output.
- `uncertainty` is a nonblank string or null.
- `uncertainties` contains nonblank strings.
- no separate `answer`, `answer_summary`, `findings`, or
  `range_dispositions` is present in the model schema.

Remove the current arbitrary 20,000-character synthesis-answer cap. Provider
`max_output_tokens`, request admission, HTTP limits, and bounded debug capture
already constrain output. Use a dedicated bounded-output limit only if an
existing server response-byte ceiling requires one; it must be derived from
configured provider output budget, not `MAX_QUESTION_LENGTH`.

## Public structured result

The completed conversational result contains:

```json
{
  "completion_status": "complete_with_warnings",
  "answer_source": "structured_synthesis",
  "overview": "model text",
  "results": [
    {
      "probability": "high_probability",
      "classification_status": "model_classified",
      "statement": "model text",
      "reported_range_ids": ["r000001", "r999999"],
      "verified_range_ids": ["r000001"],
      "unverified_range_ids": ["r999999"],
      "citation_status": "partial",
      "uncertainty": null,
      "warnings": ["UNKNOWN_RANGE_ID:r999999"]
    }
  ],
  "unclassified_evidence": [
    {
      "range_id": "r000002",
      "summary": "validated extraction summary",
      "relevance": "validated extraction relevance",
      "reason": "not_referenced_by_synthesis"
    }
  ],
  "unverified_model_statements": [],
  "evidence_ledger": [],
  "evidence_validation": {},
  "synthesis_validation": {
    "status": "warnings",
    "raw_output_preserved": false,
    "warnings": []
  },
  "coverage": {},
  "retrieval_diagnostics": {},
  "ledger_processing": {},
  "usage": {}
}
```

Exact enums:

```text
completion_status:
  complete
  complete_with_warnings
  partial

answer_source:
  structured_synthesis
  raw_synthesis_output
  synthesis_unavailable

probability:
  high_probability
  lower_probability

classification_status:
  model_classified
  unclassified

citation_status:
  verified
  partial
  unverified

synthesis_validation.status:
  conformant
  warnings
  unparseable
  unavailable
```

The server may choose precise class names consistent with repository style,
but these public JSON field names and literals are binding.

Use three strict discriminated public result variants:

- `structured_synthesis`: `overview` is required and `raw_answer` is absent;
- `raw_synthesis_output`: `raw_answer` is the complete provider content and
  `overview` is absent;
- `synthesis_unavailable`: both are absent.

Do not duplicate the complete raw output in both `overview` and another field.
The common result sections and ledger remain available in all variants.

## Public result assembly

### Structured synthesis

- `overview` is exact model text.
- result statements and reported IDs are exact model values.
- verified/unverified IDs are server-derived.
- high/lower grouping is deterministic.
- omitted canonical ranges appear in `unclassified_evidence`.

### Raw synthesis

- `raw_answer` is complete raw provider content.
- `answer_source=raw_synthesis_output`.
- `synthesis_validation.status=unparseable`.
- deterministically recoverable result items may be included.
- complete raw content is returned exactly once, not silently truncated.

### Synthesis unavailable

- `overview` is absent, not an empty default.
- `answer_source=synthesis_unavailable`.
- canonical ledger and unclassified evidence remain.
- terminal status is `partial`.

## Evidence ledger

The canonical ledger remains server-built from verified extraction ranges. It
contains source identity, boundaries, extraction summary/relevance,
normalizations, and uncertainties.

Remove synthesis dispositions and rationales from canonical ledger records.
Probability belongs to synthesis results, not evidence identity.

Extraction `summary` and `relevance` are nullable in the canonical ledger when
the model omitted or malformed them but supplied unambiguous real endpoints.
Absence is reported explicitly; empty/default text is never manufactured.

## Evidence validation summary

Expand the existing summary to include:

- planned window count;
- usable window count;
- unavailable window count and content-free reason codes;
- accepted range count;
- rejected range count and existing granular diagnostics;
- normalized range count;
- status `complete|partial`.

Evidence status is partial when any planned window is unavailable or any
candidate range is rejected.

## Warning codes

Use stable structured codes:

- `UNKNOWN_RANGE_ID`
- `UNKNOWN_MESSAGE_ID`
- `RANGE_ENDPOINTS_REVERSED`
- `THREAD_ID_CORRECTED`
- `CROSS_THREAD_RANGE`
- `AMBIGUOUS_RANGE`
- `DUPLICATE_CITATION`
- `CITATION_PARTIALLY_VERIFIED`
- `CITATION_UNVERIFIED`
- `UNKNOWN_PROBABILITY`
- `SYNTHESIS_OUTPUT_NONCONFORMANT`
- `SYNTHESIS_RESULT_UNCLASSIFIED`
- `SYNTHESIS_OMITTED_LEDGER_RANGE`
- `WINDOW_OUTPUT_UNUSABLE`
- `WINDOW_UNAVAILABLE`
- `COMPACTION_UNAVAILABLE`
- `SYNTHESIS_UNAVAILABLE`

Warnings carry a machine code and bounded content-free details. They do not
copy message text into normal logs.

## Stream changes

Add or rename events so the sequence distinguishes provider output from result
inspection:

```text
ledger_synthesis_started
ledger_synthesis_received
synthesis_validation_completed
retrieval_overlap_completed
completed
```

`ledger_synthesis_received` is emitted once provider content arrives, before
schema/result inspection. Its data includes usage and whether content is
nonblank, never content.

`synthesis_validation_completed` includes conformant/warning/unparseable/
unavailable status and counts.

Add window events for:

- `window_output_unusable`
- `window_unavailable`

Existing retry events remain the source of attempt/backoff progress.

Every event passes the strict server and client stream parser. Sequence remains
monotonic.

## Error mapping

Delete `LEDGER_BIJECTION_FAILED`.

Use hard errors only for hard failures, with specific codes such as:

- `LEDGER_INTERNAL_INTEGRITY_FAILED`
- `NO_USABLE_WINDOW_OUTPUT`
- `NO_USABLE_RESULT`

Model-output nonconformance that still contains readable content is a warning,
not an HTTP/stream error.

## Configuration migration

This packet does not require a control-schema version bump because operation
names and setting shapes remain unchanged. It does require replacing the
incompatible default `ledger_synthesis` prompt.

For every existing stored config version:

- preserve model profile, provider, API-key reference, reasoning,
  temperature, token budgets, timeouts, retry settings, and pricing;
- replace the synthesis prompt only when its body equals a known obsolete
  default or contains the obsolete required literals;
- never overwrite a genuinely operator-custom prompt silently;
- validation must reject activation of prompts containing active obsolete
  response-contract requirements and explain that the prompt must be updated;
- bootstrap/current defaults use the new prompt.

If the current config-store architecture requires a schema bump to make prompt
migration atomic and auditable, use v5. Do not bump merely for appearance. The
executor must record the decision and prove migration/rollback behavior.

## Compatibility policy

There is no runtime backward compatibility for old synthesis output or old
public result shapes. Update server, Python test equipment, scripts, and tests
atomically in this packet. Flutter is untouched.
