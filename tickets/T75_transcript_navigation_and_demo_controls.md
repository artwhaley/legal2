# T75 - Transcript Navigation And Demo Controls

## Goal
Implement the navigation API and the demonstrator controls needed to exercise deep-thread scrolling before search integration begins.

## Background
The new tab needs explicit proof that we can jump directly to deep ordinals and specific messages without relying on the old surface or on gradual scroll behavior.

**Spec reference:** `06_new_transcript_widget_spec.md` sections `Public API Required For Future Integration`, `Demo Tab Controls`

## Depends On
- T74

## Scope
- Implement:
  - `scroll_to_message(message_id)`
  - `scroll_to_ordinal(thread_ordinal)`
  - `focus_message(...)`
  - `viewport_center_message_id()`
  - `viewport_center_ordinal()`
- Add demo buttons:
  - `Jump 50`
  - `Jump 500`
  - `Persist / reload current thread` shell if not already present
- Update tab status text after demo actions
- Handle short threads gracefully by clamping to the last available message

## Guardrails
- Jump actions should resolve to document positions directly, not by simulated scroll stepping
- Keep the API names aligned with the future replacement contract
- Do not yet create evidence blocks in this ticket unless needed by a helper stub

## Non-Goals
- Overlay rendering
- Boundary editing
- Search integration

## Acceptance Criteria
- Jump 50 and Jump 500 land on the expected message or nearest valid fallback
- Focusing by message ID scrolls the document correctly
- Viewport-center helpers return stable values after navigation
- Persist/reload shell preserves the selected source thread

## Tests
- Add navigation tests on a synthetic thread with at least 600 messages
- Add a UI smoke test for jump-button behavior
- `python -m pytest tests/test_new_transcript_widget.py tests/test_ui_smoke.py -q`
