# T15 — Chunk Embedding Index

## Goal

Build/rebuild conversation-chunk embeddings for source-thread message ranges using sqlite-vec.

## Dependencies

T14.

## Implementation Notes

Implement message-boundary-preserving chunking. Each chunk stores source_thread_id, start_message_id, end_message_id, message count, approximate token/char count, and text checksum. Use selected embedding model. Store vectors in sqlite-vec and metadata separately. Log chunk creation decisions and vector inserts.

## Files / Areas Likely Touched

- message_evidence_workstation/embeddings/chunking.py
- message_evidence_workstation/embeddings/index_jobs.py
- message_evidence_workstation/embeddings/sqlite_vec_backend.py
- message_evidence_workstation/db/schema.py
- tests/test_chunking.py
- tests/test_chunk_embedding_index.py

## Acceptance Criteria

- Chunking never splits a message body into partial records.
- Chunks preserve source message ID ranges.
- Settings action computes chunk embeddings.
- Chunk metadata and sqlite-vec vectors are stored.
- Build logs chunk count, chunk sizes, overlap policy, dimensions, timing, failures.
- Metadata status accurately reflects ready/failed/stale.

## Tests / Verification

- Unit test chunking boundaries.
- Fake adapter index build test.
- Manual small dataset build and inspect logs.

## Non-Goals

- No pink search UI yet.
- No cross-source-thread chunks.
