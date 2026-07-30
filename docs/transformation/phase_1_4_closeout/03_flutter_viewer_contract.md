# Flutter v14 Viewer Contract

## Purpose

Turn the current probe-only executable into the first real, intentionally small
Flutter client surface. It proves that a transformed v14 EVW is understandable
and viewable without Python. It remains read-only in this phase.

## Invocation

```text
evw_client.exe                         open viewer, no file selected
evw_client.exe --evw C:\path\x.evw    open viewer with file
evw_client.exe --probe                 run synthetic compatibility probe, exit
evw_client.exe --probe --evw PATH      run probe plus real-v14 inspection, exit
```

Viewer mode never exits after probing. Probe mode never opens the product UI
and returns 0 only when every check passes.

## Lean UI

Implement one window with:

- Open EVW and Refresh buttons;
- workspace filename/display name, schema version, integrity status, and
  read-only status;
- canonical Full Corpus summary: thread/message/date counts;
- Active Search Corpus summary: name, selection, message count, token count,
  768,000-token limit, membership/index status, generation, and last error;
- a two-choice view selector: `Full Corpus` and `Active Search Corpus`;
- source-thread list for the selected view;
- paged transcript for the selected thread.

The active view joins `working_corpus_message`; it must not merely filter a
previous full-corpus list in memory. If no active ready corpus exists, show the
stored reason and no active-view messages. Full-corpus viewing remains
available because viewing canonical data is not a search.

Use an explicit Refresh button; do not add background polling, navigation,
state-management frameworks, ORM/code generation, design systems, search,
editing, evidence controls, server calls, or fake screens.

## Data access

- Open with SQLite URI `mode=ro` and `query_only=ON`.
- Require schema version 14; reject older/newer versions visibly.
- Run `quick_check` and `foreign_key_check` before showing data.
- Load sqlite-vec/spellfix only in probe mode; the viewer does not need native
  extensions to read canonical tables.
- Page thread and message reads; do not load the corpus into memory.
- Close the old database before opening another.
- Never create a WAL, change pragmas that write, or mutate workspace state.

Use the official Windows `file_selector` plugin for Open EVW. Keep handwritten
Dart limited to these files and responsibilities:

```text
main.dart                 mode parsing and app/probe entry
src/evw_database.dart     read-only SQL and paging
src/evw_models.dart       immutable view records
src/workspace_view.dart   one viewer screen
src/compatibility_probe.dart
src/native_extensions.dart
```

Do not split widgets into one-file-per-control structures.

## Flutter tests

- database tests against a generated v14 fixture;
- widget test proving full vs active counts and excluded messages;
- wrong-schema and integrity failure presentation;
- pagination and UTF-8 transcript rendering;
- no-write test comparing EVW/WAL/SHM state before and after viewer use;
- release probe against synthetic fixtures and a migrated v14 copy.
