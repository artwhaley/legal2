# T03 — PySide6 Shell Sidebar and Settings Log

## Goal

Build the main two-division UI shell: persistent left sidebar and right-side tab workflow area. Add the Setup/Settings tab with a live verbose log window.

## Dependencies

T01, T02 useful but not strictly required.

## Implementation Notes

The sidebar should reserve space for the source-thread selector and category tree even if some content is placeholder. The right side should expose tabs: Simple Search, Conversational Interface, Output Formatting, Setup / Settings. The settings log window should subscribe to the ProcessLogger/log bus and also be able to load persisted log rows. Keep it noisy.

## Files / Areas Likely Touched

- message_evidence_workstation/ui/main_window.py
- message_evidence_workstation/ui/sidebar.py
- message_evidence_workstation/ui/settings_tab.py
- message_evidence_workstation/logging_ui/log_bus.py

## Acceptance Criteria

- Main window has left sidebar and right tabs.
- Tabs exist with clear placeholders.
- Settings tab shows live process log entries.
- Settings log supports severity filter at minimum.
- A test log button or startup event proves live logging works.

## Tests / Verification

- Run app and confirm layout.
- Generate info/warning/error logs and verify display.
- Restart app and confirm persisted logs can be loaded.

## Non-Goals

- No polished styling.
- No real category behavior yet.
- No NIM settings fields unless started as placeholders.
