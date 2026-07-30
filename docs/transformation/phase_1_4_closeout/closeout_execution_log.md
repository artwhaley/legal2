# Closeout execution log

This file records the implementation and verification work for the clean-break Phase 1–4 closeout packet.

## Baseline — 2026-07-18

- Repository: `main`, `HEAD` and `origin/main` are aligned (`0` commits ahead, `0` behind).
- The worktree already contains user/agent changes from the preceding transformation work. Those changes are preserved; no reset or checkout cleanup is permitted.
- Runtime EVW schema is currently v13. Runtime migration branches for earlier schema versions still exist.
- The current Python client still exposes legacy local-provider/model-routing and prompt/model-run surfaces.
- The current persistence layer still exposes direct SQLite connection access and more than one writable-connection path.
- The current Flutter executable is probe-oriented rather than a production read-only EVW viewer.

## Execution rule

Implementation follows `README.md` and `kickoff_prompt.md` in this directory. This is a clean break to v14: incomplete compatibility paths are removed from runtime code, and migration is an explicit one-shot tool. Existing dirty files remain in place unless a ticket explicitly changes them.

## Implementation completed — 2026-07-18

- EVW v14 is now the only runtime schema. Fresh workspaces create v14;
  runtime open rejects older or incomplete files. v12/v13 conversion is an
  explicit compact-copy command and does not edit its source unless the caller
  explicitly requests in-place replacement.
- Canonical data, evidence blocks, printable artifacts, settings, visible
  conversation history, working-corpus definitions/membership, and rebuildable
  local indexes are retained. Provider payloads, prompt templates, model runs,
  raw embedding requests, secrets, and development logs are not stored in the
  EVW. External diagnostics are metadata-only rotating JSONL.
- Working-corpus activation is atomic at the product boundary: the previous
  active corpus remains searchable while a replacement builds; a replacement
  becomes active only after membership, FTS5, and spellfix are complete. Empty
  and over-limit corpora cannot activate. Dataset content revision is explicit
  and corpus scope identity includes the revision, selection, membership, and
  tokenizer.
- EVW lifecycle is centralized in `WorkspaceStore`: one writer thread,
  short read transactions, sidecar lock, WAL FULL/synchronous settings,
  startup integrity/recovery checkpoint, periodic checkpoint monitoring, and
  clean-close WAL truncation.
- The Python client is local-first for EVW ownership, FTS5/spellfix, sqlite-vec
  storage/KNN, transcript construction, corpus scope, and visible-history
  persistence. The v2 gateway is the only remote model surface. Automatic
  conversational search uses whole-transcript mode when the advertised budget
  fits and otherwise performs retrieval-term expansion, deterministic windows,
  window scans, and ledger synthesis with local citation validation.
- The server is stateless and EVW-blind. It exposes only v2 health,
  capabilities, keyword expansion, retrieval terms, embeddings, whole
  transcript, window scan, and evidence-ledger synthesis endpoints. No client
  provider/model code remains in the server boundary or vice versa.
- Flutter Windows now opens v14 EVWs read-only, validates integrity, displays
  full and active working-corpus metadata, pages the transcript, and has no
  write or server path in this phase.

## Verified gates

- `python -m pytest -q --basetemp .tmp\pytest-basetemp`: 6 passed.
- `python -m compileall -q message_evidence_workstation server scripts tests`:
  passed.
- `python scripts\verify_package_boundaries.py`: passed.
- v12/v13 fixture compact-copy plus `python scripts\verify_evw_v14.py`:
  passed.
- Local wheel build via `python -m pip wheel . --no-deps`: passed. The
  environment does not provide the separate `build` module, so `python -m
  build` itself was unavailable.
- `flutter pub get`, `flutter test`, `flutter analyze`, and
  `flutter build windows --release`: passed.
- The release executable's `--probe --evw` against a freshly migrated v14
  artifact: 28 passed, 0 failed.

## Post-closeout hygiene correction — 2026-07-20

- Removed the stale crash-trace import from the Python entry point after
  verifying the final source tree. The entry point now imports and parses CLI
  options cleanly without restoring the deleted legacy trace module.
- Updated the root and Flutter READMEs for the v14 split architecture and the
  direct Windows release-executable probe command.

## Per-endpoint server configuration correction — 2026-07-20

- Replaced the environment-only single-model router with one persistent,
  validated server configuration for keyword expansion, retrieval terms,
  whole-transcript answers, exhaustive window scans, evidence-ledger
  synthesis, and embeddings.
- Added the local server control panel (`python -m server.gui`). Every chat
  endpoint exposes provider, base URL, API key, model, context window, request
  budget, output budget, timeout, and temperature. The embedding tab exposes
  model, revision, normalization, batch size, and required dimensions.
- The control panel saves atomically outside the EVW, tests the selected
  endpoint, starts/stops the server, displays process output, and reports API
  health. The headless server reads the same configuration file.
- Migrated the last working client configuration to
  `C:\Users\artwh\.message_evidence_server\server.json`: GLM-5.2 for keyword
  expansion/retrieval terms; DeepSeek V4 Flash for whole transcript, window
  scan, and ledger synthesis; all-MiniLM-L6-v2 for embeddings.
- Hardened all five prompt responses to exact JSON types and made window-scan
  output validation explicit after a live provider test exposed an invalid
  string-valued `coverage_summary`.
- Live API v2 validation passed health, capabilities, keyword expansion,
  retrieval terms, embeddings, whole transcript, window scan, and evidence
  ledger synthesis with the assigned models.

## Resumable embedding-build correction — 2026-07-21

- Replaced the synchronous UI-thread embedding build with a background worker
  and visible phase, message count, batch count, progress bar, and elapsed time.
- Moved remote embedding calls outside SQLite writer transactions. Each batch
  is validated and committed through the single writer before the next server
  call begins.
- Removed destructive restart behavior. Matching committed message/chunk
  vectors are counted and retained; failed or interrupted builds resume only
  the missing batches. There is no automatic network retry.
- Added exact batch/count failure messages and durable failed/ready status on
  the active corpus index.
- Corrected read-only SQLite connections so the local sqlite-vec extension can
  load for GUI embedding searches while the URI remains filesystem read-only.
