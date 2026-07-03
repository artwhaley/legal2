# TKT-04 — New Merge Function + Call Site Swap

## Goal

Add `_run_evidence_ledger_window_merge` to `search/conversational_answer.py` and
conditionally call it from `run_exhaustive_window_scan_answer` behind a feature flag.

---

## Depends On

- TKT-01 (evidence ledger module functions)
- TKT-02 (run type wiring so `run_nim_chat` accepts the new run type)
- TKT-03 (validator functions for raw model + assembled payload)

---

## Context

The existing merge function `_run_bounded_exhaustive_window_merge` at line 981 of
`conversational_answer.py` takes this call:

```python
parsed = _run_bounded_exhaustive_window_merge(
    conn, logger, router,
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

The new `_run_evidence_ledger_window_merge` takes the same parameters and returns
the same `ConversationalAnswerResult`. It is a drop-in replacement.

---

## Deliverables

### 1. `config/settings.py` — Feature flag

Add to `AnswerSettings`:

```python
use_evidence_ledger_merge: bool = True
```

This is a production feature flag for rollback. Not a UI project in this phase.

### 2. Imports in `conversational_answer.py`

Add imports:

```python
from message_evidence_workstation.nim.prompts import RUN_TYPE_EVIDENCE_LEDGER_SYNTHESIS
from message_evidence_workstation.search.evidence_ledger import (
    assemble_ledger_result,
    build_evidence_ledger,
    build_evidence_ledger_synthesis_messages,
    batch_context_to_dicts,
    ledger_to_dicts,
    plan_ledger_budget,
)
from message_evidence_workstation.search.ledger_validator import (
    validate_assembled_ledger_output,
    validate_ledger_analysis_output,
)
```

Do not import `task_role_for_run_type` or `user_facing_role_for_task_role` here.
`run_nim_chat` already performs run-type task-role resolution internally.

### 3. `_run_evidence_ledger_window_merge` function

Signature matches the existing `_run_bounded_exhaustive_window_merge` exactly.

#### Logic:

1. **Log**: `evidence_ledger_merge_selected` — flag, window count, source thread count.

2. **Build ledger**:
   ```python
   entries, batch_ctx = build_evidence_ledger(window_results)
   entry_dicts = ledger_to_dicts(entries)
   batch_dicts = batch_context_to_dicts(batch_ctx)
   ```
   Log: `evidence_ledger_built` — entry count, batch count, thread IDs.

3. **Empty ledger early return** (no API call):
   ```python
   if not entry_dicts:
       log: evidence_ledger_empty
       return ConversationalAnswerResult(...)  # deterministic no-results
   ```
   The deterministic answer text must be:
   `"Exhaustive Windowed Search examined the full selected data package and found no results. Please modify your search terms and try again."`

4. **Profile selection**:
   ```python
   provisional = build_evidence_ledger_synthesis_messages(
       user_query, entry_dicts, batch_dicts, config=None,
   )
   config = plan_ledger_budget(
       entry_dicts, provisional,
       model_context_tokens=budget.context_window_tokens,
       max_output_tokens=max_tokens,
   )
   ```
   Log: `evidence_ledger_budget_planned` — mode, format, estimates, fallback.

5. **If `config.overflow` is true** -> log `evidence_ledger_validation_failed`
   with `phase="budget"` and raise `ConversationalAnswerParseError` with clear
   token math from `config.fallback_reason`. Do not make the model call. Do not
   silently split or truncate.

6. **Build final messages**:
   ```python
   messages = build_evidence_ledger_synthesis_messages(
       user_query, entry_dicts, batch_dicts, config,
   )
   ```

7. **Single synthesis call**:
   ```python
   log: evidence_ledger_synthesis_start
   result = run_nim_chat(
       conn, logger, router,
       run_type=RUN_TYPE_EVIDENCE_LEDGER_SYNTHESIS,
       messages=messages,
       dataset_id=dataset_id,
       max_tokens=max_tokens,
   )
   ```

8. **Parse + validate raw model output**:
   ```python
   model_json = _extract_json_object(result.content)
   validation = validate_ledger_analysis_output(model_json, entry_dicts)
   if not validation.ok:
       log: evidence_ledger_validation_failed (phase=raw, issues=...)
       raise ConversationalAnswerParseError(...)
   ```

9. **Assemble deterministic result**:
   ```python
   assembled = assemble_ledger_result(model_json, entry_dicts, config)
   ```

10. **Validate assembled payload**:
    ```python
    assembly_validation = validate_assembled_ledger_output(assembled, entry_dicts)
    if not assembly_validation.ok:
        log: evidence_ledger_validation_failed (phase=assembled, issues=...)
        raise ConversationalAnswerParseError(...)
    ```

11. **Pass through existing parser**:
    ```python
    parsed = _parse_answer_payload(
        assembled,
        valid_message_ids=valid_ids,
        message_thread_by_id=message_thread_by_id,
        source_thread_ids=source_thread_ids,
        messages_considered=len(valid_ids),
        mode=ANSWER_MODE_EXHAUSTIVE_WINDOW_SCAN,
        sessions_considered=len(sessions),
        sessions_inspected=len({w.get("session_id") for w in window_results}),
        sessions_skipped=max(0, len(sessions) - len({w.get("session_id") for w in window_results})),
        retrieval_assists=retrieval_assists,
        message_order_by_thread=_message_order_by_thread_from_db(conn, dataset_id),
    )
    ```

12. **Log completion**:
    ```python
    log: evidence_ledger_merge_complete
        — final answer range count
        — cited message count
        — uncertainty count
    ```

13. **Return**:
    ```python
    return parsed
    ```

### 4. Replace the call site in `run_exhaustive_window_scan_answer`

Replace:

```python
parsed = _run_bounded_exhaustive_window_merge(...)
```

With:

```python
if settings.use_evidence_ledger_merge:
    parsed = _run_evidence_ledger_window_merge(...)
else:
    parsed = _run_bounded_exhaustive_window_merge(...)
```

### 5. `_message_order_by_thread_from_db`

This helper already exists in `conversational_answer.py`. No changes needed.

---

## Guard Rails

1. **Drop-in replacement**: The new function must accept the exact same parameters
   and return the same `ConversationalAnswerResult` type as the old function.
2. **No silent retries**: If validation fails, raise a noisy error. Do not retry
   the model call.
3. **No hidden fallbacks**: Do not fall back to the old merge path if the ledger
   merge fails. The feature flag is the only control.
4. **Empty ledger**: Must return the deterministic no-results `ConversationalAnswerResult`
   without making an API call, using the exact answer text above.
5. **Token overflow**: If `config.overflow` is true because the compact profile
   still exceeds the input or output budget, raise a `ConversationalAnswerParseError`
   with clear token math. Do not split or truncate. Multi-call ledger splitting is
   deferred.
6. **Logging**: Every phase must be logged. Do not hide failures, fallbacks, or
   edge cases.
7. **Do not change** window planning, scan calls, retrieval assists, or the final
   post-merge annotations (`coverage_summary.windows_inspected`, `token_budget`,
   `uncertainties` concatenation) — those stay in `run_exhaustive_window_scan_answer`
   as-is.

---

## Acceptance Criteria

- `_run_evidence_ledger_window_merge` exists with the same signature as
  `_run_bounded_exhaustive_window_merge`.
- When `use_evidence_ledger_merge=True`, `run_exhaustive_window_scan_answer` calls
  the new function.
- When `use_evidence_ledger_merge=False`, `run_exhaustive_window_scan_answer` calls
  the old function.
- Empty ledger (all window_results have empty answer_ranges) returns deterministic
  no-results without a model call.
- Token overflow (even compact profile exceeds budget) raises
  `ConversationalAnswerParseError`.
- Valid model response with full profile produces a `ConversationalAnswerResult`
  with correct `answer_ranges`, `answer_summary`, `answer`, `uncertainties`,
  `coverage_summary`.
- All existing log operations for the new path are emitted.
