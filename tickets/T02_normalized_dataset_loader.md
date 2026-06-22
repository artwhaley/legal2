# T02 — Normalized Dataset Loader

## Goal

Implement the provisional normalized fixture loader for `dataset.json`, `source_threads.jsonl`, and `messages.jsonl`.

## Dependencies

T01.

## Implementation Notes

This is test plumbing, not final raw import. Validate required fields, normalize message body into `body_normalized`, compute or verify source-thread message counts, and log every load phase. For malformed rows, fail loudly with line numbers and details. Load should be idempotent for a fresh DB; if reloading into an existing dataset, use an explicit clear/reload path rather than silent overwrites.

## Files / Areas Likely Touched

- message_evidence_workstation/importers/normalized_loader.py
- message_evidence_workstation/db/repositories.py
- tests/fixtures/sample_dataset/
- tests/test_normalized_loader.py

## Acceptance Criteria

- A valid sample dataset loads into `dataset`, `source_thread`, and `message`.
- Loader logs counts for threads/messages.
- Bad JSONL line produces visible exception/log entry with file and line number.
- Messages sort correctly by `source_thread_id`, timestamp, and sort_index.
- Message records are treated as immutable after load.

## Tests / Verification

- Load sample fixture into temp DB and assert row counts.
- Test malformed JSONL.
- Test missing required field.
- Test normalized body generation.

## Non-Goals

- No raw Facebook/WhatsApp/Google Voice import.
- No UI file picker unless trivial.
- No FTS index building beyond logging a TODO.
