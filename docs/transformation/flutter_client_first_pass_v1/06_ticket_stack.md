# Ticket stack

Execute in order. Do not begin a dependent ticket before its gates pass.

## FCFP1-000 — Baseline and inventory

Record:

- branch/commit and full dirty status;
- Flutter/Dart versions;
- current source/test file inventory;
- current `flutter analyze`, `flutter test`, and Windows release-build results;
- current real-v15 disposable-copy transcript smoke result;
- exact server contract files and schema tables inspected.

Do not “fix” unrelated baseline failures. Attribute them and stop only if they
prevent safe work.

Acceptance:

- `execution_log.md` exists with baseline;
- no source modifications in this ticket.

## FCFP1-100 — Workspace ownership and five-page shell

Implement `WorkspaceController`, startup server URL parsing, five top-level
tabs, controlled `IndexedStack`, Corpus page, prerequisite states, clean
open/close, and current-ready-revision selection.

Refactor current mixed `WorkspaceView`; do not retain nested duplicate
navigation. Add close refusal during an operation lease.

Tests:

- no automatic corpus selection;
- selecting a working corpus resolves only its current ready revision;
- unavailable corpus cannot become work scope;
- close clears all shared state and releases lock;
- tab state survives navigation;
- invalid server URL fails startup clearly.

## FCFP1-200 — Shared transcript/evidence controller

Refactor `TranscriptEvidenceEditor` for external controller ownership. Add
active-page viewport gating and persisted evidence mutation version. Build the
full Transcript page.

Tests:

- three editor instances observe one created/edited/hidden block;
- offstage view cannot steal center-line activation;
- newly active view reconciles once;
- controller disposed exactly once on close/scope change;
- prior transcript virtualization/boundary tests remain green.

## FCFP1-300 — Scoped FTS5 and Search page

Add typed local search models/repository and the three-zone Search page. Add
message display fields, explicit 100-row pagination, result navigation, and
hit-centered evidence creation with creator provenance.

Tests:

- search is revision/generation scoped;
- query escaping/empty query;
- deterministic ordering;
- all pages reachable through Load more;
- click scrolls the page's transcript;
- save creates exact one-message relevant plus same-thread context;
- no keyword endpoint call or keyword control exists.

## FCFP1-400 — Gateway and query embedding search

Implement strict Dart gateway, NDJSON parser, cancellation, embedding geometry,
one-query embedding workflow, sqlite-vec local lookup, and Embedding mode UI.

Use deterministic local fake HTTP servers for automated transport tests.

Tests:

- request IDs, content type, sequence/config identity, terminal rules;
- structured HTTP errors;
- malformed/truncated stream fails noisily;
- cancellation closes only the owning request;
- geometry mismatch, duplicate/missing vector, nonfinite vector;
- vector result is constrained to selected revision;
- top-k shown and enforced;
- query vector is not persisted;
- operation lease always releases.

## FCFP1-500 — Conversational coordinator and typed results

Port planning, semantic retrieval preparation, complete corpus payload,
analysis streaming, progress, cancellation, strict terminal result parsing,
and visible-history persistence.

Do not port server decisions into Dart.

Tests:

- planner none mode makes no embedding call;
- semantic mode embeds every planner query and performs local candidate lookup;
- frozen analysis context is sent unchanged;
- every selected message is sent once in ordinal order;
- progress covers retry, heartbeat, unavailable window, synthesis, warning,
  completion, cancellation, and failure;
- complete, complete-with-warnings, partial, raw, and synthesis-unavailable
  outcomes remain returned;
- no provider internals are persisted;
- cancelled/failed request does not create completed history.

## FCFP1-600 — Conversation page and range evidence

Implement the two-zone Conversation page, current-session question/assistant
cards, complete result rendering, verified range navigation, and exact range
evidence creation.

Tests:

- high/lower divider and all result classes render;
- unknown IDs have no navigation/save callback;
- verified range view targets median;
- save includes full relevant range and up to three same-thread context
  messages each side;
- core is lower median and sole initial highlight;
- invalid/cross-thread/missing range writes nothing;
- evidence created here appears immediately in Search and Transcript editors;
- elapsed timer stops only on terminal/cancel/failure.

## FCFP1-700 — Functional print-output first pass

Implement typed print repository and limited Print output page. Use existing
tables and native Flutter document preview.

Tests:

- explicit first artifact creation creates default group only then;
- dataset ownership checks;
- metadata round trip;
- append rejects new duplicate;
- up/down reorder persists contiguous order;
- remove persists;
- preview contains every exact attached message in order;
- relevant/context distinction renders;
- evidence edits refresh preview;
- no Print/PDF/export control exists.

## FCFP1-800 — Integration, cleanup, and residue removal

Remove obsolete mixed-view code and duplicate state. Extend EVW validation and
test fixtures. Fix all touched user-facing mojibake. Verify resource disposal,
operation-lease behavior, and empty/prerequisite states.

Run residue searches for:

- Flutter keyword expansion calls or controls;
- independent per-page `EvwDatabase.open`;
- independent per-page `TranscriptDocumentController`;
- placeholder/no-op buttons;
- server/provider/model/prompt settings in Flutter;
- unscoped FTS/vector SQL;
- fabricated-ID navigation;
- Print/PDF/export claims.

## FCFP1-900 — Final proof and handoff

Run every gate in `07_acceptance_gates.md`, create `closeout_report.md`, and
leave the rebuilt Windows executable stopped unless the packet's manual smoke
requires it. Clean disposable files and confirm no Flutter or server process
remains.

The closeout report includes:

- ticket status;
- changed files and why;
- exact commands/results/test totals;
- final page and ownership inventory;
- final local/server operation map;
- proof of shared evidence behavior;
- proof of no paid calls;
- disposable EVW cleanup;
- factual limitations and concise human manual-test steps.

