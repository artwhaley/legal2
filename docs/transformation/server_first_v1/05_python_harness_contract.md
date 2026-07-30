# Temporary Python EVW harness contract

The Python application is not a product target. Modify it only in tickets
SFV1-800 through SFV1-803 so it can prove the new server against the real local
EVW workflow. Do not add Python UI architecture, settings tabs, generic job
frameworks, or compatibility branches.

Retain `python -m message_evidence_workstation.app` as the temporary harness
launch command. Do not add a second launcher.

## Retained local behavior

The Python harness continues to:

- open and cleanly close EVW v14 through `WorkspaceStore`;
- resolve the active working corpus and optional date/thread narrowing;
- run local scoped FTS5 and sqlite-vec searches;
- persist streamed embeddings into profile/generation partitions;
- persist only the user prompt, final presented answer, visible evidence ranges,
  strategy, and scope provenance after successful conversational completion;
- show explicit progress/failure in its existing lean window.

No EVW schema work is authorized. If current tables cannot store a new optional
display field, omit that local persistence and report it; do not migrate schema
inside this phase.

## Removed client responsibilities

Delete from the Python runtime path:

- capabilities calls and capability dataclasses;
- whole-versus-window decision;
- transcript token/model-budget accounting;
- retrieval-term orchestration;
- window planning and window model calls;
- client evidence-ledger construction/synthesis;
- client provider retry/backoff/circuit policy;
- provider/model/context/prompt/batch controls;
- public gateway methods for removed server endpoints.

The existing transient conversational session/retry/resume implementation is
removed when the unified server path is wired. The server owns retries during
one stream. The Python UI may offer only a user-initiated complete resubmission
after terminal failure; it must say that this starts a new paid request.

## Client settings

The only remote setting in the Python client is `server_url`. Local settings
remain local. The client does not display or cache server model configuration.

## Keyword expansion

Send the query to `/v1/keyword-expansion`, receive strict terms, then run local
scoped FTS5. A server error ends keyword expansion noisily; there is no fallback
to raw query unless the user explicitly chooses ordinary FTS5.

## Conversational analysis

For the active narrowed scope, perform one short read transaction that copies
ordered message identity/thread/timestamp/sender/text into ordinary Python
objects, then close the transaction. Send one `/v1/conversational-analysis`
request and consume NDJSON outside SQLite transactions.

Render every progress event. Treat `completed` as the only success and `failed`
or premature EOF as failure. On completion, re-read active scope identity; if
working corpus/generation/scope changed while the request ran, display the
answer but refuse persistence with a noisy stale-scope message. Otherwise
validate all returned message/range IDs against the submitted local set and
persist final visible history in one short write transaction.

The client does not revalidate model-output schemas or ledger bijection; those
are server contracts. It validates only local ownership/scope before storing.

## Embeddings

Read missing active-corpus messages into ordinary objects and send one complete
`/v1/embeddings` workload. Do not divide by server model batch size. Consume
streamed vector batches, validate profile/dimensions/finite vectors and local
message IDs, then commit each received vector batch in a short writer task.

The first `accepted` event supplies embedding profile, dimensions,
normalization, and model identity. Use it to select/rebuild the local partition;
there is no capabilities request. If profile changes, explicitly mark prior
active-corpus embedding state stale and build the new partition.

Progress displays server completed/total counts and local committed counts.
On terminal failure or interrupted stream, retain committed vectors for the
same profile. A later user-initiated build resends only locally missing IDs;
the server itself remains stateless.

## Boundary tests

Tests must prove:

- server imports no `message_evidence_workstation` module;
- Python gateway contains no provider/model/prompt/window/retry policy;
- no client call to `/capabilities` or removed internal endpoints remains;
- no network request occurs while an EVW transaction is open;
- every local search and submitted corpus respects active working-corpus and
  optional narrowed scope;
- only terminal successful conversation results are persisted;
- streamed embedding batches survive a later server failure and resume by
  locally missing IDs without server job state.
