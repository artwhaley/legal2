# Acceptance Matrix and Closeout Procedure

## Required fixtures

1. `scope_boundary_v14.evw`: at least two sources and two threads. Active
   limited corpus contains `INSIDE_SCOPE_ALPHA`; canonical full corpus also
   contains excluded `OUTSIDE_SCOPE_OMEGA` whose vector is intentionally the
   globally closest result for one query.
2. `over_limit_source`: deterministic token-counter test data producing exactly
   768,000 and 768,001 tokens.
3. copied v12 EVW and copied experimental v13 EVW for migration.
4. one copy of the user's real EVW for final manual inspection; never the only
   copy.

## Scope-boundary assertions

For every search mode, test included and excluded sentinels:

| Operation | Required proof |
|---|---|
| FTS5 exact/prefix/phrase/fuzzy | excluded sentinel returns zero through public search API |
| Keyword expansion | fake server may return excluded term; scoped local FTS still returns zero |
| Message embedding | KNN partition returns active member even when excluded global vector is closer |
| Chunk embedding | every returned chunk boundary belongs to active member IDs |
| Date narrowing | active member outside selected date returns zero; date never broadens |
| Whole transcript | fake server asserts body and ordered IDs contain no excluded message |
| Exhaustive windows | union of every window ID equals the narrowed active membership exactly once, subject only to documented overlap |
| Retrieval hints | every lexical/vector hint belongs to active membership |
| Ledger synthesis | every source range/citation validates against frozen scope |
| Visible history | persisted turn records corpus ID, generation, hash, and only valid citations |

Also prove draft, building, stale, failed, wrong-content-revision, and wrong-index-
generation scopes all fail before search/network work.

## Server assertions

- Real subprocess starts with fake providers for tests and production startup
  rejects missing configuration.
- Server process opens no SQLite/EVW file and imports no client package.
- Client imports no server/provider/model SDK package.
- API version, operation capabilities, embedding metadata, request IDs, and
  scope metadata round-trip exactly.
- Embedding order/count/dimensions are exact for batches 1 and 32; 33 fails.
- Malformed model output, timeout, connection error, and oversize input are one
  visible failure with zero retry.
- Logs contain no fixture sentinel text, transcript, query, prompt, response,
  vector, key, or provider body.
- Built wheel contains server code and prompt-set v2 and no client UI/DB code.

## EVW assertions

- Schema version exactly 14 and strict schema validator passes.
- One dataset, at most one active corpus, active membership/index constraints,
  all foreign keys, `quick_check`, and `foreign_key_check` pass.
- Canonical migration counts and hashes match selected source data.
- Excluded development/secrets tables and settings are absent.
- Working membership contains no body/text duplication.
- 768,000 activates; 768,001 fails without changing current active corpus.
- A canonical change increments content revision, stales scopes, clears active,
  and blocks search.
- Second Python writer process fails immediately and visibly; Flutter read-only
  open remains allowed.
- Crash recovery preserves committed and excludes uncommitted writes.
- Clean close leaves no pending WAL frames; never manually delete WAL.

## Flutter assertions

- `flutter analyze` and `flutter test` pass.
- Windows release build passes.
- Viewer opens the migrated v14 copy, visibly shows full and active counts, and
  excludes `OUTSIDE_SCOPE_OMEGA` only in Active Search Corpus view.
- Thread/message pagination and UTF-8 rendering pass.
- Wrong schema and damaged integrity stop visibly.
- Viewer changes no EVW bytes and creates no meaningful WAL/SHM.
- `--probe --evw` reports every probe independently and exits 0.

## Python client assertions

Using a real fake-server subprocess and public workflow service/UI surfaces:

1. Open v14 and display Full Corpus vs Active Search Corpus.
2. FTS5 succeeds with server stopped.
3. Keyword expansion succeeds with server running and fails visibly when down.
4. Message and chunk embedding builds call server and write complete local
   partitions through the single writer.
5. Message and chunk embedding search call server only for the query vector and
   run KNN locally.
6. Whole-transcript and forced exhaustive conversational answers call only v2,
   present valid citations, and persist only visible history.
7. No provider, prompt, response, process-log, or secret data appears in EVW.
8. Search controls show and enforce the active corpus and optional narrowing.

## Required commands

The executor may segment during development, but final closeout runs all:

```powershell
python -m compileall -q message_evidence_workstation server
python -m pytest -q
python -m build
python scripts/verify_package_boundaries.py
python scripts/verify_evw_v14.py PATH_TO_MIGRATED_COPY
```

```powershell
cd flutter_client
flutter analyze
flutter test
flutter build windows --release
build\windows\x64\runner\Release\evw_client.exe --probe --evw PATH_TO_MIGRATED_COPY
```

No known red test, timeout, skipped in-scope test, or xfail is accepted. Fix the
chunk-calibration test/implementation and test-lifecycle leaks instead of
carrying them into closeout.

## Manual final walkthrough

1. Copy and migrate the real EVW to v14 with the explicit tool.
2. Record source/canonical counts, target counts, target/backup paths, and hashes.
3. Open target in Flutter; inspect full and active corpus and several threads.
4. Start configured server and verify health/capabilities.
5. Open target in Python client and run FTS5, embedding build, embedding KNN,
   keyword expansion, whole-transcript answer, and forced exhaustive answer.
6. Change to a limited corpus excluding a known thread/date and repeat all
   searches; verify no excluded hit/text/ID reaches UI or server test capture.
7. Stop server and verify only local lexical search remains operational.
8. Close Python cleanly, run integrity/WAL checks, reopen in Flutter, and verify
   visible conversation history/citations.

## Closeout report

`closeout_report.md` must contain ticket status, commit/diff identity, deleted
legacy files, schema/table inventory, migration evidence, full/active counts and
token totals, index partitions, endpoint/capability output, exact test commands
and results, Flutter screenshots or textual inspection evidence, WAL/lock
results, package-boundary scan, and any external live-provider test not run.
