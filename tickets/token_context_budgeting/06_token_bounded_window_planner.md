# Ticket 06: Add Token-Bounded Window Planner

## Goal

Build exhaustive-scan windows that respect token targets while preserving message boundaries and full coverage.

## Files

Create:

```text
message_evidence_workstation/search/window_planner.py
tests/test_window_planner.py
```

Inspect:

```text
message_evidence_workstation/search/session_map.py
message_evidence_workstation/search/transcript.py
message_evidence_workstation/search/token_budget.py
```

## Implementation

Add:

```python
@dataclass(slots=True)
class TranscriptWindow:
    window_id: str
    session_id: str
    source_thread_id: str
    start_message_id: str
    end_message_id: str
    message_ids: list[str]
    estimated_tokens: int
    text: str
```

Add:

```python
def build_token_bounded_windows(
    conn: sqlite3.Connection,
    dataset_id: int,
    sessions: list[TranscriptSession],
    *,
    target_tokens: int,
    overlap_messages: int,
    model_id: str,
) -> list[TranscriptWindow]:
    ...
```

Behavior:

- Preserve chronological order.
- Prefer session boundaries.
- If a session fits under `target_tokens`, produce one window.
- If a session exceeds `target_tokens`, split into message windows.
- Never split a message.
- Include overlap messages between split windows.
- Do not omit messages.
- Overlap duplicates are allowed only as configured.

## Acceptance Criteria

- Small sessions are not split.
- Oversized sessions split into multiple windows.
- Overlap works.
- Every original message appears in at least one window.
- Chronological order is preserved.
- Empty sessions are handled safely.

## Suggested Tests

```text
test_small_session_produces_one_window
test_large_session_splits_by_token_target
test_overlap_messages_are_included
test_no_message_loss
test_window_text_contains_message_ids
```

## Focused Test Command

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_window_planner.py --basetemp .pytest_tmp
```
