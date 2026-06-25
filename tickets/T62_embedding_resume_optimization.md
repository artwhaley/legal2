# T62 - Embedding Resume Optimization

## Goal
Optimize embedding index resume for large datasets without sacrificing correctness when batches interrupt, rows are missing, or embedding settings change.

## Background
`_embedded_message_ids` loads all embedded IDs into a Python set. Resume must work on 100k+ rows without huge RAM and must not skip holes. This ticket must land before T55 so the Load Dataset auto-embedding path does not launch donor datasets with the old 100k-ID set behavior.

**Spec reference:** `04_pre_scale_hardening_spec.md` Section 15

## Depends On
- T61 (batch logging during embedding)

## Scope
- Extend `embedding_index_metadata` or companion metadata with:
  - Provider/model ID, model revision if available, dimensions, distance metric, normalization mode.
  - Corpus/index generation or checksum inputs that distinguish stale indexes.
  - Batch completion state.
  - `last_embedded_message_sort_key` committed only after a successful batch.
- Fast-path resume query on deterministic ordering, preferably `(timestamp, sort_index, message_id)`.
- Before fast-path continue:
  - Verify no missing embeddings before checkpoint for active model/generation.
  - If holes exist, fill holes with an anti-join query before advancing past checkpoint.
- Chunk embeddings:
  - Track compatible chunk index metadata and `last_chunk_id` or deterministic chunk sort key.
  - Detect stale/missing chunks before fast-path continuation.
- Fallback:
  - Use set-based or anti-join resume when metadata is missing, stale, or incompatible with current model settings.
- Correctness cases:
  - Interrupt mid-batch.
  - Delete an embedded row.
  - Change embedding model settings; incompatible resume triggers full rebuild or safe hole-fill path.
- Expose a clean status/result object that T55 can report during auto-embedding.

## Guardrails
- Do not gut resume; re-embedding entire corpus on every launch is unacceptable for 100k datasets.
- Single embedding worker at a time; document in code comment or `docs/known_limitations.md`.
- Do not load all embedded IDs into RAM for the normal large-dataset resume path.

## Non-Goals
- New embedding providers.
- Load Dataset tab UI (T55).
- Changing vector schema beyond required metadata/index bookkeeping.

## Acceptance Criteria
- Interrupt 100k embed at approximately 60k; resume continues without re-embedding skipped rows.
- Resume does not load 100k IDs into RAM in the normal path (test or instrumentation note).
- Hole after checkpoint is detected and filled.
- Model/settings change invalidates stale checkpoint safely.
- T55 can call the optimized resume path for automatic message and chunk embedding.

## Tests
- Resume interrupted job test on medium fixture.
- Hole-detection test: delete row, resume fills it.
- Model settings change invalidates checkpoint test.
- Memory/instrumentation test or assertion proving normal resume avoids full embedded-ID set load.
- `python -m pytest -q`
