# Server and Python Client Contract

## API v2

The server exposes only:

```text
GET  /v2/health
GET  /v2/capabilities
POST /v2/keyword-expansion
POST /v2/retrieval-terms
POST /v2/embeddings
POST /v2/answers/whole-transcript
POST /v2/answers/window-scan
POST /v2/answers/evidence-ledger-synthesis
```

The server exposes no `/v1` aliases. Remove
the legacy window-merge endpoint. Evidence-ledger synthesis is the only merge.

All POST requests contain `request_id` and this required scope metadata:

```text
working_corpus_id
index_generation
scope_hash
```

Scope metadata is opaque correlation/provenance to the server. The server does
not resolve or persist it.

## Capabilities

`/v2/capabilities` returns:

```text
api_version = 2
prompt_set_version = 2
operations: map operation -> model_id, context_window_tokens,
            max_output_tokens, max_request_tokens
embedding: model_name, model_revision, dimensions, normalization,
           embedding_profile_id, max_batch_size (exactly <= 32)
```

The client refuses an incompatible API version or missing required operation.
It uses the writing operation's context/output limits for local window planning
and the embedding capability as the sole vector-index identity.

Server startup validates every configured model, provider base URL, credential,
positive context/output limit, embedding model, and request limit. Each of the
five model endpoints has an independent server-owned configuration and an
independent capability entry. The local server GUI edits, validates, tests,
saves, starts, and stops this configuration; API keys never enter an EVW.
Invalid configuration prevents startup with one explicit error. Tests inject fake
providers through `create_app`; production has no environment-selectable fake
fallback.

## Request/response rules

- Keyword expansion accepts the user query and returns a bounded ordered list
  of normalized terms.
- Retrieval terms accepts the user question and returns the bounded terms used
  only as local scoped hints.
- Embeddings accepts ordered `{local_id, text}` items, rejects duplicate IDs,
  preserves order, and returns one `{local_id, vector}` per input plus exact
  model metadata/profile ID. It never accepts an EVW path or database
  identifier beyond opaque scope metadata.
- Whole transcript accepts serialized transcript text, ordered message IDs,
  source-thread IDs, and question. Oversize input fails; it is not truncated.
- Window scan accepts one deterministic window, ordered IDs, and question.
- Ledger synthesis accepts validated ledger records with stable local range
  IDs. The server returns those IDs; it does not invent message IDs.
- Every response echoes `request_id` and scope metadata.
- Errors use `{code, message, details, request_id}` and never echo body text.

The server validates provider output before returning. The client independently
validates all returned message/range IDs against the supplied active scope.

## Prompt set v2

Package only the five active prompts:

- keyword expansion;
- exhaustive retrieval terms;
- whole-transcript answer;
- exhaustive window scan;
- evidence-ledger synthesis.

Remove planner, generic synthesis, coverage/session, evidence-range suggestion,
and legacy window-merge prompts and run types. Hash prompt-set v2 in tests and
include it in the wheel.

## Server package isolation

Move provider clients, provider error translation, task-role mapping, retries
(which must be disabled), model result types, and embedding-model loading under
`server/`. The server may depend on neutral third-party libraries but may not
import `message_evidence_workstation` at runtime. Conversely, the desktop client
may not import `server` at runtime.

Add an AST/import-boundary test that walks both packages and fails on either
direction, except tests may import `server.create_app` to inject fakes.

## Python client gateway

Keep one concrete `RemoteGateway`; remove the resolver singleton and optional
return. Construct the gateway from the non-secret client setting `server_url`
and inject it into `ClientWorkflowService` and UI services.

The gateway has one method per v2 endpoint. It performs one HTTP attempt, has a
finite explicit timeout, validates the complete response, and raises one typed
`RemoteGatewayError`. No retry or local fallback exists.

## Client settings

Replace the current settings model with only client-owned values:

```text
server_url
answer_strategy: whole_transcript | exhaustive_window_scan
context_safety_ratio
prompt_overhead_tokens
window_overlap_messages
fts_page_size
max_expansion_terms
embedding_selectivity
chunking configuration
transcript display preferences
```

Delete NIM/provider keys, provider/model routing, model lists, embedding model
selection/download, local context/output/model metadata, settings migration for
those fields, and hidden widgets. The Settings tab contains server URL, Test
Server, the returned read-only capabilities, and the client-owned planning/UI
settings above.

## Client workflow service

Create one non-UI orchestration surface used by both tests and PySide tabs:

```text
resolve_active_scope()
run_fts(scope, date_scope, query, page)
run_keyword_expanded_fts(scope, date_scope, query)
build_embeddings(scope, kind)
run_embedding_search(scope, date_scope, query, kind)
run_conversational_search(scope, date_scope, question)
```

It owns sequencing and emits explicit progress events. UI tabs do not assemble
their own database/network workflows.

### Lexical search

FTS and spellfix execute locally through required scope-aware repository APIs.
Expanded search calls the server first, then applies returned terms only to the
same local `NarrowedSearchScope`.

### Embedding build and search

For each corpus generation, read at most 32 member texts/chunks with a
short-lived reader, close it, call `/v2/embeddings`, validate IDs/dimensions,
then commit vectors through the single writer. Resume state is stored in the
generation's `working_corpus_index` row. A failed batch marks the index failed;
it never marks a partial index ready.

Query embedding uses the same endpoint/model metadata. KNN runs locally inside
the exact corpus/model/generation partition and applies date narrowing in its
canonical-message join.

### Conversational search

Resolve and freeze one scope at request start. Build the transcript/windows
only from membership joined to canonical messages. Recheck active scope and
generation before presenting/persisting the result; if the corpus changed,
discard the unpresented result visibly. Persist one visible turn and its valid
citations in one writer transaction.

## Corpus UI

Add one lean `Search Corpus` tab/panel to the Python client. It shows canonical
full-corpus counts and the active limited-corpus definition/count/token/status.
It provides:

- name;
- all vs selected mode;
- explicit source-platform and thread selections;
- optional inclusive start/end dates;
- Preview;
- Build and Activate;
- visible membership/index progress and errors.

Preview performs no writes. Build is explicit and sequential. If the full
corpus is within 768,000 tokens, import creates, builds, and activates a default
`Full corpus` search corpus. If it is over limit, import leaves canonical data
ready, creates a failed candidate with counts, and routes the user to this
panel. It never silently narrows.

All search tabs show the active corpus name/count/date and disable themselves
when no valid active scope exists.

## Required source deletion/rewrite

Delete or move out of the client package, then fix imports rather than leaving
shims:

- `message_evidence_workstation/llm/router.py`
- `message_evidence_workstation/llm/providers/`
- client provider retry/error/task-role code
- `message_evidence_workstation/nim/client.py`
- `message_evidence_workstation/nim/model_runs.py`
- `message_evidence_workstation/nim/prompts.py`
- `message_evidence_workstation/search/tool_runner.py`
- `message_evidence_workstation/search/synthesis.py`
- the legacy bounded exhaustive-window merge implementation/parser
- local `SentenceTransformerAdapter` and adapter factory branches
- `embeddings/dataset_embedding_cache.py` and BLOB fallback behavior
- old process/model-run export functions

Rewrite `exhaustive_hints.py`, `keyword_expansion.py`, and
`conversational_answer.py` against `RemoteGateway` and required scope. Do not
leave deprecated wrappers with old signatures.
