# T36 - Conversational Result Navigation And Evidence Block Creation

## Goal
Make each result row in the conversation stream interactive.

## Required Interactions
Left click:
- Load the result's source thread into the bottom transcript widget.
- Focus/center the transcript on `hit_message_id`.

Double click:
- Create an evidence block from the result.
- Use `hit_message_id` as the core message.
- Use `start_message_id` and `end_message_id` as the relevant range.
- Use derived 3-before/3-after context boundaries.
- Highlight `hit_message_id`.
- Refresh sidebar/categories.

Hover:
- Show `display_text` as tooltip.

## Scope
- Wire click/double-click handlers for stream result rows.
- Reuse `EvidenceBlockTranscriptWidget.create_evidence_block_for_answer_range`.
- Preserve interaction for older turns.
- Ensure result actions do not depend on the most recent answer only.

## Optional Scope
- Preserve drag-to-sidebar support if cheap, using existing `MIME_SEARCH_RESULT` payloads.
- If drag support complicates the stream widgets, defer it.

## Acceptance Criteria
- Clicking a result from the newest turn focuses the transcript on the correct hit message.
- Clicking a result from an older turn still focuses the correct hit message.
- Double-clicking a result from any turn creates one evidence block.
- Created evidence block has:
  - core hit = `hit_message_id`
  - relevant range = returned start/end
  - context range = derived 3-before/3-after
  - highlight = `hit_message_id`
- Sidebar refreshes/reveals created block where appropriate.

## Tests
- UI test appends two turns, clicks a result in the first turn, and verifies transcript source thread/hit focus.
- UI test double-clicks a result in the first turn and verifies evidence block slots.
- UI test double-clicks a result in the second turn and verifies evidence block slots.
- Test verifies category refresh handler is called after creation.

