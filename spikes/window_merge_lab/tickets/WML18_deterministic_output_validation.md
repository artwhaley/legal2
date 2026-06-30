# WML18 - Deterministic Output Validation

## Goal

Add deterministic validation so the app can reject structurally invalid ledger-synthesis outputs before treating them as accepted results.

## Depends On

- WML17

## Scope

Add a spike-local validator, for example:

```text
spikes/window_merge_lab/validator.py
```

Suggested interface:

```python
validate_synthesis_output(
    parsed_response: dict,
    ledger_records: list[EvidenceLedgerRecord],
    mode: Literal["full", "compact"],
) -> ValidationResult
```

Suggested result types:

```python
@dataclass
class ValidationIssue:
    severity: Literal["error", "warning"]
    code: str
    message: str
    range_id: str | None = None

@dataclass
class ValidationResult:
    ok: bool
    issues: list[ValidationIssue]
    input_range_count: int
    output_range_count: int
    represented_range_count: int
    missing_range_ids: list[str]
    duplicate_range_ids: list[str]
    unknown_range_ids: list[str]
    invalid_message_ids: list[str]
```

Required hard errors:

- missing `answer_ranges` (null, undefined, or empty)
- output entry missing `range_id`
- output entry missing `source_range_key`
- unknown `range_id` (not present in the input ledger)
- missing input `range_id` (not represented in output)
- duplicate input `range_id` representation (same `range_id` appears > 1 in output)
- changed `hit_message_id` (differs from input ledger record for that `range_id`)
- changed `start_message_id` (differs from input ledger record for that `range_id`)
- changed `end_message_id` (differs from input ledger record for that `range_id`)
- invalid message IDs outside the ledger allowlist
- `answer_format` does not match the selected profile (`"detailed"` for full,
  `"brief"` for compact) — if the plan said full but the model returned `"brief"`,
  reject as a hard error

### Message ID Comparison Rules

Before comparing message IDs between input ledger and output, normalize both sides:

- strip leading/trailing whitespace
- do not normalize case or format — the IDs must match exactly after trimming
- reject as "changed" if they differ after normalization

Rationale: message IDs are opaque keys. Whitespace trimming is safe. Any semantic
transformation by the model is an error.

### Ledger Allowlist Definition

The "ledger allowlist" for message ID validation is the set of ALL message ID
values that appear in the input ledger records across `hit_message_id`,
`start_message_id`, and `end_message_id`. IDs from the original source windows
that are NOT in the ledger are NOT in the allowlist — the model must not introduce
message IDs that weren't in its input.

This means if a ledger record has `hit_message_id="msg_002"`, `start_message_id="msg_001"`,
`end_message_id="msg_003"`, the allowlist contains `{"msg_001", "msg_002", "msg_003"}`.
If the model outputs `hit_message_id="msg_999"`, that is rejected as an unknown ID.

### Bijection Enforcement (v1)

For v1, enforce one input ledger row → one output answer_range:

- `input_range_count == output_range_count == represented_range_count`
- Every input `range_id` appears exactly once in output
- No output `range_id` is unknown
- No output `range_id` appears more than once

If any of these fail, the output is structurally invalid and should be flagged
with hard errors. Do not silently repair the output.

Required warnings:

- empty title (empty string or whitespace only)
- metadata-only title (heuristic: matches pattern matching date-only or
  generic labels — e.g. `/^(Conversation|Discussion|School)\s+on\s+/i` or
  similar. Document the heuristic in code as a constant.)
- missing `answer_summary` (empty or absent)
- missing `answer` (empty or absent)
- empty summary/display text in full mode

## Integration

- Strategy result should carry validation status
- Invalid outputs should still be saved for inspection
- Evaluator should show validation failures clearly
- GUI should expose validation status

## Guardrails

- Do not silently repair missing or unknown range IDs
- Do not silently repair changed message IDs
- Only allow small deterministic normalization during migration, like scalar/list coercion for `source_range_key(s)` when unambiguous

## Acceptance Criteria

- Validator rejects non-bijective outputs
- Validator rejects invented or changed IDs
- Validator allows compact outputs when they are structurally valid
- Tests cover missing, duplicate, unknown, and changed range cases

