# T19 — Output Formatting View

## Goal

Build the Output Formatting tab shell that opens categorized workstation conversations and displays the full source thread with basic hit highlighting.

## Dependencies

T05, T08 or T18.

## Implementation Notes

The output view should list categories and workstation conversations, open a selected conversation, and render the entire source thread in a scroll view. Initially highlight stored hit messages as bold green. Prepare the UI layout for range handles, per-message overrides, preview, notes, and audit panel, but keep interactions minimal until T20.

## Files / Areas Likely Touched

- message_evidence_workstation/ui/output_formatting_tab.py
- message_evidence_workstation/ui/source_thread_view.py
- message_evidence_workstation/db/repositories.py

## Acceptance Criteria

- Output tab lists categories and workstation conversations.
- Selecting a workstation conversation displays the full source thread.
- Primary/stored hit messages render bold green.
- The view scrolls to the primary hit on open.
- Notes/status fields are visible or editable minimally.
- Open/render actions are logged.

## Tests / Verification

- Manual test with conversation created from search/category.
- Repository test fetching full output context.

## Non-Goals

- No NIM range suggestion yet.
- No draggable boundaries yet.
- No export preview yet.
