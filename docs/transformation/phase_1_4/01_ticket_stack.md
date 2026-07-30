# Phase 1–4 Ticket Stack

This is the authoritative ticket order. Do not parallelize tickets across a phase unless the dependency column explicitly permits it. Every ticket must leave the repository testable.

## XFM-000 — Baseline and safety gate

Dependencies: none.

Inspect `AGENTS.md`, git status, current tests, schema/table counts, dataset counts, EVW size, WAL size, vector metadata, active prompts, and all direct model/embedding call sites. Do not modify the live EVW.

Done when the baseline and call-site inventory are recorded in `docs/transformation/phase_1_4_execution_log.md`.

## XFM-101 — Flutter Windows project

Dependencies: XFM-000.

Create Windows-only `flutter_client/`, pin the toolchain, use direct SQLite FFI, and add no product UI or speculative architecture.

## XFM-102 — Flutter SQLite native assets

Dependencies: XFM-101.

Package and hash Windows x64 sqlite-vec 0.1.9 and spellfix. Load known native entrypoints through Dart FFI. Do not use SQL `load_extension` or Python virtual-environment binaries.

## XFM-103 — EVW compatibility probe

Dependencies: XFM-102.

Implement the complete matrix in `04_flutter_compatibility_spec.md` against copied v12 and fixture EVWs.

## XFM-104 — Flutter release gate

Dependencies: XFM-103.

Run the packaged Windows release probe. Do not begin Phase 2 while it is red.

## XFM-201 — Remove database diagnostics and prompt dependency

Dependencies: XFM-000.

Freeze exact active prompts as prompt-set v1. Replace `process_log`/`model_run` persistence with external metadata-only rotating logs and an in-memory event bus. Remove prompt-table dependency and prompt editor behavior. Temporarily preserve local provider settings only until Phase 4.

## XFM-202 — Schema v13 and working-corpus model

Dependencies: XFM-201.

Implement schema v13 from `03_evw_schema_and_wal_spec.md` and `02_working_corpus_spec.md`. Retain one canonical full corpus. Add workspace, conversation, event, and working-corpus tables. Remove development-noise tables from production v13. Enforce one dataset per EVW and one active indexed working corpus.

## XFM-203 — Repositories and working-corpus service

Dependencies: XFM-202.

Implement typed repositories for conversations, citations, settings, events, working-corpus preview/creation/activation/status, membership materialization, token-limit enforcement, stale marking, and index-generation state. Persist visible completed conversation turns only.

## XFM-204 — Single writer and scoped indexes

Dependencies: XFM-202, XFM-203.

Implement one serialized writer, operation-scoped readers, caller-owned transactions, and working-corpus-scoped FTS/vector/chunk access. No search function may operate from dataset ID alone. Vector partition identity must include model and working-corpus ID inside the sqlite-vec query.

## XFM-205 — Startup, WAL, checkpoint, and close lifecycle

Dependencies: XFM-204.

Implement the startup/operation/shutdown rules in `03_evw_schema_and_wal_spec.md`. Update `app.py`, `app_bootstrap.py`, and `ui/main_window.py`. No manual WAL deletion and no hidden busy retries.

## XFM-206 — Safe v12-to-v13 compact-copy migration

Dependencies: XFM-203, XFM-204, XFM-205.

Create a validated compact backup, build a temporary v13 file, preserve canonical data, create the default full-dataset working-corpus definition, enforce the 768,000-token gate, rebuild scoped derived indexes, validate, and atomically replace only after success. Require explicit dataset selection when necessary.

## XFM-207 — Phase 2 regression gate

Dependencies: XFM-206.

Run schema, migration, WAL, crash, backup, working-corpus, FTS, vector, evidence, artifact, conversation, and full-regression tests. The Flutter probe must pass against v13.

## XFM-301 — Stateless server package

Dependencies: XFM-207.

Create small `server/` package with FastAPI and `python -m server`. No server DB, auth, billing, or cloud deployment.

## XFM-302 — Server contracts and prompt registry

Dependencies: XFM-301.

Implement typed endpoint contracts, request IDs, stable error envelopes, working-corpus metadata, and exact prompt-set v1.

## XFM-303 — Server provider and embedding routing

Dependencies: XFM-302.

Move provider/model/embedding routing to the server. Use explicit environment configuration. Preserve current error behavior and do not retry or switch providers/models.

## XFM-304 — Server endpoints

Dependencies: XFM-303.

Implement the endpoints in `05_server_contract_spec.md`, including embeddings, whole-transcript answers, exhaustive scans, both merge paths, and evidence-ledger synthesis.

## XFM-305 — Server gate

Dependencies: XFM-304.

Run fake-provider contract tests, malformed-response tests, prompt-hash tests, no-body-logging tests, and independent startup tests.

## XFM-401 — Python remote gateway

Dependencies: XFM-305.

Add one typed remote model gateway and one remote embedding adapter. Convert server failures into visible client failures. No retry or local fallback.

## XFM-402 — Retarget search and conversational flows

Dependencies: XFM-401.

Route keyword expansion, retrieval terms, whole-transcript answers, exhaustive scans, both merges, and evidence-ledger synthesis through the server. Keep working-corpus selection, FTS, vectors, transcript/window planning, evidence, and persistence local.

## XFM-403 — Retarget embeddings

Dependencies: XFM-401.

Route message/chunk/query embedding generation to the server. Store vectors and perform all lookup locally. Preserve resume/index-generation behavior.

## XFM-404 — Settings and secret scrub

Dependencies: XFM-402, XFM-403.

Replace provider/key/model controls with server URL/status/capabilities. Remove prompt editing and plaintext provider keys after the remote path is proven.

## XFM-405 — Final split gate

Dependencies: XFM-404.

Run complete parity, outage, malformed-response, provider-failure, restart, local-only, working-corpus, FTS, vector, migration, and static import-boundary tests. Confirm no raw calls, logs, model runs, prompts, or secrets remain in EVW.
