# EVW Flutter Windows client

This is the Flutter Windows client for EVW schema v15.

It opens a local `.evw`, validates SQLite integrity and the v15 schema, shows
named working corpora and their current ready revision metadata, and provides
five coordinated pages: Corpus, Search, Conversation, Transcript, and
Document preview. Search uses scoped local FTS5 or an already-ready local
sqlite-vec message index. Conversation planning, query embeddings, and
analysis use the configured server gateway with strict JSON/NDJSON validation.
Transcript, Conversation, and Search share one exact-message evidence
controller; Document preview reads and edits persisted printable artifacts.

The app takes the same exclusive `.evw.lock` used by the Python client, writes
through short SQLite transactions, and checkpoints WAL state on open and clean
close. Do not open the same EVW in both clients at once.

## Run

```powershell
flutter pub get
flutter run -d windows
```

Build the release executable, then run the compatibility probe directly for
native SQLite, FTS5, sqlite-vec, file, and locking checks:

```powershell
flutter build windows --release
build\windows\x64\runner\Release\evw_client.exe `
  --probe `
  --evw C:\path\to\workspace.evw
```
