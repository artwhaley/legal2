# Prompts, admin, and client behavior

## Window extraction prompt

Replace the active extraction prompt with one that retains current frozen-plan
and exhaustive-window guarantees and explicitly states:

- inspect every supplied message;
- retrieval suggestions are fallible attention aids only;
- return every passage that directly, plausibly, indirectly, or borderline
  helps answer the plan;
- overcollection is preferable to omission;
- uncertainty must be explained rather than used to suppress a range;
- exact message/thread IDs must be copied;
- no result ranking or final relevance category is assigned during extraction;
- an empty list is allowed only when nothing plausibly answers the plan.

The prompt must not contain:

- `direct_evidence`;
- `useful_context`;
- `not_responsive`;
- a generic instruction to seek contradictory evidence;
- a fixed result count;
- a score or confidence threshold.

## Ledger compaction prompt

Preserve:

- every original range ID;
- canonical order;
- uncertainty;
- no final relevance classification.

Clarify that compaction failure never authorizes omission. No probability
category is assigned during compaction.

## Synthesis prompt

The active synthesis prompt must say:

- answer the exact user question using the frozen plan and available evidence;
- prefer overcollection to omission;
- return high-probability results first;
- return lower-probability/borderline/context-dependent results afterward;
- lower-probability results remain user-visible;
- cite only supplied exact range IDs;
- paraphrase rather than manufacture canonical message quotations;
- do not create or infer missing IDs;
- explain coverage/validation uncertainty;
- use the exact model-output schema from file 03;
- do not emit a separate disposition list.

The output categories describe likely responsiveness, not factual truth.

## Admin interface

Update the existing server-rendered admin rather than adding a second UI.

Required changes:

- explain the result-preserving policy in ordinary human language;
- explain high versus lower probability with practical examples;
- state that lower-probability results are never discarded;
- state that source IDs are mechanically verified;
- show the new synthesis model schema;
- remove every disposition/direct/context/not-responsive explanation;
- show content-free process metrics:
  - complete results;
  - complete-with-warning results;
  - partial results;
  - unavailable windows;
  - rejected ranges;
  - corrected ranges;
  - partial/unverified citations;
  - raw-synthesis fallbacks;
  - synthesis-unavailable ledger returns;
- preserve current model/prompt/reasoning/temperature/output/timeout/retry/
  structured-output controls and next-request activation;
- preserve temporary debug capture controls;
- add no no-op validation policy controls.

The return-everything policy is fixed product behavior, not configurable.

## Python test-equipment gateway

Replace the exact old result parser. It must accept only the new server
contract and reject old disposition-based result shapes.

The gateway verifies:

- monotonic event sequence;
- exact terminal completed/failed event;
- exact new status/answer-source/result/citation/warning shapes;
- verified IDs are a subset of reported IDs and canonical ledger IDs;
- unverified IDs never appear as verified navigation targets;
- high results precede lower results, which precede unclassified evidence;
- partial/completed-with-warning results are successful results.

The client must not repeat or reinterpret server validation policy.

## Python GUI

The Python GUI is test equipment for this phase. Change only what is needed to
exercise the server.

Render:

1. structured overview or raw answer, according to `answer_source`;
2. `High probability`;
3. a clear visual divider;
4. `Lower probability`;
5. `Unclassified candidates` as a labeled subsection under the lower-
   probability side of the divider;
6. `Unverified model statements`, only when present;
7. compact validation/coverage warnings;
8. complete evidence ledger/navigation.

Do not:

- show a critical failure popup for `complete_with_warnings` or `partial`;
- hide lower-probability results;
- navigate fabricated IDs;
- recalculate categories client-side;
- add Python-side model/provider/prompt/retry policy;
- persist debug/raw provider inputs in the EVW.

Elapsed time continues until the terminal event. Progress visibly reports
window retry/unavailable, synthesis received, validation warning, and ledger-
only partial completion.

## Visible history

Persist the visible user question and presented response only according to the
existing client history policy.

For raw nonconforming synthesis, persist the raw answer that was presented plus
its warning/status. Do not persist hidden provider calls, prompts, extraction
responses, or debug capture in the EVW.

## Scripts

Update live/experiment runners to:

- preserve raw synthesis on warnings;
- write structured high/lower/unclassified sections;
- report fabricated/partial citations;
- treat `complete_with_warnings` and `partial` as returned outcomes;
- fail their own acceptance gate only when the gate's explicit quality
  criteria fail, not because the server returned warnings;
- never automatically rerun an expensive live sequence.

Automated script tests use fake providers and no real API calls.
