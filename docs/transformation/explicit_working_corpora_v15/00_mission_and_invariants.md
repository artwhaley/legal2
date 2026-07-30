# Mission and Invariants

## Four distinct concepts

### Canonical dataset

`dataset`, `source_thread`, and `message` are the one source of transcript
truth. A working corpus never copies message bodies.

### Named working corpus

A durable organizational object such as `Recent family messages`. It has a
name and a pointer to its published current revision. It has no readiness,
membership, index, or global selection state of its own.

### Working-corpus revision

An immutable searchable snapshot of selection criteria, ordered membership,
canonical content revision, token total, scope hash, and derived-index
generation. Ready revisions are never edited in place.

### Evidence block

A canonical user-created artifact over an exact ordered set of canonical
message IDs. It records the revision from which it was created and may be
associated with every later/overlapping revision that contains its complete
message set.

## Corpus and revision invariants

1. One EVW may contain any number of named corpora.
2. Every corpus may have many immutable revisions.
3. At most one revision per corpus is published as current.
4. Publishing corpus A has no effect on corpus B.
5. There is no global active corpus.
6. UI selection is process-local and performs no EVW write.
7. A search worker captures one `WorkingCorpusScope` before starting. Later UI
   changes cannot redirect it.
8. Editing a corpus creates a draft revision copied from an explicit base
   revision. Only drafts are editable.
9. Building freezes the draft definition, materializes membership, and creates
   a lexical-index generation.
10. A built revision is published only after membership/index validation and
    evidence compatibility resolution.
11. A failed draft/build never replaces the corpus's published revision.
12. Older ready revisions remain explicitly selectable and searchable while
    their canonical dataset revision remains current.
13. A canonical content-revision change makes older revisions stale for new
    searches. Their saved membership, history, and evidence associations remain
    visible for provenance.
14. Empty membership is a valid built revision, but network-required embedding
    and conversation actions reject it before HTTP.
15. A revision over 768,000 tokens fails. It is never trimmed or sampled.
16. Scope hashing covers the canonical revision, complete frozen definition,
    ordered member IDs, exact serialized-message token counts, and tokenizer.

## Revision state machine

```text
draft -> building -> ready (unpublished)
                \-> failed

ready -> published by updating working_corpus.current_revision_id
ready -> stale when canonical revision changes
failed -> no mutation; create another draft revision
stale  -> no mutation; create another draft revision
```

Rebuilding never mutates a frozen revision. A user request described as
“rebuild this corpus” creates a new draft revision from the selected base,
builds it, and publishes it after explicit evidence resolution.

Lexical index generations remain derived children of a revision. FTS and
spellfix must both be ready before the revision becomes ready. A repair of
corrupt derived indexes may create a new index generation without changing
membership; it still cannot change the revision definition or membership.

## Sparse embedding invariants

1. No full-corpus precomputation exists.
2. Embedding artifacts are created only for inputs requested by an explicit
   revision embedding build.
3. An artifact is keyed only by lowercase SHA-256 of the exact UTF-8 text sent
   for embedding.
4. Identical exact text reuses one artifact across messages, chunks, corpora,
   and revisions.
5. Different exact text requires a different artifact.
6. Query embeddings are request-local and not persisted.
7. Revision embedding readiness means every required member/chunk resolves to a
   valid artifact with the local cache's recorded vector geometry.
8. Cached artifacts outside the selected revision are not search candidates.
9. The production embedding model is an operational constant. The EVW does not
   store or version provider, model, model revision, deployment, or opaque
   profile identity.
10. Provider calls receive only cache misses. Returned artifacts are validated
    and committed in short batches.
11. Testing may change the server embedding model only after the operator uses
    the explicit `Clear local embeddings` action. Nothing clears or invalidates
    embeddings automatically.
12. Clearing embeddings preserves canonical data, corpus definitions,
    revisions, membership, lexical indexes, deterministic chunks, evidence,
    conversations, and settings. It deletes only vector artifacts/cache
    geometry and marks embedding coverage missing.

## Evidence invariants

1. Evidence blocks are dataset artifacts, not exclusively owned by one corpus.
2. Every new block records its origin revision and origin scope hash.
3. Every block stores its exact ordered context-range message IDs.
4. Boundary/core/highlight IDs must belong to that stored range, same dataset,
   and same thread in legal order.
5. Stored positional slots do not exist in v15. UI slot positions are derived
   from the exact block-message list.
6. A block-revision association exists only when every stored block message is
   a member of that revision.
7. Adding messages in a new revision preserves compatible associations.
8. Removing any block message creates a publication conflict.
9. Conflict handling never shrinks, moves, deletes, or silently detaches a
   block.
10. Hard deletion of any canonical message referenced by a block is rejected
    with the referencing block IDs.
11. Editing a block is allowed only when the replacement exact range validates
    against every retained revision association; incompatible associations
    require explicit detachment in the same transaction.

## Server boundary

The server receives an opaque scope ID and exact request-local messages. It
does not know about corpus names, current revisions, SQLite, evidence
associations, or embedding-cache storage.

`POST /v1/embeddings` keeps its existing nonempty-item contract. The client
sends only locally computed cache misses and uses returned vector dimensions
and normalization solely to validate local vector geometry. It does not
persist or compare the server's opaque embedding identity. No capabilities,
profile, cache-management, or fourth product endpoint is added.

## Deliberate exclusions

This patch does not add Flutter writes, source synchronization, auth, billing,
BYOK, server persistence, corpus deletion UI, automatic rebuild, background
embedding, vector-cache pruning, or a new server route.

Because source synchronization is not implemented, v15 also removes the
current destructive normalized-dataset reload path. Reimport cannot delete and
recreate canonical/user data behind existing revisions and evidence.
