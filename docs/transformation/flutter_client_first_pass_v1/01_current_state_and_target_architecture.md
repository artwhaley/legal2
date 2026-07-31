# Current state and target architecture

## Read before editing

Inspect these files completely:

- `AGENTS.md`
- `flutter_client/lib/main.dart`
- every file under `flutter_client/lib/src`
- every file under `flutter_client/test`
- `flutter_client/pubspec.yaml`
- `message_evidence_workstation/client_api/gateway.py`
- `message_evidence_workstation/client_api/contracts.py`
- `message_evidence_workstation/services/client_workflows.py`
- `message_evidence_workstation/search/scoped_search.py`
- `message_evidence_workstation/db/schema.py`
- `message_evidence_workstation/db/printable_artifacts.py`
- `server/app.py` route definitions
- `server/contracts.py` public request/result models

The Python files are contract references and test-equipment history. Do not
edit them in this packet.

## Current Flutter state

At packet creation, Flutter has:

- v15 EVW opening, locking, WAL recovery/checkpoint, validation, and close;
- working-corpus and revision reads;
- virtualized variable-height transcript rendering;
- exact evidence-block persistence and editing;
- sticky center-line active evidence behavior;
- a single `WorkspaceView` that mixes corpus selection, transcript editing,
  and revision details;
- no Dart local search repository;
- no Dart server gateway or conversational workflow;
- no Flutter print-artifact repository or page.

Preserve these working behaviors. Refactor them; do not replace them with a
second implementation.

## Target object ownership

### `WorkspaceController`

Create one app-session controller, owned by `WorkspaceView`, that owns:

- current `EvwDatabase?`;
- path and open/close error;
- available `CorpusSummary` records;
- selected `CorpusSummary?`;
- resolved ready `RevisionSummary?`;
- one `TranscriptDocumentController?`;
- monotonically increasing evidence-data version;
- one explicit foreground remote-operation lease;
- server gateway configured at app startup.

It must provide explicit methods for open, close, refresh, select corpus,
begin/end remote operation, and report evidence mutation.

Opening another EVW closes the current EVW cleanly first. A failed new open
leaves no half-open database. Closing or switching corpus is refused with a
clear visible reason while a remote operation owns the lease. Do not
automatically cancel or silently abandon work.

Do not automatically select the first corpus after open. The user selects one
on the Corpus page. Selection resolves only the corpus's current revision.
Corpora with no current revision or a non-ready current revision remain listed
with an explicit unavailable status and cannot be selected for work.

### `TranscriptDocumentController`

Retain one shared evidence controller for the resolved revision. Refactor
`TranscriptEvidenceEditor` to accept the externally owned controller and never
dispose it. Each editor owns only its text fields, scroll key, and presentation
state.

Add an evidence mutation signal/version that advances only after successful
database writes or reloads, not on every boundary-drag preview. Pages that
display evidence-backed data use it to refresh.

### Main navigation

Replace the nested viewer tabs with one top-level five-tab shell in this exact
order:

`Corpus | Search | Conversation | Transcript | Print output`

Use a controlled `TabBar` plus `IndexedStack` so search results, current
conversation, and scroll positions survive tab changes. Do not use five
independent routes or reopen the EVW per page.

Pass `isPageActive` to pages containing a transcript. Extend
`VirtualTranscriptView` with `viewportActivationEnabled`. When false it may
render and respond to explicit scroll calls, but it must not reconcile the
shared active evidence block from its offstage viewport. When a page becomes
active, schedule one reconciliation from its real viewport.

### Server location

The client has no model/provider settings. Use:

- default server base URL `http://127.0.0.1:8710`;
- optional startup argument `--server-url URL`;
- validation requiring `http://` or `https://`;
- no environment-variable setup and no settings UI in this packet.

Keep `--evw PATH` and `--probe` working.

## Page prerequisites

Corpus is always usable. Every other page receives the shared workspace state.
If no EVW or no ready selected corpus exists, show one concise prerequisite
message directing the user to Corpus. Do not show nonfunctional page controls.

