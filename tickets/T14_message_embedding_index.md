# T14 — Message Embedding Index

## Goal

Build/rebuild the message-level embedding index using the selected local embedding model and sqlite-vec.

## Dependencies

T12, T13, T02.

## Implementation Notes

Add Settings action to compute message embeddings for all messages in the current dataset. Batch embedding calls. Store vectors in sqlite-vec with associated message IDs. Update EmbeddingIndexMetadata with model, revision, dimensions, distance metric, normalization mode, backend, counts, timing, status, and last error. Log progress noisily.

## Files / Areas Likely Touched

- message_evidence_workstation/embeddings/index_jobs.py
- message_evidence_workstation/embeddings/sqlite_vec_backend.py
- message_evidence_workstation/ui/settings_tab.py
- message_evidence_workstation/db/repositories.py
- tests/test_message_embedding_index.py

## Acceptance Criteria

- User can start message embedding index job.
- Job logs model, dimensions, message count, batches, progress, failures, elapsed time.
- sqlite-vec row count matches embedded message count.
- Metadata status becomes ready on success and failed on failure.
- Index is marked stale when selected embedding model changes.
- No silent skip of failed messages unless each skip is logged with reason.

## Tests / Verification

- Use fake adapter to test index build.
- Test metadata ready/failed states.
- Manual small dataset embedding run.

## Non-Goals

- No chunk index.
- No purple search UI yet unless a debug query is trivial.
