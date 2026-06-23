# Ticket 07: Wire Exhaustive Scan To Token Windows

## Goal

Make exhaustive scan inspect token-bounded windows instead of raw sessions.

## Files

Update:

```text
message_evidence_workstation/search/conversational_answer.py
tests/test_conversational_answer.py
```

Use:

```text
message_evidence_workstation/search/window_planner.py
```

## Implementation

Update `run_exhaustive_window_scan_answer`.

Instead of serializing each session directly:

1. Rebuild/load sessions as before.
2. Build token-bounded windows with `window_target_tokens` and `window_overlap_messages`.
3. Run one `exhaustive_window_scan` NIM call per planned window.
4. Merge all window findings.

Each scan payload should include:

```json
{
  "window_id": "...",
  "session_id": "...",
  "source_thread_id": "...",
  "estimated_tokens": 1234,
  "message_ids": ["..."],
  "transcript": "..."
}
```

Merge coverage should include:

```json
{
  "messages_considered": 100,
  "sessions_considered": 15,
  "windows_inspected": 22,
  "sessions_skipped": 0,
  "token_budget": {
    "window_target_tokens": 12000,
    "context_window_tokens": 128000,
    "context_source": "registry",
    "safety_ratio": 0.70
  }
}
```

If existing `CoverageSummary` lacks `windows_inspected`, add it compatibly with default `0`.

## Acceptance Criteria

- Exhaustive mode inspects every planned window.
- Merge receives every window finding.
- No messages are omitted.
- Existing forced two-window tests are updated and pass.
- Coverage reports window count.

## Suggested Tests

```text
test_run_exhaustive_window_scan_inspects_every_planned_window
test_exhaustive_scan_payload_contains_window_id_and_estimated_tokens
test_exhaustive_scan_coverage_reports_windows_inspected
```

## Focused Test Command

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_conversational_answer.py tests\test_window_planner.py --basetemp .pytest_tmp
```
