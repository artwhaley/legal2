# Ticket 01: Add Token Estimation

## Goal

Add a reusable token estimation module so routing and window planning can use estimated tokens instead of raw character count.

## Files

Create:

```text
message_evidence_workstation/search/token_budget.py
tests/test_token_budget.py
```

Inspect:

```text
message_evidence_workstation/search/transcript.py
message_evidence_workstation/search/conversational_answer.py
pyproject.toml
```

## Implementation

Add:

```python
@dataclass(slots=True)
class TokenEstimate:
    estimated_tokens: int
    method: str  # model_native | tiktoken | heuristic
```

Add functions:

```python
def estimate_tokens(text: str, model_id: str | None = None) -> TokenEstimate:
    ...

def estimate_json_payload_tokens(payload: dict, model_id: str | None = None) -> TokenEstimate:
    ...
```

Fallback order:

1. Placeholder for model-native tokenizer if added later.
2. `tiktoken` if installed.
3. Heuristic fallback: `ceil(len(text) / 4)`.

Do not add a hard dependency on `tiktoken`. Import it defensively inside the function.

## Acceptance Criteria

- Works when `tiktoken` is not installed.
- Returns method `"heuristic"` when falling back.
- Tests can force the heuristic path.
- Tests can mock a tiktoken encoder path.
- `200_000` characters estimates approximately `50_000` tokens by heuristic.
- JSON payload estimation serializes with `ensure_ascii=False`.

## Suggested Tests

```text
test_estimate_tokens_heuristic_chars_divided_by_four
test_estimate_json_payload_tokens_uses_serialized_json
test_estimate_tokens_uses_mocked_tiktoken_when_available
test_estimate_tokens_empty_string_is_zero_or_one_consistently
```

## Focused Test Command

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_token_budget.py --basetemp .pytest_tmp
```
