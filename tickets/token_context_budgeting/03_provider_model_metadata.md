# Ticket 03: Preserve Provider Model Metadata

## Goal

Keep raw model metadata from provider model-list responses so context-window detection can use it when available.

## Files

Update:

```text
message_evidence_workstation/nim/client.py
tests/test_nim_client.py
```

Inspect:

```text
message_evidence_workstation/ui/settings_tab.py
```

## Implementation

Change:

```python
@dataclass(slots=True)
class NimModelInfo:
    id: str
```

To:

```python
@dataclass(slots=True)
class NimModelInfo:
    id: str
    metadata: dict[str, Any] = field(default_factory=dict)
```

In `NimClient.list_models()`:

- Preserve the raw model item as `metadata`.
- Existing UI code that reads `.id` must continue to work.
- Do not assume provider metadata contains context fields.

## Acceptance Criteria

- Model list UI still works.
- Tests confirm `.id` still works.
- Tests confirm raw metadata is preserved.

## Suggested Tests

```text
test_list_models_preserves_metadata
test_list_models_supports_name_or_id
```

## Focused Test Command

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_nim_client.py --basetemp .pytest_tmp
```
