# Contracts and configuration

All request, response, event, and model-output objects are strict:

- required fields are required;
- extra fields are forbidden;
- scalar coercion is disabled;
- strings are bounded and nonblank;
- no response defaults are inserted;
- no compatibility aliases survive migration.

Retain the existing ID, question, query, and request-size ceilings unless this
file explicitly adds a smaller list bound.

## Product endpoint 1

`POST /v1/keyword-expansion` is unchanged.

It remains independent from conversational planning. Its model operation
remains `keyword_expansion`.

## Product endpoint 2: conversational plan

Replace `/v1/conversational-retrieval-plan` with:

```http
POST /v1/conversational-plan
Content-Type: application/json
```

Request:

```json
{
  "request_id": "UUID",
  "question": "Show me fights about school."
}
```

### Model output

The `analysis_planning` provider call returns exactly:

```json
{
  "analysis_question": "Identify exchanges in which the participants disagreed, argued, accused one another, or sustained conflict about schooling or educational decisions.",
  "answer_objective": "Present the responsive exchanges with dates, participants, the subject of conflict, and what each side said.",
  "concepts": [
    {
      "label": "interpersonal conflict",
      "definition": "A disagreement, argument, accusation, heated exchange, or sustained competing position between participants.",
      "manifestations": [
        "direct argument",
        "accusations about educational responsibility",
        "sustained incompatible positions"
      ]
    }
  ],
  "inclusion_criteria": [
    "Schooling or education is a material subject of the conflict."
  ],
  "exclusion_criteria": [
    "Cooperative school planning without disagreement."
  ],
  "retrieval_queries": [
    "argument disagreement about school education",
    "accusations about homeschooling or educational responsibility"
  ],
  "answer_requirements": [
    "Organize responsive exchanges chronologically.",
    "Explain the competing positions and cite the supporting ranges."
  ],
  "interpretive_assumptions": [
    "The word fight includes substantive verbal conflict, not only physical fighting."
  ]
}
```

This example describes behavior; do not hard-code its school/fight language.

Exact bounds:

- `concepts`: 1..12;
- `manifestations` per concept: 1..12;
- `inclusion_criteria`: 1..20;
- `exclusion_criteria`: 0..20;
- `retrieval_queries`: 1..20;
- `answer_requirements`: 1..12;
- `interpretive_assumptions`: 0..12;
- each list must contain unique values case-insensitively;
- every provider string must already equal its trimmed value; reject leading
  or trailing whitespace rather than silently rewriting the plan;
- each string uses the existing maximum query length except
  `analysis_question`, `answer_objective`, and concept `definition`, which use
  the existing maximum question length.

The model does not assign concept or query IDs. The server assigns query IDs
`q0001` onward in returned order. The server does not derive fallback queries.

Use two explicit server models:

- `AnalysisPlanningOutput` contains every provider field above, including
  `retrieval_queries`;
- `FrozenAnalysisPlan` contains every provider field except
  `retrieval_queries`.

The server validates `AnalysisPlanningOutput`, copies its non-query fields
without paraphrase into `FrozenAnalysisPlan`, and converts only the ordered
query strings into server-ID-bearing `RetrievalQuery` objects. There is no
second planner or normalization model call.

### Public response

```json
{
  "request_id": "UUID",
  "config_version": 41,
  "analysis_plan_id": "UUID",
  "compatibility_fingerprint": "64 lowercase hex characters",
  "analysis_plan": {
    "analysis_question": "Identify the exchanges that answer the user's question.",
    "answer_objective": "Present each responsive exchange and explain what it establishes.",
    "concepts": [
      {
        "label": "responsive exchange",
        "definition": "An exchange that materially bears on the requested subject.",
        "manifestations": ["direct discussion", "indirect but material discussion"]
      }
    ],
    "inclusion_criteria": ["The passage materially answers the requested question."],
    "exclusion_criteria": ["The passage is merely topically adjacent."],
    "answer_requirements": ["State the responsive findings and cite their ranges."],
    "interpretive_assumptions": []
  },
  "retrieval_queries": [
    {
      "query_id": "q0001",
      "text": "argument disagreement about school education"
    }
  ],
  "embedding": {
    "embedding_profile_id": "server profile ID",
    "artifact_fingerprint": "server artifact fingerprint",
    "dimensions": 384,
    "normalization": "unit_l2"
  },
  "search_policy": {
    "mode": "semantic_ranges",
    "top_k_per_query": 100,
    "fusion_method": "reciprocal_rank_fusion",
    "rrf_constant": 60,
    "maximum_prompt_suggestion_messages": 40
  },
  "usage": {
    "input_tokens": 100,
    "output_tokens": 200,
    "source": "provider_reported",
    "estimated_cost": null,
    "cost_complete": false,
    "currency": "USD"
  }
}
```

`analysis_plan` omits `retrieval_queries` because the public response exposes
the same ordered values with server-assigned IDs in `retrieval_queries`.

When `search_policy.mode` is `none`:

- `embedding` is exactly `null`;
- the server does not prepare/load an embedding runtime for this request;
- the client does not call `/v1/embeddings`.

When mode is `semantic_ranges`, `embedding` is required and reflects the
actually prepared server embedding runtime.

### Fingerprint

The compatibility fingerprint is SHA-256 over canonical JSON containing:

- normalized original question;
- the complete validated `analysis_plan`;
- ordered retrieval query IDs and text;
- non-secret resolved `analysis_planning` operation configuration;
- search policy, including mode;
- actual embedding profile/fingerprint/geometry when semantic mode is active,
  otherwise `embedding: null`.

Do not include unrelated extraction/synthesis settings. Those are captured
independently at analysis ingress. This fingerprint is an integrity/staleness
check, not authentication.

## Product endpoint 3: conversational analysis

Replace `retrieval_assistance` with one required `analysis_context` object:

```json
{
  "request_id": "UUID",
  "question": "Show me fights about school.",
  "working_corpus": {
    "scope_id": "opaque client scope",
    "messages": [
      {
        "message_id": "source:1",
        "thread_id": "thread",
        "timestamp": "2026-01-01T00:00:00Z",
        "sender": "Person",
        "text": "Example message."
      }
    ]
  },
  "analysis_context": {
    "analysis_plan_id": "UUID",
    "plan_config_version": 41,
    "compatibility_fingerprint": "64 lowercase hex characters",
    "analysis_plan": {
      "analysis_question": "Identify the exchanges that answer the user's question.",
      "answer_objective": "Present each responsive exchange and explain what it establishes.",
      "concepts": [
        {
          "label": "responsive exchange",
          "definition": "An exchange that materially bears on the requested subject.",
          "manifestations": ["direct discussion", "indirect but material discussion"]
        }
      ],
      "inclusion_criteria": ["The passage materially answers the requested question."],
      "exclusion_criteria": ["The passage is merely topically adjacent."],
      "answer_requirements": ["State the responsive findings and cite their ranges."],
      "interpretive_assumptions": []
    },
    "retrieval_queries": [
      {
        "query_id": "q0001",
        "text": "argument disagreement about school education"
      }
    ],
    "embedding": {
      "embedding_profile_id": "server profile ID",
      "artifact_fingerprint": "server artifact fingerprint",
      "dimensions": 384,
      "normalization": "unit_l2"
    },
    "search_policy": {
      "mode": "semantic_ranges",
      "top_k_per_query": 100,
      "fusion_method": "reciprocal_rank_fusion",
      "rrf_constant": 60,
      "maximum_prompt_suggestion_messages": 40
    },
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

Mode invariants:

- `none`: `embedding` is null and `hits` is empty;
- `semantic_ranges`: `embedding` is non-null and `hits` is nonempty.

The analysis endpoint validates:

- exact plan and query schema;
- question/fingerprint/current planning compatibility;
- exact echoed policy;
- geometry when semantic mode is active;
- all existing query/rank/distance/corpus membership invariants;
- no duplicate query/message pair;
- no client-added or client-edited query.

Failures use:

- HTTP 409 `ANALYSIS_PLAN_STALE` for plan/question/config/policy mismatch;
- HTTP 409 `RETRIEVAL_GEOMETRY_MISMATCH` for embedding mismatch;
- strict 4xx request validation for malformed hits or context.

Never truncate or silently ignore client data.

## Internal model user objects

Every extraction call receives exactly:

```json
{
  "task": "window_evidence_extraction",
  "question": "original question",
  "analysis_plan": {
    "analysis_question": "validated planned question",
    "answer_objective": "validated answer objective",
    "concepts": [
      {
        "label": "validated concept",
        "definition": "validated definition",
        "manifestations": ["validated manifestation"]
      }
    ],
    "inclusion_criteria": ["validated inclusion"],
    "exclusion_criteria": [],
    "answer_requirements": ["validated answer requirement"],
    "interpretive_assumptions": []
  },
  "retrieval_queries": [
    {
      "query_id": "q0001",
      "text": "validated retrieval query"
    }
  ],
  "suggestion_ranges": [],
  "window_id": "w000001",
  "messages": [
    {
      "message_id": "source:1",
      "thread_id": "thread",
      "timestamp": "2026-01-01T00:00:00Z",
      "sender": "Person",
      "text": "Example message."
    }
  ]
}
```

Every compaction call receives the existing fields plus the exact same
validated `analysis_plan` object.

Every synthesis call receives:

```json
{
  "task": "ledger_synthesis",
  "question": "original question",
  "analysis_plan": {
    "analysis_question": "validated planned question",
    "answer_objective": "validated answer objective",
    "concepts": [
      {
        "label": "validated concept",
        "definition": "validated definition",
        "manifestations": ["validated manifestation"]
      }
    ],
    "inclusion_criteria": ["validated inclusion"],
    "exclusion_criteria": [],
    "answer_requirements": ["validated answer requirement"],
    "interpretive_assumptions": []
  },
  "coverage_report": [],
  "evidence_validation": {},
  "ledger_metadata": [],
  "records_or_highest_level_summaries": []
}
```

No stage reconstructs or paraphrases the plan.

## Extraction model envelope

Remove redundant `no_relevant_evidence`. The exact top-level model response is:

```json
{
  "window_id": "w000001",
  "evidence_ranges": [
    {
      "thread_id": "thread",
      "start_message_id": "source:1",
      "end_message_id": "source:7",
      "summary": "What the passage shows.",
      "relevance": "How the passage answers or may answer the analysis plan."
    }
  ],
  "uncertainties": []
}
```

An empty `evidence_ranges` list is the only no-evidence representation.
Range-level parsing and semantic validation are defined in file 04.

## Synthesis model output

Replace disposition literals and add structured findings:

```json
{
  "answer": "Complete answer.",
  "answer_summary": "Short answer.",
  "findings": [
    {
      "statement": "A responsive finding.",
      "range_ids": ["r000001", "r000004"]
    }
  ],
  "range_dispositions": [
    {
      "range_id": "r000001",
      "disposition": "direct_evidence",
      "rationale": "Directly establishes the finding."
    },
    {
      "range_id": "r000002",
      "disposition": "not_responsive",
      "rationale": "Cooperative planning does not answer the conflict question."
    }
  ],
  "uncertainties": []
}
```

Disposition is exactly:

- `direct_evidence`;
- `useful_context`;
- `not_responsive`.

Finding validation:

- finding statements are nonblank;
- range IDs are unique within a finding;
- every cited ID exists exactly once in the canonical ledger;
- every finding cites at least one range classified `direct_evidence`;
- a finding may additionally cite `useful_context`;
- a finding may never cite `not_responsive`;
- zero findings is valid only when zero ranges are classified
  `direct_evidence`.

The complete disposition list remains an exact ordered bijection with accepted
ledger range IDs.

## Compaction output

Remove `range_dispositions` from `LedgerCompactionOutput`.

Compaction returns only:

```json
{
  "group_id": "g01-000001",
  "summary": "Complete group summary preserving the plan-relevant distinctions.",
  "covered_range_ids": ["r000001"],
  "uncertainties": []
}
```

Only final synthesis classifies answer relevance.

## Final result additions

The following is the v4 field fragment; unchanged v3 coverage, retrieval,
ledger-processing, and usage objects retain their existing strict subfields:

```json
{
  "completion_status": "partial_evidence_validation",
  "answer": "...",
  "answer_summary": "...",
  "findings": [],
  "strategy": "multi_window_ledger",
  "evidence_ledger": [
    {
      "range_id": "r000001",
      "window_id": "w000001",
      "source_range_index": 0,
      "thread_id": "thread",
      "start_message_id": "source:1",
      "end_message_id": "source:7",
      "summary": "...",
      "relevance": "...",
      "normalizations": [],
      "disposition": "direct_evidence",
      "rationale": "..."
    }
  ],
  "evidence_validation": {
    "status": "partial",
    "accepted_range_count": 3,
    "rejected_range_count": 1,
    "normalized_range_count": 0,
    "rejected_ranges": [
      {
        "window_id": "w000006",
        "range_index": 3,
        "code": "UNKNOWN_MESSAGE_ID",
        "message": "Range references an ID absent from its supplied window.",
        "declared_thread_id": "julie_kramer",
        "start_message_id": "source:5131",
        "end_message_id": "source:5141"
      }
    ]
  },
  "uncertainties": [],
  "coverage": {},
  "retrieval_diagnostics": {},
  "ledger_processing": {},
  "usage": {}
}
```

`completion_status` is exactly `complete` or
`partial_evidence_validation`. `evidence_validation.status` is exactly
`complete` or `partial`, and the two fields must agree.

Rejected-range diagnostic ID fields are nullable only when the malformed range
did not provide a string value. The diagnostic contains no transcript text,
summary, relevance, or model reasoning.

Rename retrieval diagnostic fields:

- `used_ranges_overlapping_suggestions` becomes
  `answer_relevant_ranges_overlapping_suggestions`;
- `used_ranges_outside_suggestions` becomes
  `answer_relevant_ranges_outside_suggestions`.

Answer-relevant means `direct_evidence` or `useful_context`.

## Stream contract

Replace `retrieval_assistance_accepted` with:

```text
analysis_plan_accepted:
  analysis_plan_id, compatibility_fingerprint, concept_count,
  retrieval_query_count, retrieval_mode
```

Keep existing events and add:

```text
evidence_validation_completed:
  window_count, accepted_range_count, rejected_range_count,
  normalized_range_count, status
```

Revise `window_completed` payload:

```text
window_id, window_index, window_count,
accepted_range_count, rejected_range_count, normalized_range_count,
validation_status,
input_tokens, output_tokens, usage_source, estimated_cost
```

`validation_status` is `complete` or `partial`.

`completed` remains the terminal success event and carries the exact final
result, including partial status. Structural failures remain terminal
`failed`.

## Configuration schema v4

Increment `CONFIG_SCHEMA_VERSION` from 3 to 4.

Final model operations:

```text
keyword_expansion
analysis_planning
window_evidence_extraction
ledger_compaction
ledger_synthesis
```

Final local retrieval mode:

```text
retrieval_assistance_mode:
  none | semantic_ranges
```

Migration from v3:

- rename operation `retrieval_terms` to `analysis_planning`;
- preserve its model-profile assignment, temperature, reasoning settings,
  output budget, timeout, concurrency, retry, circuit, and accounting settings;
- replace its system prompt with the new v4 planning prompt because the old
  prompt and output schema are incompatible;
- map `disabled` and `terms_only` to `none`;
- map `semantic_ranges` to `semantic_ranges`;
- preserve all retrieval numeric policy settings;
- preserve providers, encrypted secrets, model profiles, active/draft/version
  identity, audit, and usage;
- record one content-free migration audit entry;
- migrate atomically and roll back byte-for-byte on failure.

After migration, runtime code reads only v4. Old endpoint, operation, field,
mode, event, and disposition names may remain only in explicit migration tests
and historical documentation.
