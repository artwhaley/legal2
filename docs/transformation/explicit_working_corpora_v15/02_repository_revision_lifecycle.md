# Repository and Revision Lifecycle Contract

## Immutable scope

Extend `WorkingCorpusScope` to contain:

```python
working_corpus_id: int
working_corpus_revision_id: int
revision_number: int
dataset_id: int
index_generation: int
dataset_content_revision: int
scope_hash: str
message_count: int
estimated_tokens: int
tokenizer_id: str
```

Its exact opaque server identity is:

```python
remote_scope_id = (
    f"evw15:{working_corpus_id}:"
    f"{working_corpus_revision_id}:"
    f"{index_generation}:{scope_hash}"
)
```

The server treats this as opaque.

## Typed repository projections

Implement frozen, slotted:

```text
WorkingCorpusSummary
WorkingCorpusRevisionSummary
WorkingCorpusDefinition
WorkingCorpusScope
EvidenceBoundaryIds
EvidenceCompatibilityConflict
EvidenceCompatibilityReport
```

Do not return untyped dictionaries from new corpus/revision lifecycle APIs.

## Required repository API

Use these binding names:

```python
create_working_corpus(*, dataset_id: int, name: str) -> int
rename_working_corpus(*, working_corpus_id: int, name: str) -> None
list_working_corpora(dataset_id: int) -> list[WorkingCorpusSummary]
list_revisions(working_corpus_id: int) -> list[WorkingCorpusRevisionSummary]

create_draft_revision(
    *,
    working_corpus_id: int,
    base_revision_id: int | None,
) -> int

replace_draft_definition(
    *,
    working_corpus_revision_id: int,
    selection_mode: str,
    start_date: str | None,
    end_date: str | None,
    source_names: Iterable[str],
    source_thread_ids: Iterable[str],
) -> None

get_revision_definition(
    working_corpus_revision_id: int,
) -> WorkingCorpusDefinition

require_current_scope(
    *,
    working_corpus_id: int,
    dataset_id: int,
) -> WorkingCorpusScope

require_ready_scope(
    *,
    working_corpus_revision_id: int,
    dataset_id: int,
) -> WorkingCorpusScope

validate_ready_scope(scope: WorkingCorpusScope) -> None
```

Build/publication services use:

```python
build_revision(
    working_corpus_revision_id: int,
) -> WorkingCorpusScope

assess_evidence_compatibility(
    *,
    base_revision_id: int | None,
    candidate_revision_id: int,
) -> EvidenceCompatibilityReport

publish_revision(
    *,
    working_corpus_id: int,
    working_corpus_revision_id: int,
    excluded_evidence_block_ids: frozenset[int],
) -> WorkingCorpusScope
```

Delete activation, implicit scope, mutable membership, and in-place rebuild
APIs. Do not keep deprecated wrappers.

## Draft definition rules

- Creating the first draft uses `base_revision_id=None`.
- A later draft must identify the corpus's current published revision as its
  base. Branching from an older revision requires creating a new named corpus
  and is not implicit.
- Draft creation copies the base definition exactly.
- Only `replace_draft_definition` may change criteria.
- It rejects non-draft revisions.
- `selection_mode=all` requires empty selected-source/thread sets.
- `selection_mode=selected` requires at least one source or thread.
- Dates are inclusive, valid, and ordered.
- Sources/threads must exist in the owning dataset.
- Definition replacement is one transaction; partial criteria are never
  visible.
- Calling build transitions the draft to building and freezes criteria.

## Build algorithm

`build_revision` performs this linear flow for only the addressed revision:

1. Validate draft state, ownership, definition, and canonical dataset readiness.
2. Transition revision to `building`.
3. Materialize all matching ordered membership in memory/temporary work.
4. Count exact conversational serialized tokens using `cl100k_base`.
5. If over 768,000, write no membership/index rows, mark failed with exact
   total, and stop.
6. Write complete revision membership in one bounded transaction.
7. Compute scope hash and verify every copied embedding input hash.
8. Create lexical index generation 1 in `building`.
9. Build revision-scoped FTS and spellfix.
10. Validate counts, hashes, component status, and canonical revision.
11. Atomically mark index and revision ready.
12. Return the ready scope without publishing it.

An empty revision completes ready with empty lexical indexes. Embedding and
conversation services raise `WORKING_CORPUS_EMPTY` before HTTP.

On failure, mark only the candidate revision/generation failed, retain the
original cause, and leave every corpus pointer and other revision unchanged.

## Publication and evidence compatibility

Publication is separate from build.

For each block associated with `base_revision_id`:

- `compatible`: every exact block message and content hash is present in the
  candidate; association is carried.
- `incompatible`: report missing/changed message IDs; do not carry unless the
  block is separately edited into a new valid artifact.

`publish_revision` requires:

- candidate revision ready and owned by the corpus;
- corpus current pointer still equals candidate `base_revision_id` (or both are
  null for initial publication);
- candidate canonical revision current;
- a freshly recomputed compatibility report;
- `excluded_evidence_block_ids` exactly equal to the incompatible IDs.

If incompatible IDs are omitted or extra IDs are supplied, publication fails
without changing the current pointer. This makes every dropped association an
explicit caller decision.

In one transaction publication:

1. inserts all compatible inherited associations;
2. records one existing `workspace_event` per exclusion using event type
   `working_corpus_revision_evidence_excluded` and details containing corpus,
   base revision, candidate revision, and evidence-block IDs only;
3. updates `working_corpus.current_revision_id`;
4. leaves the previous revision and its associations unchanged.

For the first revision, the report is empty and publication simply sets the
pointer.

## Readiness

`require_ready_scope(revision_id, dataset_id)` checks:

- exact revision/dataset/corpus ownership;
- revision status ready;
- revision dataset revision equals canonical dataset revision;
- every membership message exists and its copied embedding hash matches;
- newest ready lexical generation has matching canonical revision and complete
  FTS/spellfix;
- stored counts, token limit, and scope hash.

`require_current_scope(corpus_id, dataset_id)` resolves the corpus's explicit
published pointer and then calls `require_ready_scope`. It never chooses another
revision.

`validate_ready_scope(scope)` rechecks every captured field. It is the only
production validator used by FTS, spellfix, embeddings, transcript snapshots,
conversation calls, and persistence.

Use typed errors with stable `code`:

```text
WorkingCorpusNotFoundError          WORKING_CORPUS_NOT_FOUND
WorkingCorpusRevisionNotFoundError  WORKING_CORPUS_REVISION_NOT_FOUND
WorkingCorpusNoPublishedError       WORKING_CORPUS_NO_PUBLISHED_REVISION
WorkingCorpusRevisionNotReadyError  WORKING_CORPUS_REVISION_NOT_READY
WorkingCorpusRevisionStaleError     WORKING_CORPUS_REVISION_STALE
WorkingCorpusIndexNotReadyError     WORKING_CORPUS_INDEX_NOT_READY
WorkingCorpusDefinitionError        WORKING_CORPUS_DEFINITION_INVALID
WorkingCorpusOverLimitError         WORKING_CORPUS_OVER_LIMIT
WorkingCorpusEmptyError             WORKING_CORPUS_EMPTY
EvidenceCompatibilityError          EVIDENCE_COMPATIBILITY_REQUIRED
WorkingCorpusBaseChangedError       WORKING_CORPUS_BASE_CHANGED
EmbeddingCacheGeometryMismatchError EMBEDDING_CACHE_GEOMETRY_MISMATCH
EmbeddingCacheBusyError             EMBEDDING_CACHE_BUSY
```

No production scope resolver returns `None` or falls back.

## Sparse embedding workflow

The Python gateway exposes exactly:

```python
embeddings(items: list[EmbeddingItem]) -> Iterator[StreamEvent]
```

It keeps the existing nonempty `POST /v1/embeddings` contract. No profile,
capabilities, expected-model, or cache-control method/route is introduced.
The strict transport parser may continue validating the server's existing
opaque identity fields because they are part of its wire schema; local
workflow state, decisions, results, and persistence do not retain or compare
them.

Use these local result shapes:

```python
EmbeddingBuildResult(
    required_inputs: int,
    reused_artifacts: int,
    generated_artifacts: int,
    dimensions: int,
    normalization: str,
)

EmbeddingCacheClearResult(
    artifacts_deleted: int,
    revision_indexes_marked_missing: int,
)
```

Neither contains a profile/model/version identity.

For message embeddings:

1. Validate the exact captured revision scope.
2. Capture all `(message_id, embedding_input_hash, body)` rows without holding
   a transaction across HTTP.
3. Join requested hashes to local `embedding_artifact`.
4. If misses exist, send the existing embedding workload containing only
   unique missing hashes/text. If no misses exist, make no server request.
5. Validate every returned ID/vector plus accepted dimensions and normalization
   against the local cache geometry contract; validate completed item count.
6. Insert immutable artifacts in short writer transactions. Existing matching
   artifacts must be byte-compatible; conflicting artifacts fail.
7. Recompute coverage against the complete revision.
8. Mark message embedding ready only when coverage is complete.

Messages with identical body hashes may share one request item/artifact. The
workflow retains a deterministic hash-to-message mapping and verifies all
message coverage. Cache-build request item IDs are exactly
`cache:<input_hash>`; the server echoes them unchanged. Query embedding IDs are
request-local UUID-based IDs and are never persisted.

For chunks, first deterministically build revision-scoped chunks, then perform
the same process keyed by chunk text hash. A later revision reuses unchanged
chunk hashes and sends only changed/new chunks.

Interrupted builds preserve valid committed artifacts. Resume recomputes
missing hashes and sends only those. It never assumes that component status is
the cache source of truth.

## Exact embedding search

For the selected revision:

1. Reject incomplete coverage before calculating a query vector.
2. Request one query embedding with the existing endpoint contract.
3. Validate dimensions and normalization against `embedding_cache_state`.
4. Run exact scalar-distance SQL over the membership/chunk join and matching
   artifact rows.
5. Apply optional date/thread narrowing inside the candidate join.
6. Order by distance and stable canonical tie-breakers.
7. Return only selected-revision IDs.

No global KNN over-fetch/filter loop is allowed.

The local vector-search binding accepts scope, query vector, dimensions,
`top_k`, and granularity. Remove profile ID from its parameters and SQL.

## Explicit embedding reset

The production service operation is exactly:

```python
clear_local_embeddings() -> EmbeddingCacheClearResult
```

It performs the transaction and preservation behavior in file 01. The Python
integration harness exposes it as `Clear local embeddings` with an explicit
confirmation that states that all local vectors will be deleted and must be
rebuilt. It is disabled while a local operation worker is active. The result
shows exact deleted-artifact and affected-index counts. Cancellation makes no
change; failure remains visible with the original cause.

This is a testing/maintenance action, not automatic invalidation. The operator
uses it before any test-time embedding model change. Production assumes the
embedding model does not change.

## Evidence repository behavior

Use these binding production operations:

```python
create_evidence_block(
    *,
    scope: WorkingCorpusScope,
    category_id: int,
    source_thread_id: str,
    title: str,
    summary: str,
    context_start_message_id: str,
    relevant_start_message_id: str,
    core_message_id: str,
    relevant_end_message_id: str,
    context_end_message_id: str,
    highlighted_message_ids: tuple[str, ...],
    created_by: str,
) -> EvidenceBlock

replace_evidence_block_range(
    *,
    evidence_block_id: int,
    boundary_ids: EvidenceBoundaryIds,
    highlighted_message_ids: tuple[str, ...],
    detach_revision_ids: frozenset[int],
) -> EvidenceBlock

associate_evidence_block(
    *,
    working_corpus_revision_id: int,
    evidence_block_id: int,
) -> None
```

New block creation requires an explicit ready revision scope and exact boundary
IDs. The repository:

1. validates boundary/core order within one thread;
2. resolves the complete context range from the captured revision membership;
3. validates highlights are a subset;
4. writes block, exact block-message rows, highlights, origin provenance, and
   revision association in one transaction.

Boundary/highlight edits rebuild the exact block-message rows atomically. The
caller must explicitly detach every existing revision association that would
become incompatible. No silent association loss is allowed.

Canonical hard delete checks `evidence_block_message`, highlights, evidence
boundaries, and visible conversation citations. Any reference rejects deletion
with IDs and no mutation.

`associate_evidence_block` provides explicit cross-corpus reuse. It inserts
only after complete message/hash compatibility validation. It never changes
block contents.
