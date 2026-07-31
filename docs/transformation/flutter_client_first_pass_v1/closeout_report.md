# Flutter Client First Pass V1 Closeout

Date: 2026-07-30

Status: FCFP1-000 through FCFP1-900 complete. The packet’s deterministic
client gates pass. The real-EVW Flutter test harness limitation is recorded
factually below rather than treated as a product pass.

## Ticket result

- FCFP1-000: baseline, inventory, contract review, and execution log — complete.
- FCFP1-100: one workspace owner and exactly five top-level pages — complete.
- FCFP1-200: shared transcript/evidence controller and active-page gating — complete.
- FCFP1-300: scoped FTS5 search with explicit pagination — complete.
- FCFP1-400: strict JSON/NDJSON gateway and local embedding search — complete.
- FCFP1-500: typed conversation coordinator, progress, cancellation, and visible-history persistence — complete.
- FCFP1-600: current-session conversation cards and exact range evidence — complete.
- FCFP1-700: printable artifact repository and native Document preview — complete.
- FCFP1-800: validation, cleanup, and residue checks — complete.
- FCFP1-900: final gates and handoff — complete with the documented real-EVW harness limitation.

## Main implementation

The Flutter client now has one `WorkspaceController`, one open v15 EVW, one
selected current-ready revision, one shared `TranscriptDocumentController`,
and one serialized remote-operation lease. The five pages are, in order:
Corpus, Search, Conversation, Transcript, and Print output.

Key implementation files are:

- `flutter_client/lib/main.dart`, `src/workspace_view.dart`,
  `src/workspace_controller.dart`, and `src/corpus_page.dart`;
- `src/evw_database.dart` and `src/evw_models.dart` for scoped search,
  evidence, conversation history, and printable artifacts;
- `src/server_gateway.dart`, `src/server_contracts.dart`,
  `src/search_workflow.dart`, and `src/conversation_workflow.dart`;
- `src/search_page.dart`, `src/conversation_page.dart`,
  `src/transcript_page.dart`, `src/transcript_editor.dart`, and
  `src/print_output_page.dart`;
- `test/conversation_workflow_test.dart`, `test/printable_artifact_test.dart`,
  `test/server_gateway_test.dart`, `test/transcript_editor_test.dart`, and
  `test/widget_test.dart`.

No Python, server, EVW schema, or migration source was changed for this stack.
The Windows CMake bundle now includes only the sqlite-vec extension required
by the implemented client path.

## Final automated gates

Run from `flutter_client`:

- Dart format check — PASS (`23 files`, `0 changed`);
- `flutter analyze` — PASS, no issues;
- `flutter test` — PASS, `17` tests;
- `flutter build windows --release` — PASS;
- release executable:
  `flutter_client/build/windows/x64/runner/Release/evw_client.exe`;
- scoped `git diff --check` — PASS;
- focused residue scan — PASS. The only intentional open calls are the
  workspace owner and the compatibility probe.

The 17-test suite covers no-selection startup and URL validation, FTS scope and
pagination, semantic multi-query embedding and local candidate assembly,
conversation none-mode payload/persistence/failure, printable lifecycle,
deterministic fake HTTP JSON/NDJSON transport, malformed sequence failure,
evidence editing, virtualization/deep jumps, and active-page viewport gating.
No live server, provider, or paid model call was made.

## Real-EVW proof and cleanup

A fresh disposable copy of the known v15 multicorpus fixture was opened by the
rebuilt Windows executable with `--probe --evw`; it exited `0`. The earlier
baseline copy also passed the probe. The named disposable EVWs, `.lock`
sidecars, and stale sidecars from the discarded first-copy attempt were then
removed explicitly. The final filesystem check found no FCFP1 disposable files.

After the final nested-result validator adjustment, a second fresh disposable
copy was probed by the final rebuilt executable and also exited `0`; it was
removed immediately after the check.

The opt-in Flutter real-EVW test harness was attempted against the verified
multicorpus copy and a smaller v15 debug fixture. Both attempts produced no
test output and exceeded their bounded timeouts while opening. This is the
same limitation recorded in FCFP1-000; the release probe passed, and the
in-memory/fake-HTTP feature proofs did not open or mutate a source EVW.

Final process check: no `evw_client`, `dart`, or `flutter` process remains.

## Operation map

Local operations are deterministic and scope-bound to the selected ready
revision and index generation:

- FTS5: Unicode terms, quoted AND query, explicit 100-row pagination;
- embedding search: one query embedding workload, geometry validation, local
  float32 sqlite-vec L2 lookup, no query-vector persistence;
- evidence: exact message membership, same-thread context, boundaries,
  highlighting, provenance, and shared-controller repaint;
- conversation history: one conversation/turn after a completed visible
  result, citations only for verified message IDs;
- document preview: persisted groups/artifacts/ordered evidence blocks and
  exact messages with context/relevant distinction.

Server operations are only the existing `/v1/conversational-plan`,
`/v1/embeddings`, and `/v1/conversational-analysis` routes. The client checks
request identity, content type, sequence, configuration identity, event shape,
terminal behavior, geometry, and completed-result structure. There are no
keyword-expansion calls, client retries, provider fallbacks, or client-side
windowing/synthesis.

## Human smoke steps

1. Launch the release executable with a disposable v15 EVW and optional
   `--server-url http://127.0.0.1:8710`.
2. Open the EVW on Corpus, explicitly select a current ready corpus, and
   inspect the revision/index statuses.
3. Exercise FTS5 and, when the revision reports a ready message embedding
   index, Embedding search; navigate and save one result as evidence.
4. Ask a question on Conversation against a configured local server; inspect
   progress, cancellation, warnings, every result class, range navigation, and
   range save.
5. Move across Transcript and Search to confirm shared evidence state, then
   create/edit/reorder an artifact on Document preview.
6. Close the EVW and confirm the lock is released. Do not point this smoke at
   a paid provider unless that is intentionally authorized later.

Full details and command history are in
[`execution_log.md`](./execution_log.md).
