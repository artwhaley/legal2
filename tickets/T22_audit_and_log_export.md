# T22 — Audit and Log Export

## Goal

Add basic inspection/export for ProcessLog and ModelRun audit data so the MVP remains explainable.

## Dependencies

T10, T21.

## Implementation Notes

Settings should export process logs as text/JSON. Add a simple ModelRun viewer or table showing run type, model, prompt version, latency, error, and raw request/response. Output export can include an audit appendix toggle if easy, but the main goal is inspectability.

## Files / Areas Likely Touched

- message_evidence_workstation/ui/settings_tab.py
- message_evidence_workstation/nim/model_runs.py
- message_evidence_workstation/export/html_preview.py
- tests/test_audit_export.py

## Acceptance Criteria

- User can export ProcessLog to text or JSON.
- User can inspect ModelRun records.
- Failed NIM calls are visible in audit viewer.
- Prompt version used for a ModelRun is visible.
- Optional HTML audit appendix includes relevant run IDs and prompt versions.

## Tests / Verification

- Unit test log export.
- Unit test ModelRun query.
- Manual inspect a keyword expansion and range suggestion ModelRun.

## Non-Goals

- No sophisticated diff viewer.
- No redaction system unless explicitly requested.
