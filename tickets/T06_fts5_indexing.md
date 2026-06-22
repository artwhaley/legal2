# T06 — FTS5 Indexing

## Goal

Add SQLite FTS5 indexing for messages and repository functions for exact/partial search.

## Dependencies

T02.

## Implementation Notes

Create `message_fts` virtual table linked to messages or maintained by explicit rebuild code. Support rebuild after dataset load. Define exact vs partial behavior clearly. Exact should mean phrase/token match for the entered text; partial should use prefix/wildcard token behavior where safe. Log raw query, escaped query, elapsed time, result count, and errors.

## Files / Areas Likely Touched

- message_evidence_workstation/search/fts.py
- message_evidence_workstation/db/schema.py
- message_evidence_workstation/importers/normalized_loader.py
- tests/test_fts.py

## Acceptance Criteria

- FTS5 table is created.
- Dataset load/rebuild populates FTS index.
- Exact search returns expected messages.
- Partial/prefix search returns expected messages.
- Bad user search syntax is escaped or reported clearly, not silently swallowed.
- FTS queries write ProcessLog records.

## Tests / Verification

- Unit tests with small fixture.
- Test punctuation/quotes handling.
- Test empty query behavior.
- Test timing/result count log entries.

## Non-Goals

- No search UI yet.
- No keyword expansion.
- No embeddings.
