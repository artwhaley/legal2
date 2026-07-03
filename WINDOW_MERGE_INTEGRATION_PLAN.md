# Plan: Drop-In Evidence-Ledger Merge for Exhaustive Window Scan

## Goal

Replace only the merge step at the back half of `run_exhaustive_window_scan_answer`
(`search/conversational_answer.py`) with evidence-ledger synthesis.

This is a drop-in replacement for the existing production merge behavior. The
window planner, per-window scan calls, retrieval assists, routing system, model
client, and final `ConversationalAnswerResult` contract stay the same.

**Current flow:**

`plan windows -> N window scan calls -> window_results -> _run_bounded_exhaustive_window_merge(...) -> ConversationalAnswerResult`

**New flow:**

`plan windows -> N window scan calls -> window_results -> _run_evidence_ledger_window_merge(...) -> ConversationalAnswerResult`

The new merge does one synthesis model call over a deterministic evidence ledger.
The model provides narrative analysis only. It does not create, remove, merge, or
rewrite `answer_ranges`. The app injects `answer_ranges` deterministically from
the already-parsed window scan results.

---

## Scope / Constraints

- Do not change `ui/embedding_worker.py`, embedding preload,
  `DatasetLoadResult` embedding semantics, or `embeddings/index_jobs.py`.
- Do not change `ModelRouter`, `NimClient`, `search/fusion.py`,
  `search/window_planner.py`, or `search/session_map.py`.
- Do not refactor the exhaustive window scan caller.
- Do not change non-window mode (`whole_transcript`).
- Keep old `_run_bounded_exhaustive_window_merge` behind a feature flag for
  rollback.
- Do not add hidden fallbacks, silent retries, or speculative alternate merge
  paths.

---

## Production Contract

The new code must fit the same production boundary as the current merge step:

```python
parsed = _run_evidence_ledger_window_merge(
    conn,
    logger,
    router,
    user_query=user_query,
    sessions=sessions,
    window_results=window_results,
    retrieval_assists=retrieval_assists,
    token_budget=token_budget,
    budget=budget,
    dataset_id=dataset_id,
    max_tokens=merge_max_tokens,
    model_id=selected_model,
    valid_ids=valid_ids,
    message_thread_by_id=message_thread_by_id,
    source_thread_ids=source_thread_ids,
)
```

After this call returns, the existing caller may continue to set:

```python
parsed.coverage_summary.windows_inspected = len(planned_windows)
parsed.coverage_summary.token_budget = token_budget
parsed.uncertainties = scan_uncertainties + parsed.uncertainties
return parsed
```

The new merge function must return a normal `ConversationalAnswerResult`.

---

## Step 1 - New file: `search/evidence_ledger.py`

Port the evidence-ledger parts from `spikes/window_merge_lab/`, but shape them
for production window merge inputs.

### Dataclasses

- `EvidenceLedgerEntry`
  - `range_id`
  - `source_range_key`
  - `source_batch_id`
  - `source_thread_id`
  - `input_title`
  - `input_summary`
  - `input_display_text`
  - `date_description`
  - `hit_message_id`
  - `start_message_id`
  - `end_message_id`

- `SourceBatchContext`
  - `source_batch_id`
  - `source_thread_id`
  - `summary`

- `LedgerConfig`
  - `mode: Literal["full", "compact"]`
  - `answer_format: Literal["detailed", "brief"]`
  - `max_answer_chars`
  - `max_range_summary_chars`
  - `estimated_input_tokens`
  - `estimated_output_tokens`
  - `fallback_reason`

### Functions

- `build_evidence_ledger(window_results) -> tuple[list[EvidenceLedgerEntry], list[SourceBatchContext]]`
  - Flatten already-parsed per-window `answer_ranges`.
  - Assign sequential `range_id`s: `r000001`, `r000002`, etc.
  - Assign stable `source_range_key`: `{window_id}::{range_id}::{hit_message_id}`.
  - Preserve every source range. Do not deduplicate, merge, cap, or drop ranges.

- `ledger_to_dicts(entries) -> list[dict]`

- `batch_context_to_dicts(contexts) -> list[dict]`

- `build_evidence_ledger_synthesis_messages(user_query, ledger_dicts, batch_dicts, config) -> list[dict[str, str]]`
  - Return explicit chat messages:
    `[{ "role": "system", "content": ... }, { "role": "user", "content": ... }]`.
  - Do not return a separate `system_content` argument. `run_nim_chat` does not
    support that parameter.
  - Use `LEDGER_ANALYSIS_JSON_SCHEMA`.
  - The schema must not include `answer_ranges`.
  - Include anti-window language:
    "source windows are token-packed implementation artifacts; organize by
    evidence, not by window number."
  - Include injection hardening from `LEGAL_EVIDENCE_POLICY`.
  - Explicitly instruct: "Do not reconstruct answer_ranges."

- `plan_ledger_budget(ledger_dicts, provisional_messages, model_context_tokens, max_output_tokens) -> LedgerConfig`
  - Keep the provisional-build flow from the spike for now.
  - Build full-profile messages first, estimate their serialized token count,
    and use that estimate to choose `full` or `compact`.
  - This planner is not the final budget architecture. It is only a profile
    selector for the first production proof.
  - Do not truncate, drop, cap, or suppress ledger records.
  - If the payload is too large even for compact, do not invent a fallback in
    this phase. Log the condition clearly and raise a noisy error. Splitting the
    ledger into multiple calls is deferred.

- `assemble_ledger_result(model_json, ledger_dicts, config) -> dict`
  - Accept model-owned fields:
    - `answer_summary`
    - `answer`
    - `themes`
    - `notable_patterns`
    - `contradictions_or_tensions`
    - `uncertainties`
  - Inject `answer_format` from `config.answer_format`.
  - Inject `answer_ranges` deterministically from `ledger_dicts`.
  - Build `cited_message_ids` from all injected `hit_message_id` values.
  - Build a ledger-level `coverage_summary` with:
    - `mode`
    - `input_range_count`
    - `output_range_count`
    - `represented_range_count`
    - `source_thread_ids`
  - Do not ask the model to provide `answer_ranges`.

---

## Step 2 - New run type wiring

Add `RUN_TYPE_EVIDENCE_LEDGER_SYNTHESIS = "evidence_ledger_synthesis"`.

This run type must be wired everywhere `run_nim_chat` requires:

- `nim/prompts.py`
  - Add the constant.
  - Add it to `ALL_RUN_TYPES`.
  - Add a default prompt body to `DEFAULT_PROMPT_BODIES`.
  - The default body may be a short placeholder because this call will pass
    explicit `messages`, but it must exist so prompt seeding, audit records, and
    prompt-version metadata remain consistent.

- `llm/task_roles.py`
  - Import the new run type.
  - Map it to `ModelTaskRole.WINDOWED_RESULT_MERGE`.
  - Add an `LlmCallSite` entry for `_run_evidence_ledger_window_merge`.

Do not change `ModelRouter`, `NimClient`, or `run_nim_chat`.

Production call shape:

```python
messages = build_evidence_ledger_synthesis_messages(
    user_query,
    entry_dicts,
    batch_dicts,
    config,
)
result = run_nim_chat(
    conn,
    logger,
    router,
    run_type=RUN_TYPE_EVIDENCE_LEDGER_SYNTHESIS,
    messages=messages,
    dataset_id=dataset_id,
    max_tokens=merge_max_tokens,
)
```

---

## Step 3 - Modify `AnswerSettings`

Add:

```python
use_evidence_ledger_merge: bool = True
```

to `AnswerSettings` in `config/settings.py`.

This is a production feature flag for rollback. It is not a UI project in this
phase.

---

## Step 4 - Add `_run_evidence_ledger_window_merge`

Add this function to `search/conversational_answer.py` near the existing merge
function.

Responsibilities:

1. Build the evidence ledger from `window_results`.
2. If the ledger has zero entries, return a deterministic no-results
   `ConversationalAnswerResult` without making an API call.
3. Build provisional full-profile messages and choose full/compact profile.
4. Make exactly one synthesis call via `run_nim_chat(..., messages=messages)`.
5. Parse the model response as a ledger-analysis response.
6. Validate raw model fields that the model is allowed to own.
7. Assemble deterministic `answer_ranges` from the ledger.
8. Validate the assembled ledger bijection.
9. Pass the assembled payload through the existing `_parse_answer_payload` path
   so production ID, thread, and ordering checks remain single-source.
10. Return the resulting `ConversationalAnswerResult`.

### No-results behavior

Before the model call:

```python
if not entry_dicts:
    return ConversationalAnswerResult(
        answer=(
            "Exhaustive Windowed Search examined the full selected data package "
            "and found no results. Please modify your search terms and try again."
        ),
        answer_summary=(
            "Exhaustive Windowed Search examined the full selected data package "
            "and found no results."
        ),
        cited_message_ids=[],
        candidate_evidence_blocks=[],
        uncertainties=[],
        coverage_summary=CoverageSummary(
            mode=ANSWER_MODE_EXHAUSTIVE_WINDOW_SCAN,
            messages_considered=len(valid_ids),
            source_thread_ids=source_thread_ids,
            sessions_considered=len(sessions),
            sessions_inspected=len({window.get("session_id") for window in window_results}),
            sessions_skipped=max(
                0,
                len(sessions) - len({window.get("session_id") for window in window_results}),
            ),
            windows_inspected=len(window_results),
            retrieval_assists=list(retrieval_assists or []),
            token_budget=token_budget,
        ),
        mode=ANSWER_MODE_EXHAUSTIVE_WINDOW_SCAN,
    )
```

No API call should be made for an empty ledger.

### Parsing and validation

Do not use plain `json.loads(result.content)` directly unless the production
response is guaranteed to be a bare JSON object. Prefer the same JSON extraction
style used by existing answer parsers so fenced or provider-wrapped JSON errors
remain consistent.

Raw model response validation checks:

- response is a JSON object
- `answer` is present and non-empty
- `answer_summary` is present or can be derived from `answer`
- `themes`, if present, is a list
- every `themes[].range_ids[]` value exists in the ledger
- `notable_patterns`, `contradictions_or_tensions`, and `uncertainties`, if
  present, are lists

Raw model response validation must not require `answer_ranges`.

Assembled payload validation checks:

- every input ledger `range_id` appears exactly once
- no duplicate output `range_id`
- no unknown output `range_id`
- message IDs in injected ranges match the ledger

After assembly and assembled-payload validation, call the existing
`_parse_answer_payload(...)` with:

- `valid_message_ids=valid_ids`
- `message_thread_by_id=message_thread_by_id`
- `source_thread_ids=source_thread_ids`
- `messages_considered=len(valid_ids)`
- `mode=ANSWER_MODE_EXHAUSTIVE_WINDOW_SCAN`
- `sessions_considered=len(sessions)`
- `sessions_inspected=...`
- `sessions_skipped=...`
- `retrieval_assists=retrieval_assists`
- `message_order_by_thread=_message_order_by_thread_from_db(conn, dataset_id)`

This avoids creating a second production parser for answer ranges.

---

## Step 5 - Replace the merge call only

In `run_exhaustive_window_scan_answer`, keep everything before and during the
window scan loop unchanged.

Replace only:

```python
parsed = _run_bounded_exhaustive_window_merge(...)
```

with:

```python
if settings.use_evidence_ledger_merge:
    parsed = _run_evidence_ledger_window_merge(...)
else:
    parsed = _run_bounded_exhaustive_window_merge(...)
```

Do not change window planning, scan calls, retrieval assists, or the final
post-merge annotations:

```python
parsed.coverage_summary.windows_inspected = len(planned_windows)
parsed.coverage_summary.token_budget = token_budget
parsed.uncertainties = scan_uncertainties + parsed.uncertainties
return parsed
```

---

## Step 6 - New file: `search/ledger_validator.py`

Port only the validation needed for this production merge.

Functions:

- `validate_ledger_analysis_output(model_json, ledger_records) -> ValidationResult`
  - Validates raw model-owned fields.
  - Validates theme `range_id` references.
  - Does not require or inspect `answer_ranges`.

- `validate_assembled_ledger_output(assembled_payload, ledger_records) -> ValidationResult`
  - Validates deterministic range bijection.
  - Validates no changed message IDs.
  - This catches code bugs in ledger assembly, not model range errors.

Warnings are acceptable for optional narrative fields, but errors must fail
noisily in the merge path.

---

## Step 7 - Logging

Add clear production logs for the new merge path:

- `evidence_ledger_merge_selected`
  - feature flag value
  - window count
  - source thread count

- `evidence_ledger_built`
  - ledger entry count
  - batch context count
  - source thread IDs

- `evidence_ledger_empty`
  - zero-entry deterministic return
  - no model call made

- `evidence_ledger_budget_planned`
  - mode
  - answer format
  - estimated input tokens
  - estimated output tokens
  - fallback reason, if any

- `evidence_ledger_synthesis_start`
  - run type
  - max tokens
  - ledger entry count

- `evidence_ledger_validation_failed`
  - validation phase: raw model or assembled payload
  - issue summary

- `evidence_ledger_merge_complete`
  - final answer range count
  - cited message count
  - uncertainty count

Do not hide compact fallback or validation failures.

---

## Step 8 - Tests

Create `tests/test_evidence_ledger.py`.

Required tests:

| Test | Verifies |
|---|---|
| `test_build_ledger_from_production_window_results` | Production-shaped `window_results` flatten into ledger entries. |
| `test_ledger_range_ids_sequential` | Multiple windows and ranges produce stable sequential IDs. |
| `test_ledger_source_range_key_stable` | Same input produces identical source keys. |
| `test_ledger_preserves_every_range` | No valid input ranges are dropped or deduplicated. |
| `test_ledger_batch_context` | Batch context uses window IDs and scan `answer_summary`. |
| `test_profile_full_when_fits` | Large budget chooses full profile. |
| `test_profile_compact_when_over_budget` | Smaller budget chooses compact profile. |
| `test_prompt_no_answer_ranges_schema` | Ledger synthesis schema excludes `answer_ranges`. |
| `test_prompt_no_reconstruct_ranges_instruction` | Prompt says not to reconstruct `answer_ranges`. |
| `test_prompt_injection_hardening` | Evidence policy includes injection hardening. |
| `test_raw_validation_rejects_unknown_theme_range_id` | Raw model validator rejects invented range IDs in themes. |
| `test_raw_validation_does_not_require_answer_ranges` | Raw model validator matches the real model contract. |
| `test_assembled_result_has_deterministic_ranges` | Assembled ranges exactly match ledger input. |
| `test_assembled_validation_rejects_missing_duplicate_or_unknown_range` | Bijection failures are noisy. |
| `test_no_ranges_returns_deterministic_no_results_without_model_call` | Empty ledger does not call API. |
| `test_assembled_payload_reuses_parse_answer_payload_validation` | Invalid message/thread/range ordering is caught by existing parser path. |
| `test_legacy_flag_still_works` | `use_evidence_ledger_merge=False` uses old merge path. |

Extend `tests/test_conversational_answer.py`:

- Update the existing exhaustive-window test so the final call expects
  `RUN_TYPE_EVIDENCE_LEDGER_SYNTHESIS` when the flag is enabled.
- Add or parameterize a variant with `use_evidence_ledger_merge=False` to prove
  the old merge path remains callable.

---

## Step 9 - Verification

Run:

```bash
pytest tests/test_evidence_ledger.py -v
pytest tests/test_conversational_answer.py -v
pytest
```

Also grep for accidental direct merge refactors:

```bash
rg "_run_bounded_exhaustive_window_merge|_run_evidence_ledger_window_merge|RUN_TYPE_EVIDENCE_LEDGER_SYNTHESIS" message_evidence_workstation tests
```

---

## Deferred Work

These are intentionally not part of this change:

- Up-front exhaustive-scan sanity check using embedding search to estimate
  expected result count.
- Multi-call ledger splitting when a reasonable output window cannot hold the
  ledger analysis.
- Back-to-back "oh shit" partial ledger answers.
- UI controls for the feature flag.
- Broader budget architecture changes.

For this phase, prove the replacement works for a reasonable-sized dataset with
a single ledger synthesis call, deterministic range preservation, existing parser
validation, and clear logs.

---

## What Stays the Same

| Component | Status |
|---|---|
| `search/window_planner.py` | Unchanged |
| `search/fusion.py` | Unchanged |
| `search/session_map.py` | Unchanged |
| `search/result_models.py` | Unchanged |
| `ui/embedding_worker.py` | Unchanged |
| `embeddings/index_jobs.py` | Unchanged |
| `ModelRouter` / `NimClient` | Unchanged |
| `whole_transcript` mode | Unchanged |
| `_run_bounded_exhaustive_window_merge` | Kept behind `use_evidence_ledger_merge=False` |

---

## Key Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Replacement boundary | Replace only the merge function | Keeps exhaustive scan orchestration stable and inspectable. |
| `answer_ranges` owner | Code, not model | Prevents model-created navigation artifacts. |
| Model job | Narrative/theme synthesis only | The model explains evidence; it does not alter evidence ranges. |
| Run path | `run_nim_chat` with new run type and explicit `messages` | Preserves routing, audit logs, prompt metadata, and error handling. |
| Parser | Reuse `_parse_answer_payload` after assembly | Avoids duplicate validation logic. |
| Empty ledger | Deterministic no-results answer, no API call | Cheaper, clearer, and fully observable. |
| Budget overflow | Noisy failure for now | Multi-call splitting is deferred and should not be hidden. |
| Feature flag | `AnswerSettings.use_evidence_ledger_merge: bool = True` | Allows rollback without preserving two active behaviors by default. |
