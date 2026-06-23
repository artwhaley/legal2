# Ticket 04: Extend Answer Settings And UI Readout

## Goal

Expose token-budget settings and show a live explanation of the app's whole-transcript vs exhaustive-scan decision.

## Files

Update:

```text
message_evidence_workstation/config/settings.py
message_evidence_workstation/ui/settings_tab.py
tests/test_ui_smoke.py
```

Inspect:

```text
message_evidence_workstation/search/conversational_answer.py
message_evidence_workstation/search/transcript.py
```

## Implementation

Add to `AnswerSettings`:

```python
context_window_override_tokens: int = 0
context_safety_ratio: float = 0.70
reserved_output_tokens: int = 4096
prompt_overhead_tokens: int = 1500
window_target_tokens: int = 12000
window_overlap_messages: int = 2
```

Keep `whole_transcript_max_chars` for backward compatibility, but it should no longer be primary after Ticket 05.

Settings UI controls:

- Context window override tokens.
- Context safety ratio.
- Reserved output tokens.
- Prompt overhead tokens.
- Exhaustive window target tokens.
- Exhaustive window overlap messages.

Add a readout label for:

```text
Selected answer model
Context window tokens
Context source
Usable input budget
Reserved output tokens
Prompt overhead tokens
Transcript token estimate if dataset loaded
Auto mode decision
```

It is OK if the readout initially uses a helper from Ticket 05 once implemented. If needed, add a temporary placeholder and complete it in Ticket 05.

## Acceptance Criteria

- Settings load old settings files without errors.
- New settings persist.
- UI smoke tests pass.
- Readout works when no dataset is loaded.
- Readout works when a dataset is loaded.

## Suggested Tests

```text
test_settings_loads_answer_token_defaults
test_settings_persists_answer_token_fields
test_main_window_settings_has_context_budget_controls
```

## Focused Test Command

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_smoke.py --basetemp .pytest_tmp
```
