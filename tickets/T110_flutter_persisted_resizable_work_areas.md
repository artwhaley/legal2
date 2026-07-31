# T110 - Flutter Persisted Resizable Work Areas

## Goal

Make the Flutter client's vertical sidebars and top/bottom work areas resizable at runtime, persist the user's sizes, and guarantee that no pane or divider can be resized out of reach.

## Depends On

T108 and T109.

## Files / Areas Likely Touched

- `flutter_client/lib/src/evw_database.dart`
- `flutter_client/lib/src/workspace_controller.dart`
- a small shared splitter widget under `flutter_client/lib/src/`
- `flutter_client/lib/src/transcript_editor.dart`
- `flutter_client/lib/src/corpus_page.dart`
- `flutter_client/lib/src/print_output_page.dart`
- `flutter_client/lib/src/search_page.dart`
- `flutter_client/lib/src/conversation_page.dart`
- Flutter widget tests

## Split Areas In Scope

Vertical side-by-side splits:

1. Evidence sidebar / transcript in `TranscriptEvidenceEditor` (shared by Transcript, Search, and Conversation).
2. Corpus list / selected revision details on Corpus.
3. Artifact list / document preview on Print output.

Horizontal top/bottom splits:

4. Search results / transcript on Search.
5. Conversation content (history plus composer) / transcript on Conversation.

No other page layout becomes resizable in this ticket.

## Shared Splitter Contract

Build one obvious reusable splitter implementation for vertical and horizontal orientation.

- Dragging updates pane size live.
- Persist only on drag end, not on every pointer event.
- Divider hit target is at least 10 logical pixels and always has a visible divider line.
- Use the correct resize mouse cursor.
- Neither pane may be collapsed.
- Clamp the primary pane to `primaryMinimum <= size <= available - divider - secondaryMinimum` on every layout.
- A saved size outside the current window's valid range is clamped for display but retained as the preference, so enlarging the window restores the user's chosen size.
- If available space is smaller than both minimums plus the divider, use the existing responsive stacked layout where one exists; otherwise use a scrollable fallback that gives each pane its minimum size. Never render an unreachable zero-size pane or divider.

Initial minimums:

| Split | Primary minimum | Secondary minimum |
|-------|----------------:|------------------:|
| Evidence sidebar / transcript | 280 | 420 |
| Corpus list / revision | 280 | 360 |
| Artifact list / preview | 240 | 420 |
| Search results / transcript | 160 | 280 |
| Conversation content / transcript | 220 | 280 |

Treat these as explicit product constants with tests, not scattered magic numbers.

## Persistence

Use schema-v15 `workspace_setting` through explicit `EvwDatabase` read/write methods. Store logical-pixel primary-pane sizes under separate documented keys:

- `flutter.split.transcript_evidence_sidebar`
- `flutter.split.corpus_list`
- `flutter.split.print_artifact_list`
- `flutter.split.search_results`
- `flutter.split.conversation_content`

The transcript-evidence sidebar preference is shared by all mounted TranscriptEvidenceEditor instances. Keep the live preference in `WorkspaceController` (or one equivalent shared notifier) so resizing it on one tab updates the other mounted tabs without reopen.

Validate persisted values as finite positive numbers. Invalid values fail visibly and use the documented initial size; do not silently rewrite corrupt stored values.

If a persistence write fails at drag end, surface the original error and restore the last successfully persisted size. Do not claim the resize was saved.

## Initial Sizes

Use the current layouts as initial values:

- evidence sidebar: 350;
- artifact list: 300;
- Corpus: current 5:6 proportion converted to pixels at first layout;
- Search results: current clamped 31% calculation;
- Conversation: current 3:4 proportion after the T109 chrome removal.

Do not add reset buttons or a settings screen.

## Guardrails

- No keyboard resize shortcuts.
- No double-click reset behavior.
- No hidden/collapsible panes.
- No persistence on every drag update.
- No schema migration and no external preferences dependency.
- Do not change page content or copy while adding splitters.

## Acceptance Criteria

- All five listed work areas resize with mouse drag at runtime.
- Each size persists across tab changes, EVW close/reopen, and application restart.
- Transcript sidebar width stays synchronized across Transcript, Search, and Conversation.
- Minimums prevent either pane or the divider from disappearing.
- Small-window fallback keeps every pane reachable.
- Out-of-range saved sizes clamp safely and restore when space returns.
- Failed persistence is visible and restores the last persisted layout.
- No unlisted layout becomes resizable.

## Tests

Add tests for both orientations, every persistence key, cross-tab transcript synchronization, minimum/maximum clamping, small-window fallback, corrupt stored values, and failed writes.

Run:

```powershell
cd flutter_client
flutter analyze
flutter test
```
