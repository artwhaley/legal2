# Corpus-First Prompt Packing V1

Status: Approved for implementation  
Repository: `C:\Users\artwh\OneDrive\Documents\legal2`  
Scope: Server-side `window_evidence_extraction` provider payload construction

## 1. Binding outcome

Production must serialize every window-evidence extraction user object in a
single corpus-first order so an OpenAI-compatible provider can reuse the
largest stable request prefix when the same window is analyzed again:

1. `task`
2. `window_id`
3. `messages`
4. `question`
5. `analysis_plan`
6. `retrieval_queries`
7. `suggestion_ranges`

This is a wire-packing change only. All seven fields and their current values
remain present. No corpus message, retrieval query, suggestion, evidence
range, or model output may be dropped, capped, summarized, reordered within
its own collection, or otherwise changed by this work.

The old question-first extraction packing must cease to be a production path.
Do not add a feature flag, A/B toggle, compatibility mode, provider-specific
branch, or fallback to the old order.

## 2. Reason for the change

The current user JSON places query-dependent material before the window
messages:

```text
task -> question -> analysis_plan -> retrieval_queries -> suggestion_ranges
     -> window_id -> messages
```

That prevents prefix caching from reaching the corpus even when a later
request analyzes the exact same window. Corpus-first packing moves the stable
window identity and message stream ahead of query-dependent material without
changing the JSON object’s meaning or the model contract.

The completed investigations establish that:

- corpus-first packing can produce conformant GLM 5.2 extraction and synthesis
  results on both single-window and multi-window corpora;
- one six-window school-query run improved provisional known-result recall from
  5/7 to 7/7;
- a later 100K single-window sequence remained schema-valid for both a school
  query and a grandma query;
- corpus-first output can over-collect or create nested overlapping ranges;
- the configured NVIDIA NIM deployment did not report cache read/write/miss
  fields and showed no observable reuse in the 100K sequence.

The user accepts the output-quality risk and has chosen to proceed. Duplicate
range cleanup and lower-relevance precision will be handled separately through
prompt engineering. They are not blockers for this packing change.

## 3. Exact production contract

### 3.1 One authoritative constructor

Add one explicit helper dedicated to extraction user objects. A suitable
signature is:

```python
def _window_extraction_user(
    *,
    window_id: str,
    messages: Sequence[Mapping[str, Any]],
    question: str,
    analysis_plan: Mapping[str, Any],
    retrieval_queries: Sequence[Mapping[str, Any]],
    suggestion_ranges: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    ...
```

It must return a normal insertion-ordered Python dictionary with keys in this
exact order:

```python
{
    "task": "window_evidence_extraction",
    "window_id": window_id,
    "messages": list(messages),
    "question": question,
    "analysis_plan": dict(analysis_plan),
    "retrieval_queries": list(retrieval_queries),
    "suggestion_ranges": list(suggestion_ranges),
}
```

Use this helper everywhere the server constructs a
`window_evidence_extraction` user object. Do not retain direct `_user(...)`
construction for this operation.

Known call sites include:

- window-planning payload measurement in `plan_windows`;
- actual-payload post-planning fit checks;
- retrieval-reservation base and reserved payloads;
- every live single-window and multi-window extraction invocation;
- tests, fixtures, or debug probes that intentionally represent production
  packing.

Planning, fit checks, accounting, debug capture, and live provider execution
must all serialize the same authoritative object. There must not be one order
for token estimation and a different order on the wire.

### 3.2 Canonical serialization

Continue using the existing `canonical_json` implementation with
`sort_keys=False`. Do not enable alphabetical key sorting. Do not manually
concatenate unescaped JSON strings.

The provider wire request remains exactly two chat messages:

- the complete configured system prompt;
- one canonical JSON user message created from the authoritative extraction
  object.

The response schema, structured-output mode, model, temperature, maximum output
tokens, timeouts, and retry policy remain unchanged.

### 3.3 Stable prefix definition

For this version, the cache-eligible stable extraction prefix consists of:

```text
configured extraction system prompt
+ task
+ window_id
+ messages
```

The prefix is reusable only when those bytes are identical. In particular:

- the extraction system prompt must be unchanged;
- the window ID must be unchanged;
- message order, IDs, metadata, text, and JSON escaping must be unchanged;
- the provider must support prefix caching and retain the earlier entry.

Do not claim a cache hit merely because the same EVW revision was selected.
Different window boundaries or message bytes produce a different prefix.

### 3.4 Window planning boundary

Keep the existing deterministic window-planning algorithm and budget rules.
Do not redesign partitioning to force query-independent boundaries in this
ticket. The field-order change must be applied to the planner’s exact payload
measurement so any tokenization difference is honestly included.

The implementation must continue to prove:

- every working-corpus message appears in exactly one planned window;
- chronological and thread-contiguity rules are preserved;
- actual generated extraction payloads fit the configured target;
- retrieval reservation remains explicit and complete;
- single-window and multi-window strategies retain their existing semantics.

If two queries naturally produce the same window identity and messages, their
serialized extraction user messages must match byte-for-byte through the end
of `messages`. If planning produces different windows, normal execution
continues; cache ineligibility is not an error.

## 4. Observability and cache accounting

Retain the implemented cache-accounting fields:

- `cache_read_input_tokens`;
- `cache_write_input_tokens`;
- `cache_miss_input_tokens`;
- `cache_usage_reported` / aggregated provider-reported row count.

Continue accepting the already supported OpenAI-style, DeepSeek-style, and
Anthropic-style usage field names. Provider omission of cache fields is normal
telemetry absence, not a request failure and not proof of a miss.

For each extraction provider attempt, existing content-free operational/debug
metadata must make the following reviewable without logging corpus content:

- operation is `window_evidence_extraction`;
- window ID and window-plan hash;
- packing strategy identifier `corpus_first_v1`;
- provider/model/config version;
- input/output tokens;
- provider-reported cache counters and whether they were reported.

If the existing event contract cannot accept `packing_strategy` or
`window_plan_hash` without a public contract expansion, keep them in internal
operational/debug records. Do not broaden public conversation stream contracts
solely for this change.

Do not add a validation gate around cache metadata. A missing counter, absent
hash comparison, or incomplete status message must never fail an otherwise
valid conversational analysis.

## 5. Explicitly unchanged behavior

This implementation must not change:

- public HTTP request, response, or NDJSON event contracts;
- analysis planning prompts or output;
- extraction system-prompt text;
- ledger synthesis packing or system-prompt text;
- compaction behavior;
- retrieval fusion, semantic-strength selection, or suggestion construction;
- window concurrency, retry, timeout, cancellation, or stop propagation;
- ledger validation, salvage, range identity, or final assembly;
- completion status and warning policy;
- model/provider assignments or credentials;
- usage pricing or cost calculations;
- Flutter or Python client behavior;
- EVW schema, corpus membership, embeddings, search, or transcript behavior.

Do not add a result cache, versioned answer cache, response reuse, speculative
preload, hidden retry, or provider fallback.

## 6. Quality issues intentionally deferred

The following observed issues are real but outside this executor’s authority:

- nested or overlapping evidence ranges describing the same event;
- synthesis presenting two ranges from one continuous event as separate
  answers;
- lower-probability results that are merely adjacent, cooperative, or about a
  third party;
- prompt definitions that broaden “fight,” “school,” “grandma,” or other query
  concepts more than desired.

Do not introduce deterministic range merging, new relevance thresholds,
result suppression, prompt edits, or additional validation gates while
implementing this spec. Preserve all valid model output under the current
ledger rules. Those issues require a separate prompt/quality specification.

## 7. Required implementation tests

All automated tests must use fake/local providers and must make zero external
provider calls.

### 7.1 Exact key-order tests

Assert that the authoritative constructor returns exactly:

```python
[
    "task",
    "window_id",
    "messages",
    "question",
    "analysis_plan",
    "retrieval_queries",
    "suggestion_ranges",
]
```

Assert exact canonical serialized JSON for a small fixture including Unicode,
quotes, backslashes, and empty suggestion ranges.

### 7.2 Stable-prefix tests

Build two extraction objects with:

- identical window ID and messages;
- different questions;
- different frozen plans;
- different retrieval queries and suggestion ranges.

Prove their serialized user messages are byte-identical through the closing
bracket of `messages`, and differ only afterward. Prove changing any message
byte or the window ID breaks prefix equality.

### 7.3 All-call-site tests

Capture provider requests for:

- a 100K-like single-window analysis;
- a larger multi-window analysis;
- analysis with no semantic suggestions;
- analysis with retrieval queries and populated suggestion ranges.

For every extraction call, assert exact corpus-first key order and complete
field values. Assert planning/preflight token accounting used the identical
serialized object delivered to the provider.

Add a static residue assertion or focused source scan proving production no
longer directly constructs `window_evidence_extraction` with `question` before
`messages`.

### 7.4 Orchestration regression tests

Retain or extend tests proving:

- one-window analysis makes one extraction call and then synthesis;
- multi-window analysis processes every planned window and then synthesizes;
- every message appears exactly once across extraction calls;
- completion order cannot alter deterministic ledger range IDs;
- cancellation stops outstanding provider/window work;
- valid partial-range salvage behavior is unchanged;
- malformed provider output and provider failures remain visible;
- missing provider cache fields do not fail the request;
- reported cache fields are persisted and aggregated correctly.

### 7.5 Budget boundary tests

Exercise messages and retrieval reservations near the configured input target.
Prove the new serialized order is used for both planning and actual fit checks,
and that no message or suggestion is silently removed to make a payload fit.

## 8. Optional live smoke after automated gates

After all automated tests pass, the executor may run one authorized direct or
local production smoke using the existing 100K fixture:

1. complete the school query through synthesis;
2. immediately complete a different query against the same revision;
3. verify the extraction prefix hash/window identity;
4. record provider cache telemetry exactly as returned.

A provider-reported cache hit is not an acceptance requirement because the
configured NIM deployment has so far omitted cache accounting. A live failure
must remain visible and must not be retried silently.

Do not include corpus text, credentials, reasoning text, or raw provider bodies
in the execution log.

## 9. Acceptance gates

The change is complete only when all of the following are true:

1. One authoritative helper constructs every production extraction user
   object.
2. Every extraction payload uses the exact seven-key corpus-first order.
3. Planning, reservation, actual-fit checks, debug capture, and provider wire
   execution use the same serialized object.
4. No old question-first extraction construction remains in production.
5. All messages, queries, suggestions, and current model settings are
   preserved.
6. Single-window and multi-window orchestration tests pass.
7. Cache telemetry omission remains nonfatal and distinguishable from measured
   zero.
8. No public contract, client, EVW, prompt-text, synthesis, retry, or provider
   behavior changes beyond the approved packing order.
9. Full Python test suite passes with a workspace-local pytest temp directory.
10. Dirty-worktree inspection confirms unrelated user changes were preserved.

## 10. Executor protocol

Before editing:

1. Read repository `AGENTS.md` completely.
2. Record `git status --short`, current branch/HEAD, and the complete dirty
   baseline without modifying it.
3. Read this specification completely.
4. Inspect all extraction construction, planning, accounting, debug-capture,
   and relevant test call sites.

During implementation:

- use the existing dependencies and direct explicit flow;
- preserve unrelated dirty files;
- do not reset, clean, checkout, commit, push, deploy, or create a PR unless
  separately requested;
- do not call an external provider from automated tests;
- create `execution_log.md` beside this specification and record exact
  commands, outcomes, and any deviations there.

Required validation:

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.tmp\pytest-corpus-first
```

Also run focused extraction/orchestration/accounting tests first, compile all
changed Python files, inspect the final diff, and scan for obsolete
question-first construction.

At completion, write `closeout_report.md` beside this file containing:

- files changed and why;
- exact packing order implemented;
- focused and full test results;
- residue-scan result;
- cache telemetry behavior;
- any live smoke result, if performed;
- confirmation that deferred quality issues were not silently altered;
- confirmation that unrelated dirty work was preserved.

Do not restart the production server or client unless the user separately asks
the executor to do so.

## 11. Executor handoff prompt

```text
Implement the authoritative specification at:

C:\Users\artwh\OneDrive\Documents\legal2\docs\transformation\corpus_first_prompt_packing_v1\spec.md

Read AGENTS.md and the specification completely before editing. Preserve the
dirty worktree. Implement only the approved corpus-first extraction packing,
its observability, and its tests. Do not add a result cache, feature flag,
fallback, validation gate, prompt-quality cleanup, public contract expansion,
client change, or window-planning redesign. Run focused tests and the full
Python suite with a workspace-local pytest temp directory, inspect the final
diff, perform the required residue scan, and write the specified execution log
and closeout report. Do not restart applications unless separately instructed.
```
