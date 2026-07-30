# Live GLM 5.2 validation

## Purpose

Prove that one real expensive conversational search returns useful work even
when synthesis structure is imperfect.

This is one acceptance run, not model tuning.

## Preconditions

Do not begin until all deterministic gates pass.

Verify and record:

- repository environment;
- active config version and schema;
- all five active operation assignments with secrets redacted;
- GLM 5.2 assigned to planning, extraction, compaction, and synthesis;
- active prompts are the new packet prompts;
- structured-output mode, temperature, token budgets, timeouts, retries, and
  context settings;
- semantic retrieval mode and embedding geometry;
- established revision 4 large working corpus is readable and embedding-ready;
- no unrelated request is active;
- fresh debug capture can be started;
- explicit server/client log and artifact paths.

Do not expose API keys.

## Exact run

Use:

```text
Show me fights about school.
```

Execute one ordinary public flow:

1. conversational plan;
2. one query-embedding workload;
3. exact local revision-scoped retrieval;
4. conversational analysis;
5. every planned extraction window;
6. compaction only if naturally required;
7. final synthesis;
8. terminal result.

Use the current intentionally configured window utilization. Do not modify it
merely to force a window count unless the local acceptance runner already
contains a documented temporary setting/restore mechanism. If that mechanism
is used, preserve and restore the prior value through normal config activation.

Existing configured operation retries may occur. Do not:

- automatically rerun the full sequence;
- change model/provider after seeing output;
- alter the question/plan/hits;
- hand-repair output;
- call a private synthesis helper;
- hide warnings;
- classify live quality as passed merely because HTTP completed.

## Required artifact directory

Create one timestamped directory under:

`.tmp/result-preserving-validation-live/`

Include:

- redacted run manifest;
- exact plan response;
- retrieval metadata;
- window plan and per-window outcomes/timing/usage;
- accepted/rejected/normalized ranges;
- unavailable-window diagnostics;
- synthesis raw response when allowed by active debug/result policy;
- exact completed public result;
- Markdown containing actual overview, high-probability results, divider,
  lower-probability results, unclassified evidence, unverified statements,
  warnings, complete ledger metadata, usage, and timing;
- debug-capture path and stopped/flushed state;
- server/client log paths;
- active and restored config versions.

Do not copy API keys or full corpus transcripts into the report.

## Review

For diagnostic comparison only, review the provisional-positive dates:

```text
2023-03-28
2023-11-13
2024-06-26
2024-07-10
2025-07-16
2025-08-04
2026-07-01
```

These values never enter production prompts, validators, result assembly, or
ordinary deterministic product fixtures.

Report:

- provisional-positive recall;
- evidence found outside semantic suggestions;
- high/lower/unclassified counts;
- every fabricated/unknown source reference;
- whether every validated extraction range remained inspectable;
- whether readable synthesis reached the client;
- whether any warning incorrectly became a failed event;
- window/provider retries;
- compaction status;
- provider-reported/estimated token usage and elapsed time;
- practical answer quality, including overcollection and omission.

Overcollection is not an acceptance failure. Hidden lower-probability results,
discarded valid evidence, fabricated verified sources, or a thrown-away
readable answer are failures.

## External blocker

If credentials are unavailable or the configured provider remains externally
unavailable after configured attempts:

- complete all local work;
- record exact redacted provider error and request ID;
- stop capture/processes;
- mark only Gate K externally blocked;
- do not select another model/provider.

## Cleanup

- stop and flush debug capture;
- restore temporary config if changed;
- stop test processes;
- verify port/process state;
- verify EVW and WAL were not unexpectedly modified;
- run final deterministic regression, compile, boundaries, residue scan, and
  `git diff --check`;
- finish execution log and closeout report.

