# TKT-03 — Ledger Validator

## Goal

Create `search/ledger_validator.py` with two validation functions: one for raw model
output (narrative/themes) and one for the assembled payload (deterministic range
bijection). These catch code bugs and surprising model behavior before the result
reaches the user.

---

## Depends On

- TKT-01 (uses `EvidenceLedgerEntry` or the dict form via `ledger_to_dicts`)

---

## Context

The spike validator at `spikes/window_merge_lab/validator.py` contains a comprehensive
`validate_synthesis_output` function. Port only the validation needed for production:

- **Raw model validation**: The model returns `answer_summary`, `answer`, `themes`,
  `notable_patterns`, `contradictions_or_tensions`, `uncertainties`. The model never
  returns `answer_ranges`. Validate that model-owned fields are structurally sound.
- **Assembled payload validation**: After `assemble_ledger_result` injects deterministic
  `answer_ranges`, validate bijection — every input `range_id` appears exactly once,
  no unknown `range_id`s, no duplicated `range_id`s, message IDs match ledger.

---

## Deliverables

### Dataclasses

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

### Functions

#### `validate_ledger_analysis_output(model_json: Any, ledger_records: list[dict]) -> ValidationResult`

Validates the raw model response. Does NOT inspect or require `answer_ranges`.

Checks:
- `model_json` is a `dict`.
- `"answer"` is present, non-empty string.
- `"answer_summary"` is present (may be empty string, which becomes a warning).
- `"themes"` — if present, must be a list.
- Every entry in `"themes"` — if `"range_ids"` is present, it must be a list.
- Every `range_id` in `themes[].range_ids[]` must exist in `ledger_records`
  (looked up by `range_id` key). Unknown references are errors.
- `"notable_patterns"` — if present, must be a list.
- `"contradictions_or_tensions"` — if present, must be a list.
- `"uncertainties"` — if present, must be a list.

Warnings (non-blocking):
- `"answer_summary"` is empty or missing (model should usually provide one).
- `"answer"` seems unusually short (e.g. fewer than 20 chars).
- `"themes"` is missing or empty (legitimate for compact mode, but warn).

Errors are blocking. Warnings are informational.

#### `validate_assembled_ledger_output(assembled_payload: dict, ledger_records: list[dict]) -> ValidationResult`

Validates the assembled payload AFTER `assemble_ledger_result` has injected
deterministic `answer_ranges`. This catches code bugs in the assembly function.

Checks:
- `assembled_payload` is a `dict`.
- `"answer_ranges"` is a list.
- Every input ledger `range_id` appears exactly once in output `answer_ranges`.
- No unknown `range_id` in output (i.e. no `range_id` that wasn't in input ledger).
- No duplicated `range_id` in output.
- For every `answer_range`, `hit_message_id`, `start_message_id`, `end_message_id`
  match the corresponding ledger record.
- For every `answer_range`, `source_range_key` matches the ledger record.

Errors for: missing `answer_ranges`, missing ranges, unknown ranges, duplicate ranges,
changed message IDs, changed `source_range_key`.

Warnings for: empty `title`, empty `summary`, empty `display_text` in full mode.

---

## Guard Rails

1. `validate_ledger_analysis_output` must NOT require `answer_ranges`. The model
   output schema explicitly excludes them.
2. `validate_assembled_ledger_output` must NOT call the model or do any I/O.
3. Validation functions are pure — no DB, no logging, no model calls.
4. Errors in `validate_assembled_ledger_output` indicate a CODE BUG in
   `assemble_ledger_result` or `build_evidence_ledger`. These should fail noisily
   in the merge path.
5. Do not port the spike validator's `METADATA_TITLE_RE` or the legacy
   `source_range_keys` (plural) support. Those are not needed for the ledger path.
6. Do not import from `search/conversational_answer.py`. The validator works on
   plain dicts, not `ConversationalAnswerResult`.

---

## Acceptance Criteria

- `validate_ledger_analysis_output({"answer": "x", "answer_summary": "y"}, [])` returns `ok=True`.
- `validate_ledger_analysis_output("not a dict", [])` returns `ok=False`, has
  `not_object` issue.
- `validate_ledger_analysis_output({"answer": ""}, [])` returns `ok=False`, has
  `missing_answer` issue.
- `validate_ledger_analysis_output` with valid ledger and model theme referencing
  a real `range_id` returns `ok=True`.
- `validate_ledger_analysis_output` with theme referencing unknown `range_id`
  returns `ok=False`.
- `validate_assembled_ledger_output` with perfect bijection returns `ok=True`.
- `validate_assembled_ledger_output` with one missing range returns `ok=False`
  with that range in `missing_range_ids`.
- `validate_assembled_ledger_output` with one extra range returns `ok=False`
  with that range in `unknown_range_ids`.
- `validate_assembled_ledger_output` with duplicate range returns `ok=False`
  with that range in `duplicate_range_ids`.
- `validate_assembled_ledger_output` with changed `hit_message_id` returns
  `ok=False` with a `changed_hit_message_id` issue.
