# T92 - Virtual Transcript Scroll And Jump

## Goal
Implement responsive virtual scrolling and public jump APIs.

## Background
Search and later workflows need reliable navigation into large transcripts without preloading the whole thread.

**Spec reference:** `08_virtual_transcript_widget_spec.md` sections `Performance Targets`, `Demo Tab`

## Depends On
- T91

## Scope
- Implement virtual scrollbar range based on total height
- Implement scroll event handling through the height index
- Implement `scroll_to_ordinal(ordinal)`
- Implement `scroll_to_message(message_id)`
- Preserve anchor position across resize
- Refine scroll position after measuring the target window
- Add bounded jump behavior for near-start, middle, and near-end targets

## Guardrails
- No full transcript hydration for jumps
- No full transcript measurement for jumps
- Do not persist scroll pixel positions as evidence state

## Non-Goals
- Search page integration
- Evidence editing

## Acceptance Criteria
- Jump to ordinal 50 works
- Jump to ordinal 500 works
- Jump to ordinal 14,000 works on a 15k-message dataset
- Jump to message id works for unloaded messages
- Scrollbar remains usable after deep jumps
- Resize preserves the current visible anchor approximately

## Tests
- Cover ordinal jumps near top/middle/end
- Cover message-id jump through SQL ordinal lookup
- Assert jumps fetch bounded ranges
- Add a scale smoke test for a 15k-message fake transcript

