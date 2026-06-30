# WML04 - GUI Shell And Input Browser

## Goal
Create the lightweight PySide6 GUI shell with settings fields and source-window browsing.

## Depends On
- WML03

## Scope
- Implement `merge_lab_app.py`.
- Add settings panel fields:
  - `.evw` path
  - input JSON path
  - output directory
  - strategy selector
  - provider selector
  - model override
  - max output tokens
  - timeout seconds
  - dry run checkbox
  - no API checkbox
  - include raw scan text checkbox
  - compact display text checkbox
  - max ranges per window
  - merge batch size
- Add buttons:
  - Load From `.evw`
  - Load Input JSON
  - Save Input JSON
  - Build Prompt
  - Run Strategy
  - Parse Last Result
  - Evaluate Outputs
  - Open Output Folder
  - Clear Log
- Add source-window table/list.
- Add window detail panes for raw response, parsed JSON, and compact ranges.

## Guardrails
- GUI is for the spike only.
- Do not import production UI widgets.
- Do not freeze the GUI during file loading.

## Acceptance Criteria
- `python spikes\window_merge_lab\merge_lab_app.py` opens a window.
- User can load the exported input JSON.
- Source-window table shows six rows with model run id, window id, estimated tokens, range count, parse status, latency, and error status.
- Selecting a row updates detail panes.

