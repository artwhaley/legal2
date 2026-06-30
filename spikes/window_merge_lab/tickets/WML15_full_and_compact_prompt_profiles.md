# WML15 - Full And Compact Prompt Profiles

## Goal

Replace competing prompt shapes with one evidence-ledger strategy and two prompt profiles: `full` and `compact`.

## Depends On

- WML14

## Scope

Add a new prompt builder for:

```text
evidence_ledger_synthesis
```

It should accept:

- ledger records
- optional source-batch context
- selected prompt profile
- user query

Both profiles must use the same ledger input shape.

### Full Profile

Behavior:

- rich answer narrative
- useful per-range summaries
- useful display text
- content-bearing titles
- preserve every range as a distinct output entry

### Compact Profile

Behavior:

- short answer narrative
- short summaries
- short display text
- content-bearing titles
- preserve every range as a distinct output entry

Compact is not a degraded or apologetic mode. It is a normal operating mode.

## Prompt Requirements

Prompt language must say:

- source batches are token-packed artifacts, not meaningful user-facing divisions
- organize by evidence content, chronology, and themes
- do not say "in window 1" or similar
- use `input_title` and `input_summary` as compact evidence context
- prefer titles like `Tummy aches and school attendance`
- avoid metadata-only titles like `Conversation on January 21`
- for v1, do not merge ranges
- every input `range_id` must appear exactly once in output

## Output Schema

Target schema with `range_id` as the primary validation key and `source_range_key`
echoed verbatim from the input ledger for UI/debug traceability:

```json
{
  "answer_summary": "...",
  "answer_format": "detailed|brief",
  "answer": "...",
  "answer_ranges": [
    {
      "range_id": "r000001",
      "source_range_key": "...",
      "title": "...",
      "summary": "...",
      "date_description": "...",
      "display_text": "...",
      "hit_message_id": "...",
      "start_message_id": "...",
      "end_message_id": "..."
    }
  ],
  "uncertainties": [],
  "coverage_summary": {
    "mode": "full|compact",
    "input_range_count": 67,
    "output_range_count": 67,
    "represented_range_count": 67,
    "source_thread_ids": ["..."]
  }
}
```

`range_id` and `source_range_key` both appear in the output:
- **`range_id`**: the stable ID from the input ledger — used by the validator (WML18)
  for bijection checking. The model must echo it unchanged.
- **`source_range_key`**: a human-readable composite — used by the evaluator (WML19)
  for traceability in debug views. The model must echo it unchanged.

## Required Changes Outside This Ticket

### Update `ANSWER_JSON_SCHEMA` in `prompts.py`

Replace the current schema (which has `source_range_keys` plural array) with the
new schema above. This affects all prompt builders that reference it. The schema
is shared by all strategies, so verify legacy strategy prompts still parse
correctly after the change (the old `source_range_keys` field is unused by the
new strategy but may appear in old cached outputs).

### Register the New Strategy

This ticket creates the prompt builder but should also register the strategy in
`STRATEGY_REGISTRY`, `STRATEGY_DESCRIPTIONS`, and `EXPECTED_CALL_COUNTS` in
`strategies.py` so it is available in the GUI and from tests. The run function
can be a minimal placeholder that calls the prompt builder and returns an empty
result if the full implementation is deferred to later tickets.

## Guardrails

- Do not build this on raw IDs-only rows
- Do not present source batches/windows as meaningful sections
- Do not instruct merging in this stack
- Do not remove legacy prompt builders yet; keep them for comparison paths
- The old `source_range_keys` field (plural array) is dropped in favor of
  `range_id` + `source_range_key` (singular). No backward compatibility needed
  — this is a spike.

## Acceptance Criteria

- New prompt builder exists for `evidence_ledger_synthesis`
- `full` and `compact` share one ledger input shape
- Prompt wording clearly distinguishes profiles only by richness, not by correctness
- Titles are instructed to convey substance, not just metadata
- `ANSWER_JSON_SCHEMA` updated to the new output schema
- New strategy registered in `STRATEGY_REGISTRY`, `STRATEGY_DESCRIPTIONS`, `EXPECTED_CALL_COUNTS`
- Tests assert the presence of range-id and anti-window-language guidance

