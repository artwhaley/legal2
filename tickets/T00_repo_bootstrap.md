# T00 — Repo Bootstrap

## Goal

Create the initial Python project skeleton, dependency file, app entry point, and test harness. The app does not need real features yet, but it must run and it must establish the project conventions used by later tickets.

## Dependencies

None.

## Implementation Notes

Use Python 3.11+ unless the local environment demands otherwise. Use PySide6 for UI, pytest for tests, and standard logging only as a bridge until the ProcessLog service exists. Create the package structure described in the build plan. Keep the first runnable window minimal.

## Files / Areas Likely Touched

- pyproject.toml
- README.md
- message_evidence_workstation/app.py
- message_evidence_workstation/__init__.py
- message_evidence_workstation/ui/main_window.py
- tests/test_smoke.py

## Acceptance Criteria

- `python -m message_evidence_workstation.app` opens a basic PySide6 window.
- `pytest` runs and passes at least one smoke test.
- Project structure matches the build plan closely enough for later tickets.
- README includes setup/run/test commands.

## Tests / Verification

- Run app manually.
- Run `pytest`.
- Confirm no external services or model downloads are required for this ticket.

## Non-Goals

- No database schema yet.
- No real search.
- No NIM.
- No embeddings.
