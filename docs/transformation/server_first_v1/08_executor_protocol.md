# Executor protocol

## Required operating mode

Work autonomously through `06_ticket_stack.md` in order. Do not stop for choices
already made by this packet. Do not reinterpret the architecture to preserve
current code. Prefer direct replacement and deletion.

Before acting:

1. Read every packet file completely.
2. Read repository `AGENTS.md` completely.
3. Inspect git status and record preexisting changes.
4. Inspect current server/Python paths and tests named by searches.
5. Start `execution_log.md`; never claim an old log entry as current evidence.

## Ticket loop

For each ticket:

1. Restate its concrete target in the execution log.
2. Inspect only relevant current files and dependencies.
3. Implement the complete target, including required deletion in that ticket.
4. Add/update focused tests.
5. Run the focused gate and fix every failure.
6. Run all currently relevant tests to catch regression.
7. Record files, decisions already dictated by packet, commands, exact results,
   deletions, and remaining dependency in `execution_log.md`.
8. Continue immediately to the next ticket.

Do not accumulate knowingly broken placeholders across tickets except where the
ticket explicitly permits the old client to remain broken until SFV1-800.

## Repository safety

- Preserve unrelated user changes and untracked files.
- Never use destructive git reset/checkout/clean.
- Do not edit or delete historical transformation folders.
- Do not modify Flutter or EVW schema/migration code.
- Never run automated writes against the user's only EVW; use copies/fixtures.
- Use `.tmp` for generated test state and resolve exact paths before cleanup.
- Do not commit, stage, push, or create a PR unless separately instructed.

## Secret safety

- Never print/read back real API-key values in terminal output, logs, tests,
  reports, diffs, or chat.
- Tests use unmistakable synthetic secrets and temporary state.
- Existing JSON is accessed only by the importer and replaced only after the
  verified transaction specified in file 03.
- If a real key accidentally appears in output, stop further output, redact
  generated artifacts, document exposure without repeating the value, and
  continue only when safe.

## Implementation rules

- No compatibility endpoints, feature flags, aliases, dual config paths, silent
  fallback, silent retry, partial success, truncation, response defaults, or
  placeholder production logic.
- No speculative framework, generic plugin system, ORM, queue service, SPA, or
  file explosion.
- Use the final lean file map as a target; combine small cohesive helpers.
- All controls must connect to real runtime behavior and tests.
- Fixed invariants are not admin knobs.
- Network calls never occur while SQLite transactions are open.
- Blocking work never runs on the FastAPI event loop.
- Every stream and operation has visible terminal behavior.
- Every known failure has one centralized stable mapping.

## Current-test conflicts

Old tests are not requirements when they assert:

- capabilities discovery;
- public whole/window/retrieval/ledger endpoints;
- Qt server administration;
- client model/context/window/batch decisions;
- exact-one-attempt client policy;
- response default filling;
- JSON runtime configuration.

Rewrite or delete those tests in the replacement ticket. Do not keep dead code
to satisfy them. Preserve unrelated EVW/local-search integrity tests.

## Service/process discipline

Use deterministic in-process fakes for routine tests. When launching real
server/client processes, record PID/command, hide noninteractive service
windows, monitor progress, stop orphan diagnostics, and leave only deliberately
requested final test processes running. Never treat a port-open check as a
functional pass.

## Genuine stop conditions

Stop and request instructions only when:

- required source/user data would have to be destructively changed outside
  explicit authorization;
- a preexisting overlapping user edit cannot be safely preserved;
- a required credential/master-key source cannot be generated/resolved without
  exposing or destroying a real secret;
- the same environmental blocker persists after three distinct, documented
  safe approaches and no meaningful local progress remains;
- a packet contradiction changes data ownership or public contract.

External provider outage/capacity does not stop deterministic implementation;
complete all local gates and report the live gate separately. Do not invent a
fallback.

## Completion rule

Do not report completion until all mandatory local gates pass, obsolete paths
are absent, admin behavior is real, Python proves both conversation strategies
and embedding streaming, and `closeout_report.md` is complete. If a genuine
stop condition remains, report exact completed tickets, reproducer, evidence,
and the single decision/input required. Do not call partial work done.
