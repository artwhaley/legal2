# Mission and Non-Negotiable Invariants

## Mission

Transform the current PySide/SQLite application in four gated phases:

1. Prove Windows Flutter can perform the local EVW data-engine operations.
2. Harden and compact the EVW schema and lifecycle, including working-corpus scope and WAL recovery.
3. Extract model routing and embedding generation into a stateless Python server.
4. Retarget the current Python frontend to the server and prove the split.

The implementation must be functional, sequential, observable, and boring. It must not optimize for a visual appearance of completion.

## Data ownership

The EVW contains one canonical full corpus per file. It may contain:

- source threads and messages;
- evidence blocks and highlights;
- printable artifacts;
- visible conversational prompts and presented answers;
- normalized visible citations;
- non-secret workspace settings;
- a working-corpus definition and its derived membership/index state;
- FTS5, spellfix, chunks, vectors, and vector metadata.

The EVW must not contain:

- raw model requests or responses;
- hidden prompt bodies or intermediate windows;
- process logs or model-run payloads;
- provider request/response bodies;
- API keys, authentication tokens, payment state, subscriptions, or BYOK secrets;
- duplicated transcript bodies in working-corpus tables.

Account and payment records belong to a future server database. Secrets belong in future server secret storage or an OS credential store.

## Behavioral invariants

- One canonical full corpus exists per EVW.
- One active working corpus is indexed at a time.
- A working corpus is a selection definition plus materialized membership, never a second message store.
- Every FTS, spellfix, vector, transcript, window, and conversational search operation requires a ready working-corpus scope.
- A date filter may narrow a working corpus but never broaden it.
- A working corpus over 768,000 estimated tokens is rejected; it is never silently trimmed, sampled, or truncated.
- A changed canonical corpus marks the working corpus stale.
- Search refuses stale or partially indexed working corpora. There is no hidden fallback to the full corpus or an older index.
- All important operations expose start, progress, completion, and failure state.
- No hidden retry, provider switch, model switch, or local fallback is allowed.
- No database transaction spans network/model work, UI waits, or long computation.
- One serialized writer owns writes; readers are operation-scoped and close promptly.
- A blocked idle checkpoint is a visible failure, not a condition to hide.
- A nonempty WAL is never manually deleted.
- Migration never destructively edits the live EVW before a validated replacement exists.

## Existing contact surfaces

The primary Python surfaces are:

- Database: `message_evidence_workstation/db/connection.py`, `db/schema.py`, `db/migrations.py`, `db/workspace.py`, `db/repositories.py`.
- Domain: `message_evidence_workstation/domain/constants.py`, `domain/models.py`.
- Logging/export: `logging_ui/process_log.py`, `logging_ui/log_bus.py`, `diagnostics/trace_log.py`, `export/audit_export.py`.
- LLM: `llm/router.py`, `llm/types.py`, `llm/providers/*`, `llm/task_roles.py`, `nim/client.py`, `nim/model_runs.py`, `nim/prompts.py`.
- Search: `search/keyword_expansion.py`, `search/fts.py`, `search/embedding_search.py`, `search/transcript.py`, `search/window_planner.py`, `search/conversational_answer.py`, `search/evidence_ledger.py`, `search/ledger_validator.py`.
- Embeddings: `embeddings/adapters.py`, `service.py`, `index_jobs.py`, `sqlite_vec_backend.py`, `dataset_embedding_cache.py`.
- UI/lifecycle: `app.py`, `app_bootstrap.py`, `ui/main_window.py`, `ui/settings_tab.py`, `ui/search_worker.py`, `ui/conversational_tab.py`, `ui/embedding_worker.py`.
- Tests: all `tests/test_*.py`, especially schema, workspace, FTS, sqlite-vec, embeddings, conversational answer, logging, audit export, and UI smoke tests.

Do not create parallel replacements for these modules when an existing module can be extended cleanly.
