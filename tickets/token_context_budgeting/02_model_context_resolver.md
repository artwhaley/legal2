# Ticket 02: Add Model Context Resolver

## Goal

Resolve the selected model's context window from the best available source: user override, provider metadata, local registry, or safe default.

## Files

Create:

```text
message_evidence_workstation/nim/model_context.py
tests/test_model_context.py
```

Inspect:

```text
message_evidence_workstation/nim/client.py
message_evidence_workstation/config/settings.py
```

## Implementation

Add:

```python
@dataclass(slots=True)
class ModelContextWindow:
    model_id: str
    context_window_tokens: int
    source: str  # user_override | provider | registry | default
    default_output_tokens: int = 4096
```

Add defaults:

```python
DEFAULT_CONTEXT_WINDOW_TOKENS = 32768
DEFAULT_CONTEXT_SAFETY_RATIO = 0.70
DEFAULT_RESERVED_OUTPUT_TOKENS = 4096
DEFAULT_PROMPT_OVERHEAD_TOKENS = 1500
DEFAULT_WINDOW_TARGET_TOKENS = 12000
DEFAULT_WINDOW_OVERLAP_MESSAGES = 2
```

Add local registry:

```python
MODEL_CONTEXT_REGISTRY = {
    "minimaxai/minimax-m3": ModelContextWindow(...),
}
```

Use a conservative value if the exact model context is unknown. If you are not certain of a model's context size, do not invent a confident large number. Use the safe default and let the user override.

Add:

```python
def resolve_model_context(
    model_id: str,
    provider_metadata: dict | None = None,
    user_override_tokens: int | None = None,
) -> ModelContextWindow:
    ...
```

Resolution order:

1. User override if positive.
2. Provider metadata if it contains a recognized positive integer.
3. Local registry.
4. Safe default.

Provider metadata keys to detect:

```text
context_length
context_window
max_context_length
max_model_len
max_sequence_length
input_token_limit
max_input_tokens
```

## Acceptance Criteria

- User override wins.
- Provider metadata wins over registry.
- Registry is used for known models.
- Unknown models use safe default.
- Non-integer or invalid metadata is ignored safely.

## Suggested Tests

```text
test_user_override_wins
test_provider_metadata_wins_over_registry
test_registry_used_for_known_model
test_unknown_model_uses_safe_default
test_invalid_provider_metadata_ignored
```

## Focused Test Command

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_model_context.py --basetemp .pytest_tmp
```
