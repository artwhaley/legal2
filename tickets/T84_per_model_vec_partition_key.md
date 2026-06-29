# T84 - Per-Model Vec Partition Key

## Goal
Persist embedding vectors per model in the workspace `.evw` file so switching models and switching back does not force redundant recomputation (when dimensions match).

## Background
Today `embedding_index_metadata` is per-model but `message_embedding_vec` / `chunk_embedding_vec` are shared. Switching models can overwrite or leave stale vectors while metadata claims ready/wrong model.

**Spec reference:** `07_home_startup_and_embeddings_spec.md` Section 4

## Depends On
- T83 (embedding pipeline uses vec tables during load)

## Scope
- **Migration** in `db/migrations.py`:
  - Read existing vec rows + model name from `embedding_index_metadata`.
  - DROP and recreate vec tables with `model_name text partition key`.
  - Re-insert existing vectors tagged with model from metadata.
- **`sqlite_vec_backend.py`:**
  - Update `ensure_message_vec_table` / `ensure_chunk_vec_table` DDL.
  - Update `insert_message_vectors` / `insert_chunk_vectors` to include `model_name`.
  - Update KNN search queries: `WHERE model_name = ?` (partition filter).
  - Update `clear_*` helpers to optionally scope by model.
  - Update COUNT queries to filter by `model_name`.
- **`index_jobs.py`:** pass active `model_name` through all insert/count/search paths.
- **`chunking.py`:** `load_message_vector_map` / `message_vector_count` filter by model.
- **`mark_indexes_stale_for_model_change`:** mark metadata stale only; do not delete other models' vector rows.
- Document in `docs/known_limitations.md`: per-model persistence requires same vector dimensions; dimension change drops/recreates vec table.

## Guardrails
- sqlite-vec >= 0.1.6 already in `pyproject.toml` — partition keys supported.
- Virtual tables cannot ALTER — full recreate required.
- Do not break existing resume/checkpoint logic.

## Non-Goals
- Separate tables per dimension count
- Separate embedding database file

## Acceptance Criteria
- Build embeddings for model A; switch to model B and build; switch back to A — search works without rebuild (same dimensions).
- KNN queries only scan active model's partition.
- Metadata stale for inactive model does not delete that model's vectors.
- Migration preserves existing vectors under correct model name.

## Tests
- `tests/test_per_model_embedding_cache.py` (new)
- Update `tests/test_message_embedding_index.py`, `tests/test_chunk_embedding_index.py`, `tests/test_schema.py`
- `python -m pytest tests/test_message_embedding_index.py tests/test_chunk_embedding_index.py tests/test_schema.py -q`
