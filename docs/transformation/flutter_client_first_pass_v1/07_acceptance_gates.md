# Acceptance gates

## Automated gates

Run from `flutter_client`:

```powershell
dart format --output=none --set-exit-if-changed lib test
flutter analyze
flutter test
flutter build windows --release
```

Also run `git diff --check` and focused residue searches from repository root.

Automated tests must include:

- full in-memory v15 fixture with FTS, embedding, conversation, and printable
  tables;
- exact database persistence assertions;
- widget tests at large and constrained heights;
- deterministic fake HTTP JSON/NDJSON transport;
- no real external server/provider calls;
- no mass embedding calculation.

## Real-EVW disposable-copy gate

Use the existing known v15 fixture under `.tmp` or another repository-owned
test EVW. Copy the main EVW plus any required committed WAL state to a uniquely
named disposable target. Never open the source for writes.

Prove:

- open and explicit working-corpus selection;
- FTS result and transcript navigation;
- existing ready embedding index can execute a local vector lookup using a
  deterministic synthetic vector of matching geometry, without a provider
  call;
- exact range evidence create/read/edit/delete;
- print artifact create/edit/reorder/preview;
- 10,000+ message deep transcript jump remains bounded;
- clean close/checkpoint and lock release.

Remove the disposable `.evw`, `-wal`, `-shm`, and `.lock`.

## Fake-server end-to-end gate

Run a local deterministic fake implementing the exact current plan, embedding,
and conversational streams. Through the real Flutter gateway/coordinator prove:

- FTS and embedding Search pages;
- semantic planning and local candidate assembly;
- conversation progress and terminal answer;
- high/lower/unclassified range navigation;
- save range evidence;
- cancellation;
- malformed stream failure without partial persistence.

No production server code is changed to support this test.

## Windows manual smoke

Launch the release executable with a disposable EVW and optional
`--server-url` pointing to the fake server. Verify all five tabs and resize at
approximately 1200x800 and 900x650.

The executor may use widget/integration automation for interaction. It must not
make a paid live conversational or embedding call. A later human can point the
same executable at the configured real server.

## Pass criteria

- all five pages exist and only specified controls exist;
- Corpus opens/closes and explicitly selects a current ready corpus;
- FTS5 and embedding query search work in their proper boundaries;
- conversation coordinator exercises the exact server contract;
- every transcript shares evidence data but only active page drives center
  selection;
- range saves preserve complete exact ranges;
- print formatter persists and previews real artifacts;
- no source EVW mutation, leftover test files, locked database, or process;
- no test-only production branch, silent fallback, arbitrary result loss, or
  no-op control.

