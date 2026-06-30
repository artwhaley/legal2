# WML19 - Evaluator GUI And Legacy Strategy Positioning

## Goal

Surface profile/validation results in the lab and reposition one-shot/table strategies as legacy comparison controls rather than production recommendations.

## Depends On

- WML18

## Scope

Update:

- strategy execution output metadata
- evaluator views
- GUI result/status areas
- spike docs where needed
- `strategy.py` module docstring and descriptions (see "Positioning" below)

Show:

- selected profile: `full` or `compact`
- serialized prompt token estimate
- expected output token estimate
- validation status (pass/fail + issue count)
- validation issue summary (error count + warning count)
- metadata-only title count (from validator warnings)
- bijection status: input `range_id` count == output `range_id` count

Positioning changes:

- `evidence_ledger_synthesis` becomes the recommended strategy
- `one_shot_compact` remains available as a legacy comparison/control
- `evidence_table_then_synthesis` remains available as a legacy comparison/control
- Add `evidence_ledger_synthesis` to `STRATEGY_DESCRIPTIONS` with description
  like `"Single LLM call over one evidence ledger, full or compact profile"`
- Set `EXPECTED_CALL_COUNTS["evidence_ledger_synthesis"] = 1`

Do not remove the legacy strategies from the lab in this ticket unless that
becomes necessary for simplicity; just stop treating them as the path forward.

## UI Rules

- Do not present user-facing results organized by source window number.
  The debug-level compact input data tab (`_on_build_prompt` line 511) presently
  shows `"Window {i + 1}"` — this is acceptable in debug/payload views since
  source batch IDs are allowed there.
- Presentation of the old strategies should visually distinguish them as legacy
  (e.g., suffix "(legacy)" in the strategy dropdown or status area)

## Evaluator: Provenance Replacement

The current `_build_provenance` tracks merges via `source_range_keys[]`. For the
ledger strategy's 1:1 no-merge constraint, replace provenance with a
`range_id`-based bijection check:

```
Input range_ids: [r000001, r000002, ..., r0000N]
Output range_ids: [r000001, r000002, ..., r0000N]
→ bijection: PASS (all present, no extras, no duplicates)
→ or FAIL with missing/extra/duplicate lists
```

Keep the old `_build_provenance` available for legacy strategy comparisons (the
evaluator can detect which strategy was used from the result metadata and choose
the appropriate provenance method).

## Acceptance Criteria

- Evaluator shows validation results including bijection status
- GUI shows selected profile and validation status
- Recommended strategy in spike docs/result text is `evidence_ledger_synthesis`
- Legacy strategies are visually marked as comparison-only in the GUI
- `STRATEGY_DESCRIPTIONS` and `EXPECTED_CALL_COUNTS` include the new strategy

