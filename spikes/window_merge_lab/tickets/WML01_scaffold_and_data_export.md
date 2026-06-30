# WML01 - Scaffold And Data Export

## Goal
Create the spike scaffolding and a read-only exporter for the six successful scan-window model runs.

## Depends On
- None

## Scope
- Ensure this directory exists:
  - `spikes/window_merge_lab/`
  - `spikes/window_merge_lab/inputs/`
  - `spikes/window_merge_lab/outputs/`
- Add empty or skeletal modules:
  - `merge_lab_app.py`
  - `merge_lab.py`
  - `db_export.py`
  - `data_loader.py`
  - `strategies.py`
  - `prompts.py`
  - `evaluator.py`
- Implement `db_export.py` to read model runs `165-170` from:
  - `C:\Users\artwh\.message_evidence_workstation\workspace.evw`
- Export:
  - `inputs/school_scan_windows.json`
  - `inputs/school_scan_windows_compact.json`

## Guardrails
- Open `.evw` read-only where practical.
- Do not mutate the database.
- Do not call any model APIs.
- Do not import production UI widgets.

## Acceptance Criteria
- Running `python spikes\window_merge_lab\db_export.py` creates both input files.
- Export contains all six successful `exhaustive_window_scan` model runs.
- Each exported window includes model run id, window id, message ids, raw response text, parsed response if parseable, latency, provider/model, and error status.

