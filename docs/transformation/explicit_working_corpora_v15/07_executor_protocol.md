# Executor Protocol

## Authority

Repository `AGENTS.md` and this packet are binding. This packet supersedes older
active-corpus, mutable-membership, corpus-partitioned-vector, positional-block,
and EVW-version requirements.

## Required discipline

1. Read all packet files before edits.
2. Maintain `execution_log.md` continuously.
3. Execute tickets in order and pass targeted gates.
4. Preserve unrelated dirty-worktree changes.
5. Use one explicit implementation path; delete obsolete paths.
6. Keep EVW transactions short and network-free.
7. Fail noisy with original cause.
8. Never select, migrate, retry, repair, truncate, detach evidence, discard
   vectors, or embed full data implicitly.
9. Do not modify server production behavior for local cache identity or
   clearing; the existing embeddings endpoint already supplies vectors and
   geometry.
10. Perform dependencies, builds, migrations, fixtures, and tests yourself.

Do not commit, push, deploy, reset, clean, or revert unless separately
instructed.

## Real-test standard

Forbidden:

- inserting ready revisions directly when testing build/publication;
- patching readiness checks;
- hardcoding whole/windowed results;
- using two EVWs to avoid revision selection;
- fake cache-hit counters without inspecting server workload;
- automatic cache clearing or model-change inference;
- storing provider/model/profile/version identity in v15;
- populating the full corpus to make cache tests easier;
- duplicating vectors per revision as a shortcut;
- global KNN followed by filtering;
- silently mapping legacy evidence slots;
- automatically dropping incompatible evidence;
- retaining old method aliases solely for tests;
- test-only branches in production.

## Decision hierarchy

When implementation details are not syntactically dictated:

1. preserve packet invariants;
2. choose the simplest explicit transaction/state flow;
3. prefer typed immutable records;
4. prefer deterministic validation over inference;
5. stop for a genuine contradiction rather than inventing compatibility.

The packet deliberately fixes the important architecture. Minor naming needed
only for local private helpers may follow repository conventions.

## Blockers

Continue autonomously until all local gates pass. Stop only for a genuine
contradiction, required user authority, unavailable sole-remaining live
credentials, or failure of the mandated exact-vector benchmark after measured
profiling. Record exact evidence and request the smallest decision.

## Completion

Requires:

- all tickets closed;
- all local gates green;
- validated one-EVW 100K/700K fixture;
- sparse embedding hit/miss proof;
- evidence migration/compatibility proof;
- benchmark evidence;
- `execution_log.md`;
- `closeout_report.md`;
- exact lean manual test handoff;
- no known in-scope defect or residue.
