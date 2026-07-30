# EWC15 Closeout Report

## Result

The v15 working-corpus restructure is executable and testable. One EVW holds
multiple named corpora and immutable revisions. Search and local embedding
state require an explicit revision scope. The server remains stateless and
EVW-blind.

## Verified

- `.tmp/sfv1-fixture-multicorpus-v15.evw` contains simultaneous 100K and 700K
  revisions with historical revisions preserved.
- FTS5, keyword expansion, local vector search, and conversational analysis
  use the selected revision. Conversational payloads use the server's exact
  `text` field.
- Local artifacts are keyed only by exact UTF-8 text SHA-256. Provider/model/
  profile identity is not persisted. Clear is explicit and preserves user and
  revision data.
- Sparse reuse was measured: 1,269 100K inputs; 10,530 distinct 700K inputs;
  1,269 reused during the 700K build; zero new inputs switching back.
- Flutter is read-only, does not auto-select a revision, and displays corpora,
  revisions, metadata, transcript pages, embedding coverage, and evidence.
- WAL startup recovery, serialized writes, short read transactions, clean
  checkpointing, quick-check, and foreign-key checks pass the tested paths.

## Commands and results

```text
python -m compileall -q message_evidence_workstation server tests scripts       PASS
python scripts\verify_package_boundaries.py                                  PASS
python -m pytest -q -m "not scale" --timeout=90                         84 passed
python -m pytest -q -m scale --timeout=240                                  2 passed
python scripts\verify_evw_v15.py .tmp\sfv1-fixture-multicorpus-v15.evw       PASS
python -m build                                                             PASS
cd flutter_client; flutter analyze                                           PASS
cd flutter_client; flutter test                                              PASS
cd flutter_client; flutter build windows --release                            PASS
evw_client.exe --probe --evw ..\.tmp\sfv1-fixture-multicorpus-v15.evw        PASS
git diff --check                                                            PASS
```

Authentication, payment, account persistence, and BYOK policy are not in this
phase. The server admin web page remains the configuration surface; the EVW
client does not configure server models. Existing embedding wire metadata is
transport-only.

## Manual smoke path

Open `.tmp\sfv1-fixture-multicorpus-v15.evw` in the Flutter viewer. Verify no
revision is selected initially, then select the 100K and 700K revisions and
inspect their counts and transcript. In the Python client, select each
revision explicitly and run FTS5, Keyword, Embedding, and Conversational
searches. Use the explicit clear action before rebuilding embeddings. The 100K
conversation should use whole-corpus behavior; the 700K conversation should
use windowed-ledger behavior; progress must show server events/windows.
