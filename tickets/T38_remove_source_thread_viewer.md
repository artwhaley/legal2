# T38 - Remove Source Thread Viewer

## Goal
Remove the obsolete Source Thread Viewer tab and route source-thread navigation through the Transcript Widget instead.

## Background
The Source Thread Viewer is redundant with the Transcript Widget and no longer matches the product direction. This is a cleanup, not a temporary disable.

## Scope
- Remove the `Source Thread Viewer` tab from `MainWindow`.
- Remove `SourceThreadView` construction, imports, and tab registration.
- Route left-sidebar source-thread selection directly to `TranscriptWidgetTab.select_source_thread(...)`.
- Route conversational citation/source-thread navigation directly to the Transcript Widget.
- Remove manual-conversation handler plumbing that only exists for `SourceThreadView`.
- Delete `message_evidence_workstation/ui/source_thread_view.py` after all imports are gone.
- Remove obsolete tests/assertions that expect the Source Thread Viewer tab.

## Non-Goals
- Do not remove the Transcript Widget tab.
- Do not change evidence block behavior.
- Do not implement printable artifacts in this ticket.

## Acceptance Criteria
- The app has no visible Source Thread Viewer tab.
- No production code imports `SourceThreadView`.
- Selecting a source thread in the left sidebar opens/selects the Transcript Widget and loads that thread.
- Selecting an evidence block still opens/selects the Transcript Widget and centers the block.
- Full test suite passes.

## Tests
- Update main-window smoke test tab count and tab names.
- Add or update a smoke test proving source-thread selection calls/loads the Transcript Widget.
- Run full test suite.
