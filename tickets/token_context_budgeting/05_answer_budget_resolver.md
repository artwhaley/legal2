# Ticket 05: Add Token-Aware Answer Budget Resolver

## Goal

Change `auto` routing so it uses transcript token estimates and resolved model context window instead of raw character count.

## Files

Update:

```text
message_evidence_workstation/search/conversational_answer.py
message_evidence_workstation/ui/conversational_tab.py
message_evidence_workstation/ui/settings_tab.py
tests/test_conversational_answer.py
```

Use:

```text
message_evidence_workstation/search/token_budget.py
message_evidence_workstation/nim/model_context.py
```

## Implementation

Add:

```python
@dataclass(slots=True)
class AnswerBudget:
    model_id: str
    context_window_tokens: int
    context_source: str
    safety_ratio: float
    reserved_output_tokens: int
    prompt_overhead_tokens: int
    usable_input_tokens: int
    transcript_tokens: int
    transcript_token_method: str
    decision: str
```

Add:

```python
def resolve_answer_budget(
    transcript: SerializedTranscript,
    answer_settings: AnswerSettings,
    model_id: str,
    provider_metadata: dict | None = None,
) -> AnswerBudget:
    ...
```

Budget logic:

```python
usable_input_tokens = floor(context_window_tokens * safety_ratio)
usable_input_tokens -= reserved_output_tokens
usable_input_tokens -= prompt_overhead_tokens
usable_input_tokens = max(1000, usable_input_tokens)
```

Clamp `context_safety_ratio` to `0.25..0.90`.

Auto decision:

```python
if transcript_tokens <= usable_input_tokens:
    whole_transcript
else:
    exhaustive_window_scan
```

Explicit strategies:

- `exhaustive_window_scan` always selects exhaustive scan.
- Legacy `session_coverage` settings now normalize to `whole_transcript`.
- `retrieval_fallback` always selects retrieval fallback.
- `whole_transcript` should select whole transcript if it fits; if it does not fit, log a warning and route to exhaustive scan rather than causing a model overflow.

Update the UI readout from Ticket 04 to use `AnswerBudget`.

## Acceptance Criteria

- `auto` no longer depends on `whole_transcript_max_chars`.
- Tests prove small transcript selects whole transcript.
- Tests prove large token estimate selects exhaustive scan.
- Tests prove explicit strategies still work.
- Logs include budget decision details.

## Suggested Tests

```text
test_resolve_answer_budget_auto_selects_whole_transcript_when_tokens_fit
test_resolve_answer_budget_auto_selects_exhaustive_when_tokens_do_not_fit
test_resolve_answer_mode_explicit_strategies_still_work
test_char_limit_no_longer_controls_auto
```

## Focused Test Command

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_conversational_answer.py tests\test_ui_smoke.py --basetemp .pytest_tmp
```
