# EVW Schema, Migration, and WAL Specification

## Schema v13

Set `SCHEMA_VERSION = 13` in `message_evidence_workstation/domain/constants.py`.

Retain canonical tables for the full corpus, source threads/messages, evidence, categories, and printable artifacts.

Add:

- `workspace_state`
- `workspace_setting`
- `conversation`
- `conversation_turn`
- `conversation_citation`
- `workspace_event`
- working-corpus tables defined in `02_working_corpus_spec.md`

`conversation_turn` stores only the visible user prompt and presented answer. It may store mode, status, timestamps, and visible citation references. It must not store raw model calls, hidden window results, prompt bodies, token payloads, or unpresented responses.

Remove from production v13:

- `prompt_template`
- `model_run`
- `process_log`
- orphaned style-lab tables/settings
- validation-smoke tables

FTS, spellfix, chunks, vectors, and embedding metadata remain in the EVW as rebuildable derived indexes.

No API keys, provider credentials, account state, payment state, or BYOK secrets may be stored in the EVW.

## Prompt and diagnostics transition

Before dropping prompt tables, inspect the current active workspace prompt rows and freeze their exact bodies as prompt-set v1 with hashes.

Replace database process/model logging with:

- in-memory UI event bus;
- rotating external JSONL diagnostics under the user application-data directory;
- maximum five 10 MiB files;
- metadata, state transitions, counts, durations, error type, and stack trace allowed;
- transcript text, queries, prompt bodies, response bodies, embeddings, and provider payloads prohibited.

The current Python client may temporarily retain existing plaintext provider settings until Phase 4 proves the server path. They must never be migrated into EVW and must be removed after successful retargeting.

## Transaction ownership

Use one workspace lifecycle owner and one serialized writer connection. Repository functions participate in caller-owned transactions and never commit internally.

Readers are short-lived read-only connections or explicitly scoped read transactions. They must close before returning to the UI and must never remain open across HTTP/model work.

Configure connections with:

```text
foreign_keys=ON
journal_mode=WAL
synchronous=FULL
wal_autocheckpoint=1000
```

Unexpected lock contention is surfaced; no hidden retry policy is allowed.

## Startup

1. Acquire an exclusive workspace lock.
2. Detect an unclean marker or existing WAL.
3. Open through normal SQLite recovery.
4. Run `quick_check` and `foreign_key_check`.
5. Run `wal_checkpoint(TRUNCATE)` and inspect `busy`, `log`, and `checkpointed` values.
6. Apply migration if necessary.
7. Mark the workspace open/unclean.

If recovery, integrity, or checkpointing fails, preserve all files and stop visibly.

## Normal operation

- Import transactions are bounded and observable.
- Embedding writes commit per remote/local batch.
- Long jobs perform explicit passive checkpoint checks at bounded batch intervals.
- Every top-level mutation closes its readers and performs a final truncate checkpoint.
- A checkpoint that remains busy at an idle operation boundary is a visible lifecycle failure and blocks new bulk work.

## Shutdown

1. Stop accepting new work.
2. Cancel or finish workers and report progress.
3. Wait for writer idle.
4. Close readers.
5. Mark clean shutdown and commit.
6. Run and verify `wal_checkpoint(TRUNCATE)`.
7. Close all connections.
8. Release the workspace lock.

Never manually delete a nonempty WAL. A failed close preserves the database and reports the recovery requirement.

## Migration

Migration is compact-copy, not destructive in-place alteration:

1. Acquire exclusive lock.
2. Open source through SQLite recovery.
3. Validate and checkpoint source.
4. Create a compact pre-v13 backup using SQLite backup or `VACUUM INTO`.
5. Build a same-volume temporary v13 file.
6. Require explicit dataset selection if multiple datasets exist.
7. Copy and validate canonical data.
8. Create the default full-dataset working-corpus definition.
9. Materialize its membership and enforce the 768,000-token gate.
10. Rebuild scoped FTS/spellfix/chunks and repack valid existing vectors without unnecessary re-embedding.
11. Validate counts, foreign keys, integrity, evidence references, working-corpus scope, FTS, and vectors.
12. Close all handles.
13. Atomically replace the original with the validated file.
14. Retain the compact pre-v13 backup.

Until step 13 succeeds, the original remains usable.
