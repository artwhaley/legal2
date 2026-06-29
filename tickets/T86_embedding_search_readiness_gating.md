# T86 - Embedding Search Readiness Gating

## Goal
Prevent users from selecting embedding search modes before indexes are ready, and warn on Conversational tab while message embeddings are still building.

## Background
Today Simple Search shows all four modes always enabled; embedding search fails at runtime with an error in the status label. Users need proactive gating with clear explanation.

**Spec reference:** `07_home_startup_and_embeddings_spec.md` Section 5 (gating portion)

## Depends On
- T85 (`AppContext.embedding_state` or equivalent signal)

## Scope
- **`simple_search_tab.py`:**
  - Disable `message_embedding` combo item when `message_ready` is false.
  - Disable `chunk_embedding` combo item when `chunk_ready` is false.
  - Tooltip on disabled items: e.g. `"Message embeddings still building (10432/15139) — available when complete"`.
  - Refresh gating when embedding state changes (connect to controller signal or poll on tab show).
- **`conversational_tab.py`:**
  - Persistent warning banner (QLabel) while `message_progress < message_total` or `not message_ready`:
    > Conversational interface relies on message embeddings for thoroughness verification on some searches. Responses may be degraded until embeddings are completely calculated.
  - Hide banner when message embeddings ready.
- Ensure auto-build path in conversational tab (`_ensure_message_embeddings_then`) does not fight Home background embed (no duplicate concurrent builds for same index).

## Guardrails
- FTS5 and expanded_keyword modes always enabled after dataset load.
- Disabled combo items must remain visible (greyed), not hidden.
- Do not block conversational queries entirely — warn only.

## Non-Goals
- Chunk embedding requirement for conversational (message only for banner)
- Settings manual rebuild UX changes

## Acceptance Criteria
- Before message embeddings ready: message embedding mode disabled with explanatory tooltip.
- Before chunk embeddings ready: chunk embedding mode disabled with explanatory tooltip.
- Both modes enable automatically when corresponding index reaches ready.
- Conversational banner visible during message embed build; hidden when ready.
- No duplicate embedding build jobs when Home pipeline already building.

## Tests
- UI smoke or unit test for combo item enabled/disabled state
- Test banner visibility tied to embedding_state
- `python -m pytest tests/test_ui_smoke.py -q`
