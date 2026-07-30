# Validation and Phase Gates

## Baseline

Run and record:

```powershell
git status --short --branch
pytest
python scripts/inspect_workspace_db.py
```

Record existing failures separately from regressions.

## Flutter commands

From `flutter_client/`:

```powershell
flutter test
flutter build windows --release
```

Run the compatibility probe against a copied v12 EVW, fixture EVWs, and a migrated v13 EVW.

## Python/server commands

```powershell
pytest
python -m server
```

Server tests must use deterministic fake providers and must not need a live provider credential.

## Database acceptance

Verify:

- schema version is 13;
- excluded development tables are absent;
- canonical row counts match the migration source for selected data;
- full-corpus messages remain available even if the working corpus is over limit;
- working-corpus membership has no duplicated bodies;
- working-corpus token count is recorded and bounded;
- stale working corpora cannot be searched;
- FTS and vector queries cannot cross working-corpus boundaries;
- evidence/artifact/citation foreign keys are valid;
- `quick_check` and `foreign_key_check` pass;
- clean close leaves no meaningful WAL;
- crash recovery preserves committed data and excludes uncommitted data;
- backup restoration opens successfully.

## Server acceptance

Verify:

- server starts without opening EVW;
- all versioned endpoints have typed contracts;
- request IDs are preserved;
- working-corpus identity/generation is accepted as metadata;
- embeddings preserve order and dimensions;
- malformed provider output fails visibly;
- oversized input fails without truncation;
- no retries or provider/model substitutions occur;
- logs never contain transcript, prompt, request, or response bodies.

## Final split acceptance

Verify:

- Python client has no direct provider SDK imports;
- Python client has no local sentence-transformer embedding path;
- all search/model/embedding operations use the intended remote/local boundary;
- local FTS and vector lookup remain functional if the server is unavailable;
- server failure never broadens search to the full corpus;
- visible conversation history survives restart;
- hidden model calls do not appear in EVW;
- all current relevant tests pass.

## Failure policy

Fix failures directly. Do not weaken assertions, skip tests, add silent fallbacks, or mark a partial index ready. Stop for user instruction only for data-selection ambiguity, unavoidable data-loss risk, missing external authority, or an external/native blocker that remains after three distinct safe fixes.
