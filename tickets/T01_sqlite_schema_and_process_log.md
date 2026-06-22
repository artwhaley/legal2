# T01 — SQLite Schema and Process Log

## Goal

Add SQLite connection management, schema initialization, and the persistent process log table/service. This makes later failures visible instead of silent.

## Dependencies

T00.

## Implementation Notes

Implement a simple migration/version mechanism. Create core tables from the spec even if some are not fully used yet. The ProcessLogger must write to SQLite and also emit/log in a way the future UI can subscribe to. Do not hide exceptions; capture severity, component, operation, message, details JSON, exception type, and stack trace.

## Files / Areas Likely Touched

- message_evidence_workstation/db/connection.py
- message_evidence_workstation/db/schema.py
- message_evidence_workstation/db/migrations.py
- message_evidence_workstation/logging_ui/process_log.py
- message_evidence_workstation/domain/models.py
- tests/test_schema.py
- tests/test_process_log.py

## Acceptance Criteria

- App creates/open a workspace SQLite DB.
- Schema includes all first-wave non-vector tables from the build plan.
- `process_log` table exists and can store debug/info/warning/error records.
- Exceptions can be logged with stack traces.
- Schema initialization logs start/end/failure.

## Tests / Verification

- Unit test schema creation in a temp DB.
- Unit test process log insert/retrieve.
- Force a logged exception and verify exception fields are populated.

## Non-Goals

- No UI log window yet.
- No sqlite-vec tables yet unless harmlessly stubbed.
- No dataset loader.
