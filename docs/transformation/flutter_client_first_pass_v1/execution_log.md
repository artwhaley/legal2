# Flutter Client First Pass V1 Execution Log

Append one dated section per ticket. Record files changed, decisions applied,
commands run, exact results, residue checks, and remaining blockers. Do not
rewrite prior entries to hide failures.

## 2026-07-30 — FCFP1-000 baseline and inventory

Status: complete with a documented real-EVW test timeout; no source changes
were made for this ticket.

Baseline identity:

- branch: `main`
- HEAD: `f6dd034 (Mega migration)`
- baseline command: `git status --porcelain=v1`
- baseline status count: 4,994 entries (`D=4,955`, `M=26`, `??=13`). The
  worktree already contained extensive unrelated `.tmp` deletions and prior
  RPV/QPA/server changes. In-scope Flutter state already present at baseline
  included modified `flutter_client/README.md`, `pubspec.yaml`,
  `pubspec.lock`, and `test/widget_test.dart`, plus untracked `lib/` and
  `test/transcript_editor_test.dart`; these were preserved.
- packet files were already untracked at baseline; this log is the first
  FCFP1 packet edit.

Toolchain:

- Flutter version file: `3.32.2` (`flutter --version` itself timed out once;
  the SDK version file and all Flutter commands below were available).
- Dart: `Dart SDK version: 3.8.1 (stable)`.

Flutter source/test inventory read completely before editing:

- `lib/main.dart` (57 lines), `lib/src/compatibility_probe.dart` (27),
  `evw_database.dart` (973), `evw_models.dart` (172),
  `native_extensions.dart` (54), `transcript_editor.dart` (1,195),
  `transcript_height_index.dart` (102), and `workspace_view.dart` (317).
- `test/transcript_editor_test.dart` (500 lines) and `test/widget_test.dart`
  (30 lines).
- `pubspec.yaml` and existing dependency set: Flutter, `sqlite3`,
  `file_selector`, and `crypto`; no new dependency was added.

Contract/schema references read completely:

- `message_evidence_workstation/client_api/gateway.py`;
  `client_api/contracts.py`;
  `services/client_workflows.py`;
  `search/scoped_search.py`;
  `db/schema.py`; and `db/printable_artifacts.py`.
- Server route definitions in `server/app.py` for `/v1/keyword-expansion`,
  `/v1/conversational-plan`, `/v1/conversational-analysis`, and
  `/v1/embeddings`.
- Complete public request/result and NDJSON model definitions in
  `server/contracts.py`.

Baseline commands and results from `flutter_client`:

- `flutter analyze` — PASS, no issues.
- `flutter test` — PASS, 8 tests.
- `flutter build windows --release` — PASS; produced
  `build/windows/x64/runner/Release/evw_client.exe`.

Real-v15 disposable-copy baseline:

- A disposable copy was created at
  `.tmp/fcfp1-000-baseline-multicorpus-20260730T000000Z.evw` from the known
  v15 multicorpus fixture. The source fixture was not opened for writes.
- Release executable `--probe --evw <disposable>` — PASS, process exit 0;
  the probe opened, validated, read, and closed the EVW.
- The opt-in `EVW_TRANSCRIPT_TEST_PATH` real-EVW suite timed out without test
  output at 300 seconds. The focused `real v15 EVW evidence round trip` test
  also timed out at 120 seconds against the verified copy. This is recorded
  as a pre-existing baseline limitation for diagnosis; it did not block safe
  implementation because the release probe passed and the in-memory suite
  was green. The disposable copy remains for controlled cleanup in FCFP1-900.

FCFP1-000 acceptance: execution log exists, baseline is recorded, and no
Flutter/Python/server/schema source was modified by this ticket.

## 2026-07-30 — FCFP1-100 through FCFP1-400 implementation and gates

Status: complete.

Implemented the single-process workspace owner and exact five-tab shell,
startup `--server-url` validation, explicit current-ready-revision selection,
clean EVW open/close ownership, shared external transcript/evidence-controller
ownership, active-page viewport gating, scoped FTS5 pagination, typed gateway
contracts, strict JSON/NDJSON transport, request cancellation, embedding
geometry checks, and local sqlite-vec query lookup. Search has FTS5 and
Embedding modes, explicit Load more pagination, View in transcript, and
hit-centered evidence creation with provenance.

Primary files: `flutter_client/lib/main.dart`, `lib/src/workspace_controller.dart`,
`workspace_view.dart`, `corpus_page.dart`, `search_page.dart`,
`transcript_page.dart`, `transcript_editor.dart`, `evw_models.dart`,
`evw_database.dart`, `server_contracts.dart`, `server_gateway.dart`, and
`search_workflow.dart`.

Gates:

- direct Dart format — PASS;
- `flutter analyze` — PASS, no issues;
- `flutter test` — PASS, initially 10 tests and later 16 tests after the
  integration proofs were added;
- no keyword-expansion endpoint/control, independent page database open,
  duplicate evidence-controller ownership, or unscoped FTS/vector query was
  found in the production Flutter path.

## 2026-07-30 — FCFP1-500 and FCFP1-600

Status: complete.

Added `ConversationWorkflow` with a foreground workspace lease, frozen
revision/generation/scope snapshot, planner-none and semantic-range paths,
one embedding workload for every planner query, local candidate assembly,
complete ordinal transcript payloads, streamed progress, cancellation,
strict terminal-result validation, complete/raw/partial/unavailable rendering,
and visible-history-only persistence. Added exact conversational range
creation with same-thread/order/membership validation, lower-median core,
three-message context bounds, and sole-core highlighting.

The Conversation page keeps current-session question/assistant cards, exposes
elapsed phase/progress and Cancel, renders complete server result data and
warnings, makes canonical ranges navigable/saveable only when verified, and
uses the shared transcript/evidence editor.

Tests cover planner none mode, full transcript/context persistence, failure
lease release, no incomplete history, result-contract validation, exact range
save behavior, and two mounted transcript views where only the active view may
hand off center-line evidence activation.

## 2026-07-30 — FCFP1-700

Status: complete.

Added typed printable group/artifact/document models and database operations
for lazy default-group creation, artifact creation from evidence, metadata
round trip, append with duplicate rejection, contiguous reorder, removal, and
ordered exact-message document loading. The Print output tab is a native
Document preview with metadata editing, block controls, and context/relevant
visual distinction; it has no Print, PDF, or Export control.

`printable_artifact_test.dart` proves lazy group creation, exact message order,
metadata, duplicate rejection, reorder, removal, and relevant classification.

## 2026-07-30 — FCFP1-800 integration and residue checks

Status: complete with real-EVW harness limitation carried forward from
FCFP1-000.

Extended open-time v15 shape validation for all tables/columns used by search,
conversation persistence, evidence, and printable artifacts. Removed the
unused spellfix loader and Windows bundle entry; no spellfix or keyword path is
required by this client. Updated the Flutter README for the completed five
pages. Every touched user-facing string was checked for mojibake.

Deterministic local fake HTTP tests exercise request IDs, JSON/NDJSON content
types, embedding accepted/vector/completed events, and non-increasing stream
sequence rejection. No real server/provider call was made.

## 2026-07-30 — FCFP1-900 proof status before closeout

Current standard gates:

- `dart format --output=none --set-exit-if-changed lib test` — PASS;
- `flutter analyze` — PASS, no issues;
- `flutter test` — PASS, 17 tests;
- `flutter build windows --release` — PASS; release executable exists at
  `flutter_client/build/windows/x64/runner/Release/evw_client.exe`.

Real-v15 disposable proof:

- the uniquely named copy
  `.tmp/fcfp1-000-baseline-multicorpus-20260730T000000Z.evw` is a verified v15
  multicorpus copy with ready revisions and local FTS/embedding artifacts;
- the current release executable compatibility probe opens and closes that
  copy successfully (exit code 0);
- the opt-in Flutter real-EVW test harness was attempted against both the
  verified multicorpus copy and the smaller debug fixture, but produced no
  test output and exceeded its bounded timeout while opening. This is the
  same harness limitation recorded at FCFP1-000; it is not being reported as
  a product pass. The release probe remains the successful real-EVW proof.

The disposable target remains until the final cleanup step. No Flutter
process, release client, fake server, or provider process is intentionally
left running.

Final cleanup and residue result:

- the exact disposable target and its existing `.lock` sidecar were removed;
  no `-wal` or `-shm` sidecar existed at cleanup time;
- no `evw_client`, `dart`, or `flutter` process remains;
- `git diff --check -- flutter_client docs/transformation/flutter_client_first_pass_v1` — PASS;
- focused residue scan found only the intentional workspace-owner open path
  and the compatibility-probe open path; no independent page opens,
  keyword-expansion call/control, spellfix loader, placeholder/no-op page,
  PDF/export claim, or unscoped search SQL remains.

FCFP1-900 acceptance is complete with the real-EVW Flutter-harness timeout
explicitly retained as a limitation; the release compatibility probe and all
deterministic in-memory/fake-HTTP gates passed.

Final post-build proof:

- a fresh `.tmp/fcfp1-900-final-multicorpus-20260730T000000Z.evw` copy was
  probed by the rebuilt Windows executable — PASS, exit code 0;
- that copy, its `.lock` sidecar, and the two stale sidecars from the earlier
  discarded baseline-copy attempt were removed;
- final check: no FCFP1 disposable files and no `evw_client`, `dart`, or
  `flutter` process remain.
- after the final nested-result validator adjustment, a second fresh
  `.tmp/fcfp1-900-final2-multicorpus-20260730T000000Z.evw` copy was probed by
  the final rebuilt executable — PASS, exit code 0 — and removed immediately.
