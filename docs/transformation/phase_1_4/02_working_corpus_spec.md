# Working Corpus Specification

## Concept

The canonical dataset is the full corpus imported into the EVW. A working corpus is the user-selected, token-bounded scope used by search, indexing, transcript serialization, context-window planning, and model calls.

The initial default working corpus represents the complete dataset with no source/thread/date restriction. This preserves current behavior while introducing the abstraction.

## Selection semantics

`working_corpus.selection_mode` is one of:

- `all`: include every source thread in the dataset;
- `selected`: include the union of explicitly selected sources and explicitly selected source threads.

The date range is applied after source/thread selection. Begin and end dates are inclusive calendar dates. An end date is normalized to the first instant after that calendar date using the existing message timestamp normalization rules.

An empty selected scope is valid and produces zero messages. It must be visibly reported and must not trigger model calls.

## Required schema

```sql
working_corpus(
    working_corpus_id INTEGER PRIMARY KEY,
    dataset_id INTEGER NOT NULL REFERENCES dataset(dataset_id),
    name TEXT NOT NULL,
    selection_mode TEXT NOT NULL CHECK(selection_mode IN ('all', 'selected')),
    start_date TEXT,
    end_date TEXT,
    token_limit INTEGER NOT NULL DEFAULT 768000 CHECK(token_limit = 768000),
    estimated_tokens INTEGER NOT NULL DEFAULT 0 CHECK(estimated_tokens >= 0),
    tokenizer_id TEXT NOT NULL,
    selection_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('draft', 'indexing', 'ready', 'stale', 'failed')),
    index_generation INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

working_corpus_source(
    working_corpus_id INTEGER NOT NULL REFERENCES working_corpus(working_corpus_id),
    source_name TEXT NOT NULL,
    PRIMARY KEY(working_corpus_id, source_name)
);

working_corpus_thread(
    working_corpus_id INTEGER NOT NULL REFERENCES working_corpus(working_corpus_id),
    source_thread_id TEXT NOT NULL REFERENCES source_thread(source_thread_id),
    PRIMARY KEY(working_corpus_id, source_thread_id)
);

working_corpus_message(
    working_corpus_id INTEGER NOT NULL REFERENCES working_corpus(working_corpus_id),
    message_id TEXT NOT NULL REFERENCES message(message_id),
    source_thread_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    estimated_tokens INTEGER NOT NULL CHECK(estimated_tokens >= 0),
    PRIMARY KEY(working_corpus_id, message_id)
);
```

`working_corpus_message` is derived membership and may be rebuilt. It must never contain `body`, prompt text, or duplicated transcript content.

Only one working corpus may have an index status of `indexing` or `ready` at a time. Saved definitions may exist, but only the active one is searched/indexed during these phases.

## Token budget

The hard working-corpus limit is exactly 768,000 estimated tokens. Count the serialized transcript representation used by the current transcript/window code, including the same speaker, timestamp, and delimiter material. Reuse the existing token estimation helpers; do not introduce a new chars-per-token approximation.

Store the estimator/tokenizer identity with the selection. If the selection exceeds the limit, return a structured over-limit result with counts and reduction guidance. Do not build an index and do not call a model.

The working-corpus limit is separate from per-call model context limits and window sizes. A corpus under 768,000 tokens may still require windowed search.

## Scope contract

Introduce a typed scope object, for example:

```python
@dataclass(frozen=True)
class WorkingCorpusScope:
    working_corpus_id: int
    dataset_id: int
    index_generation: int
    estimated_tokens: int
```

Every local search/index/transcript function must receive or resolve this scope. A raw `dataset_id` is sufficient only for canonical import/storage operations, never for search.

## Index rules

FTS5 rows must include `working_corpus_id UNINDEXED`, and every query must constrain it.

sqlite-vec rows must be partitioned by a stable composite identity containing both model and working-corpus ID, such as:

```text
<model_name>\x1f<working_corpus_id>
```

Do not retrieve global vector candidates and filter them afterward. The working-corpus constraint must be part of the vector query partition. Apply this to message vectors, chunk vectors, and vector metadata.

When canonical messages, threads, timestamps, or relevant import data change, mark the active working corpus `stale`, increment nothing yet, and refuse search until a complete rebuild succeeds.

Index lifecycle:

```text
draft → indexing → ready
                 ↘ failed
ready → stale
stale → indexing → ready
```

There is no searchable partial index.
