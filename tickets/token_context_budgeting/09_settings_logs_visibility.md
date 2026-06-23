# Ticket 09: Improve Settings And Log Visibility

## Goal

Make context-budget decisions visible in Settings and process logs so users can understand why the app chose whole transcript or exhaustive scan.

## Files

Update:

```text
message_evidence_workstation/ui/settings_tab.py
message_evidence_workstation/search/conversational_answer.py
tests/test_ui_smoke.py
tests/test_conversational_answer.py
```

## Implementation

Add process log events:

```text
answer_budget_resolved
whole_transcript_selected
exhaustive_window_scan_selected
window_plan_built
```

Include details:

```json
{
  "model_id": "...",
  "context_window_tokens": 128000,
  "context_source": "registry",
  "transcript_tokens": 52300,
  "usable_input_tokens": 84100,
  "decision": "whole_transcript",
  "window_count": 0,
  "target_tokens": 12000,
  "overlap_messages": 2
}
```

Settings readout should show:

```text
Selected answer model
Context window
Context source
Usable input budget
Reserved output
Prompt overhead
Transcript token estimate
Auto decision
```

If context source is default, say it is a safe default and user can override.

## Acceptance Criteria

- Readout updates when answer settings change.
- Readout updates when dataset changes or no dataset loaded.
- Logs make routing decisions explainable.
- UI smoke tests pass.

## Suggested Tests

```text
test_settings_context_budget_readout_present
test_answer_budget_log_written
test_window_plan_log_written
```

## Focused Test Command

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_smoke.py tests\test_conversational_answer.py --basetemp .pytest_tmp
```
