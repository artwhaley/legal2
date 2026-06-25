# T35 - Conversational Stream UI

## Goal
Replace redundant conversational panes with a single persistent conversation/results stream above the transcript widget.

## Target Layout
The conversational tab should have two main full-width vertical regions:

1. Top: persistent conversation/results stream.
2. Bottom: transcript widget.

The query input/send controls remain available.

## Remove Or Hide
- Separate answer text pane.
- Separate answer hits list.
- Separate coverage summary pane.
- Redundant standalone citations/list UI.

## Add
- `ConversationStreamWidget` or equivalent scrollable widget.
- Per-turn rendering:
  - `You:` plus user query.
  - `Assistant:` plus `answer_summary`.
  - one bullet row per result action.
  - uncertainties section when present.
- Result rows must be persistent widgets, not plain text.
- Result row tooltip must use `display_text`.

## Rendering Rules
- Never display full `answer` as the main UI text unless `answer_summary` is missing.
- Detailed mode bullet label: `summary`.
- Brief mode bullet label: `date_description` only.
- Fallback bullet label: `title`.
- Do not render raw message IDs in normal visible text.
- Coverage may remain in logs/debug only; do not show it as a separate main pane.

## Acceptance Criteria
- Conversational tab visually has a top stream and bottom transcript widget.
- Multiple user questions append multiple turns to the stream.
- Older result rows remain visible and interactive after later turns.
- The stream auto-scrolls to the newest turn after a new answer.
- Existing transcript widget remains functional in the bottom region.

## Tests
- UI smoke test asserts the old separate answer pane/hits list is gone or no longer primary.
- UI smoke test asserts stream contains user text, assistant summary, and one result row per answer range.
- UI smoke test appends two turns and verifies both remain rendered.
- UI smoke test verifies result row tooltip equals `display_text`.

