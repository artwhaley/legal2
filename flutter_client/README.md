# EVW Windows viewer

This is the read-only Flutter Windows client for EVW schema v15.

It opens a local `.evw`, validates SQLite integrity and the v15 schema, shows
multiple named corpus revisions and their metadata, and displays a selected revision transcript. It
does not write the EVW, call the model server, or implement search yet.

## Run

```powershell
flutter pub get
flutter run -d windows
```

Build the release executable, then run the compatibility probe directly for
native SQLite, FTS5, sqlite-vec, spellfix, file, and locking checks:

```powershell
flutter build windows --release
build\windows\x64\runner\Release\evw_client.exe `
  --probe `
  --evw C:\path\to\workspace.evw
```
