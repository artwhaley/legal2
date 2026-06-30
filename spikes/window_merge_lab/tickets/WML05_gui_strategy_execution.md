# WML05 - GUI Strategy Execution

## Goal
Wire prompt building, dry-run, API execution, output writing, and visible activity logging into the GUI.

## Depends On
- WML04

## Scope
- Build prompt from current GUI settings.
- Show prompt preview and exact payload in GUI panes.
- Run strategies from GUI.
- Keep GUI responsive during API calls.
- Show:
  - raw model response
  - parsed JSON
  - readable markdown
  - errors/tracebacks
  - output folder path
- Append timestamped activity log messages.

## Guardrails
- Dry-run must never call the API.
- `No API` must prevent API calls.
- Do not rerun scan-window calls.
- Save outputs under `spikes/window_merge_lab/outputs/`.

## Acceptance Criteria
- Build Prompt works without API calls.
- Dry-run writes output files and updates GUI panes.
- Run Strategy executes selected strategy or reports a clear error.
- API failures are visible and saved, not swallowed.

