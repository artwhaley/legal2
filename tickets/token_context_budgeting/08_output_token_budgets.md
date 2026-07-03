# Ticket 08: Pass Output Token Budgets To NIM Calls

## Goal

Use configured reserved output token budgets when calling NIM so JSON answers are less likely to truncate.

## Files

Update:

```text
message_evidence_workstation/search/conversational_answer.py
message_evidence_workstation/nim/model_runs.py
tests/test_prompts_model_runs.py
tests/test_conversational_answer.py
```

## Implementation

For conversational answer paths, pass `max_tokens` into `run_nim_chat`.

Applicable paths:

- `run_whole_transcript_answer`
- `run_exhaustive_window_scan_answer`
- Session classification / audit / summary only if appropriate and safe.

Use:

```python
max_tokens=answer_settings.reserved_output_tokens
```

For merge calls, use at least the reserved output budget:

```python
merge_max_tokens = max(answer_settings.reserved_output_tokens, 4096)
```

If current functions do not receive `answer_settings`, add explicit optional budget parameters rather than importing settings everywhere.

## Acceptance Criteria

- ModelRun `raw_request_json.max_tokens` reflects configured value.
- Existing default remains `4096`.
- Truncation risk is lower.
- Tests inspect recorded request payloads.

## Suggested Tests

```text
test_whole_transcript_answer_passes_reserved_output_tokens
test_exhaustive_scan_passes_reserved_output_tokens
test_merge_uses_at_least_reserved_output_tokens
```

## Focused Test Command

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_conversational_answer.py tests\test_prompts_model_runs.py --basetemp .pytest_tmp
```
