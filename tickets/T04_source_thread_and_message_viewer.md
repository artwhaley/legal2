# T04 — Source Thread and Message Viewer

## Goal

Connect loaded dataset data to the sidebar source-thread selector and implement a source-thread message viewer.

## Dependencies

T02, T03.

## Implementation Notes

At startup, open/select a workspace DB and populate source threads. Selecting a source thread should show the full message stream in chronological order in the right-side viewing area or a reusable widget. This widget will later be reused by Output Formatting. Show sender, timestamp, body, attachment summary if present, and message ID in debug detail.

## Files / Areas Likely Touched

- message_evidence_workstation/ui/sidebar.py
- message_evidence_workstation/ui/source_thread_view.py
- message_evidence_workstation/db/repositories.py

## Acceptance Criteria

- Loaded source threads appear in the top sidebar area.
- Selecting a source thread displays its messages in order.
- Empty dataset state is understandable.
- Viewer handles long threads with a scroll view.
- Selection/load actions are logged.

## Tests / Verification

- Manual test with sample dataset.
- Repository test for fetching threads/messages.
- Verify a thread with many messages remains scrollable.

## Non-Goals

- No category drag/drop yet.
- No search highlighting yet.
- No output boundary handles yet.
