# T85 - Embedding Progress Status Bar

## Goal
Show live message and chunk embedding progress in a global status bar and expose embedding readiness state to tabs.

## Background
Users need continuous feedback during long embedding builds (~15k messages can take most of an hour). Progress today is buried in Settings label or Load tab log.

**Spec reference:** `07_home_startup_and_embeddings_spec.md` Section 5 (status bar portion)

## Depends On
- T83 (background embedding emits batch progress)

## Scope
- **`main_window.py`:** add `QStatusBar`; permanent bottom-of-window progress area.
- New **`EmbeddingProgressController`** (or equivalent in `ui/`):
  - Subscribe to process log bus: `message_batch_progress`, `chunk_batch_progress`.
  - Display: `Message embeddings: N / M | Chunk embeddings: X / Y`.
  - Show "Embeddings ready" when both indexes `status=ready` for active model.
  - Clear or update on model change / dataset unload.
- **`AppContext`:** add `embedding_state` dataclass:
  - `message_ready`, `chunk_ready`
  - `message_progress`, `message_total`, `chunk_progress`, `chunk_total`
  - Update controller pushes changes; tabs can subscribe or poll on show.
- Wire controller start/stop to dataset load, embed job lifecycle, Settings model change.

## Guardrails
- Status bar updates must be lightweight (parse log details JSON; no DB scans on UI thread per batch).
- Do not block UI on progress refresh.

## Non-Goals
- Search mode gating (T86)
- ETA / rate display (optional future enhancement)

## Acceptance Criteria
- During embedding build, status bar updates on each batch (~every 32 messages).
- After both indexes ready, status bar shows ready state.
- `AppContext.embedding_state` reflects current progress for active dataset + model.
- Progress clears/resets appropriately on new load or model change.

## Tests
- Unit test for controller parsing log entries into state
- UI smoke: status bar visible during mocked embed progress
- `python -m pytest tests/test_process_log_batch.py -q` (if applicable)
