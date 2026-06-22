# T20 — Range Suggestion and Highlight Overrides

## Goal

Add NIM range suggestion, four adjustable boundaries, and per-message highlight overrides to the Output Formatting tab.

## Dependencies

T19, T10.

## Implementation Notes

When a workstation conversation opens without a locked/user-modified range, call the Evidence/Conversation Range Suggestion prompt. Store suggested relevant/context boundaries. Add controls for lead-in start, relevant start, relevant end, and lead-out end. Controls can be draggable handles or explicit set-to-selected-message buttons for the first implementation, as long as the four boundary semantics are clear. User edits set `user_modified` and override AI.

## Files / Areas Likely Touched

- message_evidence_workstation/ui/output_formatting_tab.py
- message_evidence_workstation/nim/prompts.py
- message_evidence_workstation/db/repositories.py
- tests/test_ranges_highlights.py

## Acceptance Criteria

- Opening unranged conversation requests NIM range suggestion.
- Suggested lead-in/relevant/lead-out boundaries are stored.
- User can adjust all four boundaries.
- User can override individual message highlight state: none/hit/relevant/context.
- User changes persist and override AI suggestions on reload.
- Range suggestion call and user modifications are logged.

## Tests / Verification

- Mock range suggestion response.
- Unit test boundary persistence.
- Manual output view adjustment.

## Non-Goals

- No PDF export.
- No legal filing template.
