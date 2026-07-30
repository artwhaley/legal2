# Contracts and configuration

All request, response, event, and model-output objects are strict: required
fields are required, extras are forbidden, scalar coercion is disabled, and
nonblank strings are trimmed only where this file explicitly says the server
normalizes model output.

Maximum string lengths used below are contract limits and also make retrieval
prompt reservation computable:

- question: 20,000 characters;
- query text: 512 characters;
- request/plan/query/message/thread IDs: 512 characters;
- maximum extracted queries: 20.

Existing EVW message IDs fit these limits. Exceeding a limit fails validation;
do not truncate.

## Product endpoint 1: keyword expansion

`POST /v1/keyword-expansion` remains unchanged.

It remains independent of conversational retrieval and local FTS5 continues to
use it only when the client explicitly invokes keyword-expanded search.

## Product endpoint 2: conversational retrieval plan

Add:

```http
POST /v1/conversational-retrieval-plan
Content-Type: application/json
```

Request:

```json
{
  "request_id": "UUID",
  "question": "When did we fight about school?"
}
```

Response:

```json
{
  "request_id": "UUID",
  "config_version": 13,
  "retrieval_plan_id": "UUID",
  "compatibility_fingerprint": "64 lowercase hex characters",
  "queries": [
    {
      "query_id": "q0001",
      "text": "fight about school"
    }
  ],
  "embedding": {
    "embedding_profile_id": "server profile ID",
    "artifact_fingerprint": "server artifact fingerprint",
    "dimensions": 384,
    "normalization": "unit_l2"
  },
  "search_policy": {
    "top_k_per_query": 100,
    "fusion_method": "reciprocal_rank_fusion",
    "rrf_constant": 60,
    "maximum_prompt_suggestion_messages": 40
  },
  "usage": {
    "input_tokens": 100,
    "output_tokens": 20,
    "source": "provider_reported",
    "estimated_cost": null,
    "cost_complete": false,
    "currency": "USD"
  }
}
```

Behavior:

- Call `retrieval_terms` once with only the question.
- The strict model output remains `{"terms":["..."]}` with 1-20 strings.
- Normalize model terms by trimming, discard blank terms, and deduplicate
  case-insensitively while preserving first occurrence.
- If normalization leaves no term, fail `RETRIEVAL_PLAN_EMPTY`; do not derive
  fallback terms.
- Assign `q0001` onward in returned order.
- The endpoint is a normal JSON response, not NDJSON. It is one small provider
  call; existing provider progress remains visible in structured/debug logs.
- Return the active prepared embedding runtime's actual profile/fingerprint
  and geometry. Do not load a second embedding model.
- Do not persist the plan.

The compatibility fingerprint is SHA-256 over canonical JSON containing:

- normalized question;
- ordered query IDs and text;
- non-secret resolved `retrieval_terms` operation configuration;
- actual embedding artifact fingerprint, dimensions, and normalization;
- `top_k_per_query`;
- RRF method and constant;
- maximum prompt suggestion messages.

Do not include `retrieval_assistance_mode` or unrelated active configuration.
This permits one frozen plan to be reused across the terms-only and semantic
A/B configurations when every retrieval-relevant setting is identical.

The analysis endpoint recomputes and compares this fingerprint. It is an
integrity/staleness check, not authentication.

## Product endpoint 3: conversational analysis

The request retains question plus complete working-corpus messages and adds one
required nullable field:

```json
{
  "request_id": "UUID",
  "question": "When did we fight about school?",
  "working_corpus": {
    "scope_id": "opaque client scope",
    "messages": [
      {
        "message_id": "source:1",
        "thread_id": "thread",
        "timestamp": "2026-01-01T00:00:00Z",
        "sender": "Person",
        "text": "Message"
      }
    ]
  },
  "retrieval_assistance": {
    "retrieval_plan_id": "UUID",
    "plan_config_version": 13,
    "compatibility_fingerprint": "64 lowercase hex characters",
    "queries": [
      {
        "query_id": "q0001",
        "text": "fight about school"
      }
    ],
    "embedding_profile_id": "server profile ID",
    "embedding_artifact_fingerprint": "server artifact fingerprint",
    "dimensions": 384,
    "normalization": "unit_l2",
    "hits": [
      {
        "query_id": "q0001",
        "message_id": "source:1",
        "rank": 1,
        "distance": 0.183
      }
    ]
  }
}
```

`retrieval_assistance` must be present as either `null` or the exact object.

Mode invariants:

- `disabled`: assistance must be `null`.
- `terms_only`: assistance is required and `hits` must be `[]`.
- `semantic_ranges`: assistance is required and `hits` must be nonempty.

The Python diagnostic runner retains the complete frozen candidate pool outside
the request for its terms-only arm, then sends that pool for semantic arms.

Validation:

- question and ordered query list must reproduce the fingerprint under current
  compatible settings;
- stale/incompatible plan: HTTP 409 `RETRIEVAL_PLAN_STALE`;
- embedding profile/fingerprint/geometry mismatch: HTTP 409
  `RETRIEVAL_GEOMETRY_MISMATCH`;
- every hit query ID must exist;
- every hit message ID must exist exactly once in the supplied corpus;
- query/message pairs must be unique;
- rank must be positive, unique per query, and contiguous from 1 through the
  number of supplied hits for that query;
- distance must be finite and nonnegative;
- each query may contain no more than active `top_k_per_query` hits;
- total hits may not exceed `query_count * top_k_per_query`;
- violation is a strict 4xx error; never truncate candidates.

## Final conversational result

Both one-window and multi-window analysis return:

```json
{
  "answer": "complete answer",
  "answer_summary": "short summary",
  "strategy": "single_window_ledger",
  "evidence_ledger": [],
  "uncertainties": [],
  "coverage": {
    "message_count": 12402,
    "window_count": 1,
    "evidence_range_count": 0
  },
  "retrieval_diagnostics": {
    "mode": "semantic_ranges",
    "query_count": 5,
    "raw_hit_count": 500,
    "unique_candidate_message_count": 420,
    "selected_suggestion_message_count": 40,
    "suggestion_range_count": 32,
    "final_ranges_overlapping_suggestions": 7,
    "final_ranges_outside_suggestions": 8,
    "used_ranges_overlapping_suggestions": 5,
    "used_ranges_outside_suggestions": 4,
    "suggestions_without_final_evidence": 25
  },
  "ledger_processing": {
    "direct_synthesis_input_tokens": 63514,
    "synthesis_usable_input_tokens": 184870,
    "compaction_applied": false,
    "compaction_levels": 0,
    "compaction_group_calls": 0
  },
  "usage": {}
}
```

`strategy` is exactly `single_window_ledger` or `multi_window_ledger`.

All original evidence-ledger records remain in `evidence_ledger`, including
`redundant` and `not_material` dispositions.

Overlap means ordinal interval intersection within the same thread. Suggestion
and evidence range endpoints are resolved against the supplied corpus order.

## Conversational stream events

Keep strict envelope sequencing, `queued`, `retry_wait`, `heartbeat`, `failed`,
and `completed`. Remove:

- `whole_started`;
- `whole_completed`;
- `retrieval_terms_started` from analysis;
- `retrieval_terms_completed` from analysis;
- `ledger_reduction_started`;
- `ledger_reduction_completed`.

Add or revise these exact progress events:

```text
accepted
accounting_completed
retrieval_assistance_accepted
retrieval_suggestions_built
window_plan_created
window_started
window_completed
ledger_built
ledger_synthesis_preflight
ledger_compaction_required               conditional
ledger_compaction_group_started          conditional/repeated
ledger_compaction_group_completed        conditional/repeated
ledger_compaction_level_completed        conditional/repeated
ledger_compaction_completed              conditional
ledger_synthesis_started
ledger_synthesis_completed
retrieval_overlap_completed
completed
```

New event payloads:

```text
retrieval_assistance_accepted:
  mode, query_count, raw_hit_count, compatibility_fingerprint

retrieval_suggestions_built:
  unique_candidate_message_count, selected_suggestion_message_count,
  suggestion_range_count, unselected_candidate_message_count

window_plan_created:
  strategy, window_count, message_count, hard_input_tokens,
  target_input_tokens, utilization_percent,
  retrieval_reserve_tokens, window_plan_hash

window_started:
  existing fields plus suggestion_range_count

ledger_synthesis_preflight:
  evidence_range_count, evidence_message_count,
  required_input_tokens, usable_input_tokens, excess_input_tokens,
  direct_fit

ledger_compaction_required:
  evidence_range_count, evidence_message_count,
  required_input_tokens, usable_input_tokens, excess_input_tokens,
  maximum_depth

ledger_compaction_group_started:
  level, group_id, group_index, group_count, covered_range_count

ledger_compaction_group_completed:
  level, group_id, group_index, group_count, covered_range_count,
  input_tokens, output_tokens, usage_source, estimated_cost

ledger_compaction_level_completed:
  level, group_count, covered_range_count

ledger_compaction_completed:
  levels, group_calls, original_range_count, covered_range_count,
  final_synthesis_input_tokens

retrieval_overlap_completed:
  the count fields from final retrieval_diagnostics
```

All payload field sets remain exact in server and Python client validators.

## Active configuration v3

Increment `CONFIG_SCHEMA_VERSION` from 2 to 3.

Final chat operations:

```text
keyword_expansion
retrieval_terms
window_evidence_extraction
ledger_compaction
ledger_synthesis
```

Delete `whole_corpus_answer`. Rename `ledger_reduction` to
`ledger_compaction` throughout active runtime, schemas, prompts, accounting,
admin, events, and tests.

Global settings:

```text
retrieval_assistance_mode:
  disabled | terms_only | semantic_ranges

retrieval_top_k_per_query:
  integer, 1..1000, default 100

retrieval_maximum_prompt_suggestion_messages:
  integer, 1..500, default 40

retrieval_rrf_constant:
  integer, 1..1000, default 60

ledger_compaction_max_depth:
  integer, 1..8, migrated/default 4
```

Keep existing window utilization, maximum concurrent windows, stream
heartbeat, request ceilings, provider, model-profile, operation, retry,
accounting, and embedding settings.

The calculated retrieval reserve is read-only and derived at validation/runtime;
it is not stored as an administrator guess.

## Control-store migration

Perform one explicit atomic control-schema migration:

- convert every stored configuration version to schema v3;
- remove `whole_corpus_answer` assignment;
- rename `ledger_reduction` assignment to `ledger_compaction` while preserving
  its model profile, prompt text, timeouts, retries, prices, and other fields;
- convert `retrieval_assistance_enabled=true` to `terms_only`;
- convert `false` to `disabled`;
- add retrieval numeric settings at specified defaults;
- rename `ledger_reduction_max_depth` to `ledger_compaction_max_depth`;
- preserve active/draft/version identity, provider secrets, audit, and usage;
- record a content-free migration audit entry;
- fail startup and roll back byte-for-byte on any invalid mapping.

After migration, runtime code reads only schema v3. Do not retain schema-v2
aliases or dual operation lookup.

