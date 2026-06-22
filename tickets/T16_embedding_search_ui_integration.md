# T16 — Embedding Search UI Integration

## Goal

Add purple message-vector and pink chunk-vector search toggles/results to Simple Search.

## Dependencies

T14, T15, T07.

## Implementation Notes

When the purple toggle is enabled, embed the query and search the message sqlite-vec index. When the pink toggle is enabled, search the chunk index and map chunks back to representative hit messages and message ranges. Vector results join the fusion/grouping system. Debug details should expose model, rank, distance, vector dimensions, message/chunk IDs, and snippets.

## Files / Areas Likely Touched

- message_evidence_workstation/ui/simple_search_tab.py
- message_evidence_workstation/search/fusion.py
- message_evidence_workstation/embeddings/sqlite_vec_backend.py
- message_evidence_workstation/embeddings/adapters.py
- tests/test_embedding_search_fusion.py

## Acceptance Criteria

- Purple toggle returns message embedding hits when ready index exists.
- Pink toggle returns chunk embedding hits when ready index exists.
- Missing/stale/failed index disables or explains the action clearly.
- Vector query logs query norm, top K requested/returned, raw distances, elapsed time.
- Results display distance/rank in debug detail.
- Duplicate messages fuse into one visible row with multiple badges.

## Tests / Verification

- Fake adapter/vector backend test for result conversion.
- Manual search after building indexes.
- Test stale index behavior.

## Non-Goals

- No conversational interface.
- No vector fallback.
