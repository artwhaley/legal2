# EVW v14 and Working-Corpus Contract

## Version policy

Set `SCHEMA_VERSION = 14`. Fresh workspaces are created directly as v14.
Production Python and Flutter clients reject every other version with a clear
"migration required" error.

Implement a separate compact-copy command:

```powershell
python -m message_evidence_workstation.tools.migrate_evw `
  --source OLD.evw --output NEW.evw --dataset-id N
```

It accepts the known v12 layout and the experimental v13 layout, opens them
through normal SQLite recovery, checkpoints, creates a compact backup, copies
canonical user data into a new v14 file, validates it, and never edits the
source. Multiple source datasets require `--dataset-id`. Runtime open code must
not contain v12/v13 branches after this tool exists.

## Canonical and persistent data

Retain exactly one `dataset`, canonical `source_thread` and `message` rows,
categories, evidence blocks/highlights, printable artifacts, visible
conversations/citations, non-secret workspace settings, workspace state/events,
working-corpus definitions/membership, and rebuildable local indexes.

Do not create or migrate prompt templates, model runs, process logs, raw model
payloads, hidden windows, provider bodies, embedding request bodies, API keys,
auth/payment data, validation-smoke tables, or style-lab remnants.

Add `dataset.content_revision INTEGER NOT NULL DEFAULT 1`. Any canonical change
that can alter scope membership or serialized transcript text increments it in
the same writer transaction.

## Working-corpus tables

`working_corpus` is an immutable saved selection once membership is ready.
Changing source/thread/date selection creates a new row rather than mutating a
searchable definition.

Required columns:

```text
working_corpus_id PK
dataset_id FK
name
selection_mode: all | selected
start_date nullable inclusive YYYY-MM-DD
end_date nullable inclusive YYYY-MM-DD
token_limit CHECK = 768000
estimated_tokens >= 0
message_count >= 0
tokenizer_id
scope_hash
content_revision
status: draft | indexing | ready | stale | failed
is_active: 0 | 1
index_generation >= 0
last_error nullable
created_at, updated_at
```

Enforce one dataset per EVW and one `is_active = 1` corpus. An active corpus
must have ready membership. Keep `working_corpus_source`,
`working_corpus_thread`, and `working_corpus_message`; membership stores IDs,
ordinal, and token count only, never duplicate bodies.

Add `working_corpus_index`:

```text
working_corpus_index_id PK
working_corpus_id FK
index_generation
index_kind: fts | spellfix | message_embedding | chunk_embedding
embedding_profile_id (empty for fts/spellfix)
model_name (empty for fts/spellfix)
model_revision
dimensions nullable
normalization_mode
config_json
status: building | ready | stale | failed
item_count >= 0
last_error
created_at, updated_at
UNIQUE(working_corpus_id, index_generation, index_kind, embedding_profile_id)
```

For embedding rows, store the server-reported profile ID and its component
metadata in their explicit columns. Add singleton
`vector_store_metadata(dimensions, sqlite_vec_version, created_at)`. sqlite-vec
tables have one fixed dimension. If server capabilities report a different
dimension, mark every embedding index stale, drop/recreate both derived vec
tables at the new dimension, and require rebuild. Never reinterpret or pad old
vectors.

`conversation_turn` must additionally store `working_corpus_id`,
`index_generation`, and `scope_hash`, so a presented answer has visible
scope provenance. Citations retain foreign keys to canonical messages and are
validated as members of that recorded corpus generation before insertion.

## Scope types

Define these exact immutable types in
`message_evidence_workstation/domain/search_scope.py`:

```python
@dataclass(frozen=True, slots=True)
class WorkingCorpusScope:
    working_corpus_id: int
    dataset_id: int
    index_generation: int
    scope_hash: str
    content_revision: int
    tokenizer_id: str
    message_count: int
    estimated_tokens: int

@dataclass(frozen=True, slots=True)
class NarrowedSearchScope:
    corpus: WorkingCorpusScope
    start_date: date | None
    end_date: date | None
```

Only `WorkingCorpusRepository.require_active_scope()` constructs the base scope.
It validates active, ready, matching content revision, and ready FTS/spellfix
rows for the current generation. Date narrowing validates inclusive dates and
can only filter existing `working_corpus_message` membership.

## Token and selection rules

- Selected mode is the union of selected source platforms and selected thread
  IDs, followed by the inclusive date filter.
- Empty selection is valid but cannot be activated for search.
- Token count uses the exact serialized line representation consumed by
  conversational/window code and the pinned `tiktoken:cl100k_base` tokenizer.
  Do not use a chars-per-token approximation. Store that exact tokenizer ID.
- Over 768,000 tokens marks the candidate failed, keeps canonical data, creates
  no derived indexes, and does not alter the current active corpus.
- Selection hash covers dataset content revision, selection fields, selected
  sources/threads, ordered member IDs, per-message token counts, and tokenizer.

## Scoped lexical indexes

Recreate `message_fts` with these columns:

```text
working_corpus_id UNINDEXED
index_generation UNINDEXED
message_id UNINDEXED
source_thread_id UNINDEXED
body
body_normalized
sender_display
```

Every FTS query constrains both `working_corpus_id` and `index_generation`
inside SQL. Every result/detail join also joins `working_corpus_message`.
Remove `dataset_id` from all public FTS/search signatures.

Partition spellfix by the active working-corpus ID using `langid`; its term
metadata includes corpus ID and generation. Search is blocked during rebuild,
so a failed rebuild cannot expose old vocabulary as current.

## Scoped vector indexes

The only sqlite-vec partition identity is:

```text
<embedding_profile_id>\x1f<working_corpus_id>\x1f<index_generation>
```

`embedding_profile_id` is lowercase SHA-256 hex of UTF-8
`model_name\x1fmodel_revision\x1fdimensions\x1fnormalization`. The server
returns it in capabilities and every embedding response; the client recomputes
and verifies it. The partition is required, never optional. Message and chunk
vec tables include auxiliary corpus ID, generation, source-thread ID, and
canonical message/chunk IDs for validation. KNN SQL constrains the partition
key before applying `LIMIT`; it must never retrieve globally and filter
afterward.

`message_chunk` is generation-scoped and contains the exact serialized chunk
text needed for embedding requests, local result display, and index rebuild. It
is rebuildable and contains only active working-corpus members. Embedding
metadata lives only in
`working_corpus_index`; remove dataset-scoped `embedding_index_metadata` and
the BLOB cache/fallback path.

## One writer and lifecycle

Replace raw shared connections with `WorkspaceStore`:

- acquire a held OS lock on a sidecar lock file before any writable open;
- create one dedicated writer thread and create its SQLite connection inside
  that thread;
- expose serialized `write(operation)` / `write_async(operation)` calls with
  caller-owned transactions;
- expose operation-scoped `mode=ro` readers;
- never hold a transaction while calling HTTP, waiting on UI, tokenizing, or
  embedding;
- embedding jobs read one batch, close reader, call server, then commit one
  returned batch through the writer;
- checkpoint at bounded bulk-operation boundaries and perform verified
  `wal_checkpoint(TRUNCATE)` on clean close;
- release the OS lock only after writer close.

App/UI/repository constructors receive `WorkspaceStore` or a narrow service,
not a long-lived raw writable `sqlite3.Connection`. A static test must reject
`connect(` calls under `ui/`, import jobs, and embedding jobs.
