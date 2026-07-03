# T101 - Embedding Search Date Range

## Goal

Make message and chunk embedding search respect the selected date range before final top-K results are chosen.

## Dependencies

T99, T100.

## Implementation Notes

This ticket closes the main correctness gap for scoped simple search: vector candidates must be date-scoped before the final ranked results are returned.

Wire date scope through:

- embedding worker job spec
- `search_message_embeddings`
- `search_chunk_embeddings`
- sqlite-vec backend helpers as needed

Decisions:

- Date scope applies before final top-K return.
- Oversampling is allowed, but it must be explicit and logged.
- Chunk scope uses **range intersection**, not chunk-start-only checks.
- If not enough in-scope candidates are found, return fewer hits rather than silently broadening scope.

Implementation should prefer one explicit oversample-and-filter path over hidden alternative behaviors.

## Files / Areas Likely Touched

- `message_evidence_workstation/ui/embedding_worker.py`
- `message_evidence_workstation/search/embedding_search.py`
- `message_evidence_workstation/embeddings/sqlite_vec_backend.py`
- `tests/test_embedding_search_fusion.py`
- `tests/test_search_worker.py`
- any existing embedding-search-specific test file if present

## Acceptance Criteria

- Message embedding search returns only in-range hits.
- Chunk embedding search returns only hits whose chunk range intersects the selected date scope.
- Out-of-range high-similarity hits do not suppress valid in-range hits from the final returned list.
- Embedding search logs include active scope and candidate filtering behavior.
- No silent fallback to unscoped embeddings occurs.

## Tests / Verification

- Add tests for:
  - message embedding scope
  - chunk intersection scope
  - oversample/filter behavior preserving in-range hits
  - fewer-than-top-k return when scoped candidates are scarce
- Run:
  - `python -m pytest tests/test_embedding_search_fusion.py tests/test_search_worker.py -q`

## Non-Goals

- No conversational search changes yet.
