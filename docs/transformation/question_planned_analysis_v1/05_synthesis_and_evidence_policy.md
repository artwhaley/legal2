# Synthesis and evidence policy

## Planning prompt

The v4 `analysis_planning` seed prompt must instruct the model to:

- faithfully operationalize the user's question;
- define ambiguous concepts in ordinary, general-purpose terms;
- include indirect manifestations likely to matter;
- distinguish what answers the question from merely related material;
- create broad semantic retrieval queries without inventing corpus-specific
  names or events;
- state inclusion and exclusion criteria;
- specify what the final answer should deliver;
- expose interpretive assumptions;
- avoid legal conclusions;
- never add a generic requirement to collect contradictory evidence;
- return only the strict planning object.

The prompt must not contain the words or definitions from the current
school-fight test except inside the admin's clearly synthetic paid-test payload.

The active prompt remains fully editable in admin and takes effect on the next
planning request after draft validation and activation.

## Extraction prompt

Replace the current global instruction to capture every supporting,
contradicting, weak, or qualifying passage.

The extraction prompt must instead say:

- inspect every message in the assigned window;
- use the frozen analysis plan as the definition of responsiveness;
- retrieval suggestions are fallible attention aids only;
- return every passage that directly or plausibly helps answer the plan;
- include borderline candidates when uncertainty is genuine and explain why;
- do not include a passage merely because it is contradictory, cooperative,
  emotional, or generally on-topic unless the plan makes that quality
  responsive;
- preserve exact opaque IDs and thread boundaries;
- return an empty range list when no passage plausibly answers the plan.

This deliberately favors candidate recall. It does not ask extraction to make
the final answer-relevance decision.

## Compaction prompt

Compaction receives the frozen plan and preserves every accepted range ID once
and in order.

It summarizes distinctions relevant to the plan but does not assign final
dispositions. Remove disposition instructions and output fields from
compaction.

Compaction remains loud, conditional on measured synthesis context overflow,
and unable to mutate the canonical ledger.

## Synthesis prompt

Synthesis receives:

- original question;
- exact frozen analysis plan;
- complete coverage report;
- evidence-validation summary;
- complete ledger metadata;
- exact records or highest-level compaction summaries.

It must:

1. answer the plan rather than summarize the ledger;
2. create structured findings supported by accepted range IDs;
3. classify every accepted range exactly once;
4. use `direct_evidence` for passages that materially answer the plan;
5. use `useful_context` only when a passage helps explain direct evidence;
6. use `not_responsive` for candidates that do not answer the plan;
7. omit `not_responsive` material from the answer narrative;
8. avoid presenting cooperative or merely related passages as conflict unless
   the plan asks for that;
9. preserve uncertainty and the explicit partial-validation warning;
10. never invent evidence, IDs, dates, speakers, or conclusions.

If there is accepted evidence but no direct evidence, synthesis returns no
findings and clearly says the supplied corpus did not establish a responsive
answer. If range validation was partial, the answer must state that malformed
candidate ranges were excluded and completeness may be affected.

## Categorical relevance, not ranking

Do not add:

- 0-1 confidence;
- 1-5 relevance;
- probability;
- model-generated evidence rank;
- top-N answer evidence;
- threshold filtering.

The three dispositions are intentionally categorical and auditable.

Retrieval distance and RRF order remain server diagnostics for attention
suggestions. They never control whether accepted evidence survives or whether
synthesis may use it.

## Structural synthesis validation

Deterministically validate:

- exact response schema;
- nonblank answer and summary;
- exact ordered disposition bijection;
- allowed disposition literals;
- valid finding IDs;
- no duplicate IDs in a finding;
- at least one direct-evidence ID per finding;
- no not-responsive ID in a finding;
- zero direct evidence implies zero findings;
- every finding statement is nonblank.

Do not attempt semantic repair of a bad synthesis response. Existing configured
retries may run visibly; otherwise fail.

## Final answer and ledger

The answer is the user-facing analysis. The ledger is the audit trail.

All accepted ranges remain in the ledger, including `not_responsive`. The
ledger may be sorted only in canonical range-ID order. The final answer may
organize findings as required by the plan, commonly chronologically or by
theme.

Structured findings make synthesis behavior reviewable without forcing every
candidate range into the prose answer.

## Quality proof

The target is not a particular evidence count.

For the established school-conflict diagnostic:

- high-recall extraction may retain cooperative school passages;
- synthesis must not label cooperative logistics as direct conflicts;
- all known responsive conflict ranges found by extraction must remain
  available and should be classified direct evidence;
- contextual passages may be classified useful context only with a specific
  rationale;
- the answer must cite direct ranges and answer the question;
- no production prompt, validator, or test fixture may hard-code the known
  dates or corpus language.

