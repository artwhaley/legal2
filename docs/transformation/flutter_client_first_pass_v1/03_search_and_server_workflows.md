# Search and server workflows

## Local FTS5

Add typed `SearchHit` and `SearchPage` models and an `EvwDatabase.ftsSearch`
method. Mirror the current Python semantics:

- trim the query;
- extract Unicode word/apostrophe terms;
- reject a query with no searchable terms;
- quote each term and join with `AND`;
- require selected ready revision and current index generation;
- constrain `message_fts.working_corpus_revision_id` and `index_generation`;
- order by `bm25`, timestamp, sort index, and message ID;
- join the canonical message/thread data needed for display;
- return total, rows, and next offset.

No spellfix or keyword-expansion call is made.

## Local vector lookup

Add typed embedding geometry and vector hit models. Before the remote call,
require:

- selected ready revision/index generation;
- `message_embedding_status='ready'`;
- one `embedding_cache_state` row.

Call `/v1/embeddings` with exactly one item:

```json
{"message_id":"query","text":"<user query>"}
```

Validate the accepted dimensions/normalization against local geometry. Require
exactly one finite vector and a matching completed terminal count. Serialize
float32 little-endian bytes and execute the existing sqlite-vec L2 query over
message artifacts, constrained to selected revision membership. Return display
messages ordered by distance with deterministic timestamp/sort-index/ID ties.

Do not store query vectors. Do not generate missing corpus vectors. Geometry
mismatch fails as `EMBEDDING_CACHE_GEOMETRY_MISMATCH`.

## Dart gateway

Create a small `ServerGateway` interface and `HttpServerGateway`
implementation using `dart:io` `HttpClient`; do not add a general networking
framework. Implement only:

- conversational plan JSON POST;
- embedding NDJSON POST;
- conversational analysis NDJSON POST.

Generate RFC 4122 v4 request IDs using secure random bytes. Each request owns a
cancellation handle that closes its HTTP request/response. Cancellation is
reported distinctly from failure.

Port the current exact Python response checks from
`client_api/contracts.py`. At minimum validate:

- HTTP status and structured error body;
- content type;
- request identity;
- strictly increasing sequence starting at 1;
- one immutable config version per stream;
- exact known event names and required event fields;
- no data after terminal;
- exactly one terminal `completed|failed`;
- analysis-plan exact shape;
- embedding accepted/vector/completed geometry;
- completed conversational result discriminants and all fields required for
  safe rendering/navigation.

Do not make parsing more permissive than the current Python client. Preserve
server warnings and readable raw results; strict transport/schema validation
is not permission to discard a valid completed result.

## Conversational workflow

Port the current `ConversationalWorkflow` behavior to a typed Dart coordinator,
without copying Python UI code:

1. acquire the workspace remote-operation lease;
2. snapshot selected revision ID, generation, and scope hash;
3. validate a nonblank question and nonempty revision;
4. request `/v1/conversational-plan`;
5. if retrieval mode is `none`, build the exact empty-hits context;
6. if `semantic_ranges`, verify local embedding geometry, request all planner
   query embeddings in one server workload, run local message-vector
   candidates per query, and construct the frozen analysis context;
7. read all selected-revision messages in ordinal order and map them to
   `message_id/thread_id/timestamp/sender/text`;
8. submit `/v1/conversational-analysis`;
9. publish every progress/heartbeat/retry/window/warning/synthesis event to the
   UI and keep elapsed time running until terminal;
10. on completed, validate and present the complete result, then persist only
    visible history;
11. on cancel, show cancelled and persist no incomplete turn;
12. on failure, retain the question card plus a visible failed status and
    original structured server details;
13. release the operation lease in `finally`.

The selected scope must still match the snapshot before persistence or
evidence creation. Since selection changes are blocked during remote work, a
mismatch is an integrity error, not a fallback case.

Do not add client retries, provider/model fallbacks, windowing, synthesis,
ranking, or result recategorization. Those are server decisions.

## Foreground operation policy

V1 permits one remote operation per Flutter process. FTS and transcript edits
are local; embedding search and conversation acquire the lease. While leased:

- corpus close/switch and another remote operation are refused visibly;
- the owning page exposes Cancel;
- tab navigation and transcript reading remain available;
- app-window close is refused until the user cancels or the operation reaches
  terminal state.

This explicit serialization is a client V1 simplification, not a server
concurrency limitation.

