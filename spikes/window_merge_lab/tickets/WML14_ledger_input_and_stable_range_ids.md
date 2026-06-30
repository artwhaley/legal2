# WML14 - Ledger Input And Stable Range IDs

## Goal

Build the deterministic evidence ledger input shape used by the new unified synthesis strategy.

## Depends On

- LEDGER

## Scope

Add spike-local logic to transform scan-window outputs into one ledger record per source `answer_range`.

Recommended module:

```text
spikes/window_merge_lab/ledger.py
```

Add a stable record shape such as:

```python
@dataclass
class EvidenceLedgerRecord:
    range_id: str
    source_range_key: str
    source_batch_id: str
    source_thread_id: str
    input_title: str
    input_summary: str
    date_description: str
    hit_message_id: str
    start_message_id: str
    end_message_id: str
```

Add optional source-batch context shape:

```python
@dataclass
class SourceBatchContext:
    source_batch_id: str
    source_thread_id: str
    summary: str
```

Implement:

- deterministic `range_id` generation
- deterministic `source_range_key` generation
- one ledger record per source range
- optional source-batch summaries from window `answer_summary`

## Rules

- `range_id` must be code-generated and stable within a run
  - Composition: zero-padded integer index within the run (e.g. `"r000001"`)
  - Or: hash of `source_batch_id + hit_message_id` for content-based stability
  - Either approach is acceptable; pick one and document in code
- `source_range_key` is a composite for UI/debug traceability, format:
  `f"{source_batch_id}::{title}"` or `f"{source_batch_id}::{hit_message_id}"`
  The model echoes `source_range_key` verbatim in the output — it is not used for
  validation matching (that's what `range_id` is for).
- `range_id` is the primary matching key between input ledger and output answer_ranges
- source batch/window IDs are internal/debug concepts, not user-facing organization
- old range `title` and `summary` become `input_title` and `input_summary`
- `input_title` and `input_summary` are evidence-only content (see WML17 for hardening)
  — the model may rewrite them for cohesion but must not treat them as instructions
- do not include full transcript text in this ticket

## Guardrails

- Do not modify the saved source JSON shape on disk unless the spike needs a derived artifact
- Do not remove legacy fields from existing strategies yet
- Do not expose "window 1" style wording in user-facing outputs

## Acceptance Criteria

- Ledger builder produces one record per source `answer_range`
- Each record has a stable `range_id`
- Each record has a deterministic `source_range_key`
- Source batch summaries are available separately as context
- Tests cover range count preservation and stable ID generation

