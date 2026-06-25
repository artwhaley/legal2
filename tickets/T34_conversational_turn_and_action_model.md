# T34 - Conversational Turn And Result Action Model

## Goal
Introduce an explicit in-memory model for persistent conversational turns and clickable result actions.

## Background
The current conversational tab converts answer ranges into transient result-list entries. The new UI needs older answers to remain interactive after later questions, and future persistence should be straightforward.

## Scope
- Add conversational UI-local dataclasses or equivalent structures:
  - `ConversationTurn`
  - `AnswerRangeAction`
- Each `ConversationTurn` should contain:
  - user text
  - assistant summary
  - answer format
  - answer range actions
  - uncertainties
  - optional coverage summary
- Each `AnswerRangeAction` should contain:
  - stable action ID
  - title
  - summary
  - date description
  - display text
  - source thread ID
  - hit message ID
  - start message ID
  - end message ID
  - leading context start message ID
  - trailing context end message ID
- Add conversion helper from `ConversationalAnswerResult` to `ConversationTurn`.
- Keep derived context behavior: 3 messages before `start_message_id`, 3 messages after `end_message_id`, clamped to thread boundaries.

## Acceptance Criteria
- `ConversationalTab` maintains a list of turns, not just the most recent answer groups.
- Actions from older turns remain addressable by stable IDs.
- Conversion from parsed answer ranges preserves `summary`, `date_description`, and `display_text`.
- Conversion derives context boundaries consistently with current evidence block behavior.
- Existing parser compatibility with old responses is not broken.

## Tests
- Unit or UI tests create two answer results and verify both turns remain in memory.
- Tests verify action IDs are unique across turns.
- Tests verify context boundaries are derived as 3 before/after.
- Tests verify action labels choose:
  - detailed mode: range summary
  - brief mode: date description
  - fallback: title

