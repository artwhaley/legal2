# V15 Schema, Embedding, and Evidence Contract

## Version policy

Set `SCHEMA_VERSION = 15`. Fresh files are v15. Python and Flutter runtime open
only v15 and reject every other version without mutation. Conversion is an
explicit compact-copy operation described in file 03.

## Canonical message hash

Add:

```text
message.embedding_input_hash TEXT NOT NULL
```

It is lowercase SHA-256 hex of the exact UTF-8 bytes sent as the message
embedding input. Those bytes are the stored `message.body` with no trim,
normalization, sender, timestamp, or metadata. Import/migration computes and
validates it.

Changing `message.body` must update this hash and increment
`dataset.content_revision` in the same transaction.

## Canonical import/update boundary

Fresh normalized import is supported only when the EVW has no dataset.
Remove the current `reload=True` destructive replacement behavior and its CLI
flag. A reimport request against an existing dataset fails
`CANONICAL_REIMPORT_NOT_SUPPORTED` before mutation.

Future incremental source synchronization must use guarded canonical mutation
services that preserve IDs, increment `dataset.content_revision`, enforce
evidence/conversation deletion restrictions, and stale affected revisions. It
is not implemented by this patch.

## Named corpus

Replace the old `working_corpus` shape with:

```text
working_corpus
  working_corpus_id PK
  dataset_id FK
  name NOT NULL
  current_revision_id nullable
  created_at
  updated_at
```

`current_revision_id` is a per-corpus published-version pointer, not a global
active selection. Its composite foreign key must prove that the revision
belongs to the same corpus. It may reference only a ready/stale revision;
application publication permits only ready.

Remove status, definition, membership totals, hashes, index fields, and
`is_active` from this table.

Names must be nonblank but are display metadata, not identity; duplicate names
are allowed and the UI always includes corpus ID.

## Immutable revision

Create:

```text
working_corpus_revision
  working_corpus_revision_id PK
  working_corpus_id FK
  revision_number >= 1
  base_revision_id nullable FK
  selection_mode: all | selected
  start_date nullable inclusive YYYY-MM-DD
  end_date nullable inclusive YYYY-MM-DD
  token_limit CHECK = 768000
  estimated_tokens >= 0
  message_count >= 0
  tokenizer_id
  scope_hash
  dataset_content_revision >= 1
  status: draft | building | ready | stale | failed
  last_error
  created_at
  built_at nullable
  UNIQUE(working_corpus_id, revision_number)
  UNIQUE(working_corpus_id, working_corpus_revision_id)
```

Create revision-keyed definition tables:

```text
working_corpus_revision_source(revision_id, source_name)
working_corpus_revision_thread(revision_id, source_thread_id)
```

Create immutable membership:

```text
working_corpus_revision_message
  working_corpus_revision_id FK
  message_id FK ON DELETE RESTRICT
  source_thread_id FK
  ordinal
  token_count
  embedding_input_hash
  PRIMARY KEY(revision_id, message_id)
  UNIQUE(revision_id, ordinal)
```

The copied hash detects canonical text change in addition to dataset revision.
Ready/stale revision definition and membership rows are immutable through
repository/service APIs and database triggers. Only draft definition rows may
change; membership may be written only while building.

Canonical messages/threads referenced by any frozen revision are not
hard-deletable. Removing a message from a working corpus means publishing a new
revision without that membership; it does not delete the canonical message or
rewrite the old revision.

## Revision index

Replace `working_corpus_index` with:

```text
working_corpus_revision_index
  working_corpus_revision_index_id PK
  working_corpus_revision_id FK
  index_generation >= 1
  dataset_content_revision
  status: building | ready | stale | failed
  fts_status: missing | building | ready | stale | failed
  spellfix_status: missing | building | ready | stale | failed
  message_embedding_status: missing | building | ready | stale | failed
  chunk_embedding_status: missing | building | ready | stale | failed
  message_embedding_last_error nullable
  chunk_embedding_last_error nullable
  last_error
  created_at
  updated_at
  UNIQUE(revision_id, index_generation)
```

Scope FTS, spellfix, and chunks by
`(working_corpus_revision_id, index_generation)`. They do not use corpus ID as
the partition identity.

## Sparse content-addressed embedding tables

Delete `vector_store_metadata` and corpus-partitioned vec0 message/chunk tables.

Create one singleton geometry record only after the first successful nonempty
embedding workload:

```text
embedding_cache_state
  cache_id INTEGER PRIMARY KEY CHECK(cache_id = 1)
  dimensions > 0
  normalization: unit_l2 | none
  created_at
  updated_at
```

This is vector geometry needed for local validation/search, not model
versioning. It must not contain provider, model, model revision, deployment,
artifact fingerprint, or opaque profile identity.

Create one regular SQLite artifact table:

```text
embedding_artifact
  input_hash lowercase SHA-256 PRIMARY KEY
  dimensions > 0
  vector BLOB NOT NULL
  created_at
  CHECK(length(vector) = dimensions * 4)
```

Vectors are little-endian float32. Insertion validates count, dimensions,
finiteness, cache geometry, and hash/request correspondence before commit.
Message and chunk text with the same exact UTF-8 bytes intentionally share one
artifact. Database triggers reject an artifact whose dimensions differ from
the singleton cache state and reject artifact insertion when that state is
absent.

## Fixed-model contract and explicit clearing

The production embedding model is fixed outside the EVW. V15 deliberately does
not detect or version embedding model changes. Existing accepted/completed
events may contain server-owned model/profile metadata, but the local client
does not persist it, compare it between calls, or use it as a cache key.

Keep the existing `POST /v1/embeddings` request unchanged: it requires at
least one item. Do not add a handshake mode, expected-profile field,
capabilities route, or any other server production change for this cache.

For a nonempty workload, use dimensions/normalization from its strict accepted
event:

- If `embedding_cache_state` does not exist, hold the accepted geometry in
  memory. On the first nonempty validated vector batch, insert the singleton
  state and that batch in the same short writer transaction. A request that
  yields no valid vector writes neither state nor artifacts.
- If it exists, accepted geometry and every vector must match it.
- Validate terminal completion and exact item counts independently; the
  completed event does not define vector geometry.
- A mismatch fails visibly as `EMBEDDING_CACHE_GEOMETRY_MISMATCH`; no vector or
  readiness state from the mismatching batch is committed. Previously committed
  valid batches remain reusable, as for any interrupted build.
- A server model change that preserves dimensions/normalization is
  intentionally undetectable. Before changing embedding models during testing,
  the operator must explicitly clear local embeddings.

Implement one local operation:

```python
clear_local_embeddings() -> EmbeddingCacheClearResult
```

It acquires the application's exclusive writer operation lock and, in one
`BEGIN IMMEDIATE` transaction:

1. deletes every `embedding_artifact`;
2. deletes the singleton `embedding_cache_state`;
3. sets message/chunk embedding status to `missing` on every revision index;
4. clears only `message_embedding_last_error` and
   `chunk_embedding_last_error`; and
5. returns exact artifact and affected-index counts.

It preserves canonical messages, corpus/revision definitions and membership,
FTS/spellfix, deterministic `message_chunk` rows, evidence, conversations, and
settings. The UI disables it while any local search, embedding, or conversation
worker is active. Lock acquisition failure is visible; there is no retry,
partial clear, automatic clear, or model-change inference. After commit,
perform the normal clean SQLite checkpoint and report completion.

`EmbeddingCacheClearResult` is a frozen typed record containing
`artifacts_deleted` and `revision_indexes_marked_missing`.
The latter counts index rows whose embedding status/error state actually
changed.

`message_chunk` becomes revision/generation scoped and stores exact chunk text
plus `embedding_input_hash = sha256(UTF-8 exact body_text)`.

Do not store an artifact-to-corpus join table. Coverage is derived by joining
revision membership/chunks to `embedding_artifact` by exact input hash. The
component readiness fields are a validated summary, not the source of artifact
identity.

## Exact vector search

Use sqlite-vec scalar distance functions over regular BLOB artifacts:

```text
selected revision membership/chunks
  JOIN exact canonical input hash
  JOIN embedding_artifact by input_hash
  compute distance
  ORDER BY distance and stable tie-breakers
  LIMIT top_k
```

The distance function is `vec_distance_L2`. Pin Python `sqlite-vec==0.1.9` and
bundle the matching v0.1.9 Windows extension for Flutter probe compatibility.
Verify the native checksum and `vec_version()` at probe/test startup. Do not use
an open-ended pre-v1 dependency range.

The membership join defines candidates before ranking. Never query a global
top-K and filter afterward. Never duplicate vectors merely to place the same
message into several corpus partitions.

## Evidence block shape

Replace positional slots with exact IDs:

```text
evidence_block
  evidence_block_id PK
  dataset_id FK
  category_id FK
  source_thread_id
  title
  summary
  context_start_message_id FK RESTRICT
  relevant_start_message_id FK RESTRICT
  core_message_id FK RESTRICT
  relevant_end_message_id FK RESTRICT
  context_end_message_id FK RESTRICT
  origin_kind: working_corpus_revision | legacy_dataset
  origin_working_corpus_revision_id nullable FK RESTRICT
  origin_scope_hash nullable
  created_by
  created_at
  updated_at
```

Materialize the exact displayed range:

```text
evidence_block_message
  evidence_block_id FK CASCADE
  message_id FK RESTRICT
  ordinal
  section: leading_context | relevant | trailing_context
  message_content_hash
  PRIMARY KEY(evidence_block_id, message_id)
  UNIQUE(evidence_block_id, ordinal)
```

`message_content_hash` is lowercase SHA-256 over UTF-8 bytes of compact JSON:

```text
[message_id,timestamp,sender_display,body]
```

Serialize with `ensure_ascii=False` and separators `(',', ':')`. This detects
later source edits without copying message text.

Retain `evidence_block_highlight`, but require its
`(evidence_block_id, message_id)` to reference `evidence_block_message`.

Associate blocks to compatible revisions:

```text
working_corpus_revision_evidence_block
  working_corpus_revision_id FK RESTRICT
  evidence_block_id FK CASCADE
  inherited_from_revision_id nullable FK
  associated_at
  PRIMARY KEY(revision_id, evidence_block_id)
```

An association is valid only when every `evidence_block_message.message_id`
belongs to the revision and stored message hashes still match canonical data.

Every block has a nonempty context range and nonempty relevant range. The core
message belongs to the relevant section. Context/relevant boundary order is
validated against the exact block-message ordinal list.

## Conversation provenance

Add `working_corpus_revision_id` and preserve corpus ID, index generation, and
scope hash on conversations/turns. A presented result is pinned to the exact
captured revision. Citations must belong to that revision membership at
insertion.
