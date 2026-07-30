# Executor protocol

## Required operating mode

Work autonomously through `07_ticket_stack.md` in order. Architectural
decisions in this packet are already made. Do not ask the user to redesign
contracts or perform setup/testing that the executor can perform.

Before editing:

1. read repository `AGENTS.md` completely;
2. read every packet file completely in README order;
3. inspect git status and preserve all user changes;
4. create baseline entries in `execution_log.md`;
5. inspect relevant current code/tests before replacing behavior.

## Ticket loop

For each ticket:

1. record target and dependencies;
2. inspect current contacts and overlapping user changes;
3. implement the complete ticket, including required deletion/rename;
4. add/update focused real tests;
5. run focused tests and fix every failure;
6. run currently relevant regressions;
7. inspect diff for defaults, fallback, aliases, content leaks, test-only
   behavior, evidence loss, and unrelated edits;
8. record files, exact commands/results, and next dependency;
9. continue immediately.

Do not accumulate a knowingly broken production path.

## Implementation discipline

- Prefer direct cohesive edits over new framework layers.
- Maintain one runtime path per operation.
- Keep generic strict model parsing strict; isolate extraction's intentional
  range-level parser.
- No hidden fallback, retry, default, truncation, or repair.
- No numeric evidence ranking.
- No test-specific prompt behavior.
- No fake progress.
- No network call in EVW/control-store transactions.
- No blocking inference on the FastAPI event loop.
- Keep exact server/client contracts synchronized.
- Preserve canonical evidence and compaction coverage.
- Treat debug capture as sensitive and temporary.

## Test discipline

- Automated tests use deterministic fake providers/embeddings.
- No routine test makes a real API call.
- No routine test regenerates large-corpus embeddings.
- Do not green a gate by weakening production validation.
- Do not retain old behavior solely for old tests.
- Run dependencies/tests/processes yourself.

## Service discipline

- Launch noninteractive processes hidden.
- Record PID, command, state directory, logs, and port.
- Monitor long work with bounded waits and visible updates.
- Stop orphan diagnostics and leave no accidental process.
- A port-open check is not a functional pass.

## Secret discipline

- Use existing encrypted server configuration.
- Never read back, echo, log, diff, or document API-key values.
- Tests use synthetic credentials.
- If a secret appears in generated output, stop outward output, redact the
  artifact without repeating the value, record the incident, and continue only
  when safe.

## Genuine stop conditions

Stop only when:

- required user data would need destructive out-of-scope modification;
- overlapping user edits cannot be safely preserved;
- the same environmental blocker remains after three distinct safe approaches;
- unavailable credentials are the only remaining live gate;
- packet and repository contain a genuine unresolved ownership contradiction.

Provider outage does not block local implementation. Before stopping, record
the exact reproducer/evidence and request the smallest required input. Do not
call partial work complete.

## Completion

Completion requires:

- QPA1-000 through QPA1-900 dispositioned;
- all mandatory local gates green;
- v4 migration and forbidden-residue proof;
- real analysis plan used end to end;
- valid sibling-range preservation;
- explicit partial validation;
- answer-oriented findings and categorical dispositions;
- compaction preserved;
- admin and Python test equipment synchronized;
- full regression and mixed load;
- one authorized live GLM run or exact external blocker;
- execution log and closeout report;
- lean manual-test handoff;
- no known in-scope defect or residue.

