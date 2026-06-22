# T13 — sqlite vec Validation and Diagnostics

## Goal

Implement sqlite-vec backend loading and a visible validation/smoke-test action on the Settings tab.

## Dependencies

T12, T01, T03.

## Implementation Notes

This ticket proves sqlite-vec can load and perform known-vector insert/query. It must not silently fall back. Log extension path, SQLite version, sqlite-vec version if available, table DDL, vector dimensions, inserted rows, query result IDs/distances, and any exception/stack trace. If sqlite-vec is unavailable, mark backend failed and disable dependent vector actions.

## Files / Areas Likely Touched

- message_evidence_workstation/embeddings/sqlite_vec_backend.py
- message_evidence_workstation/ui/settings_tab.py
- message_evidence_workstation/db/schema.py
- tests/test_sqlite_vec_backend.py

## Acceptance Criteria

- Settings has `Validate sqlite-vec` action.
- Validation checks extension load and known nearest-neighbor query.
- Dimension mismatch test produces understandable visible/logged error.
- Validation status is persisted or visible in EmbeddingIndexMetadata/process log.
- No alternate vector backend is used automatically.

## Tests / Verification

- Unit tests with sqlite-vec skipped if extension unavailable.
- Manual validation test on target dev machine.
- Forced bad extension path logs failure and disables vector jobs.

## Non-Goals

- No message/chunk embedding index build yet.
- No FAISS/LanceDB fallback.
