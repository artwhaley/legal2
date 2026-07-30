# Executor protocol

## Required operating mode

Work autonomously through `07_ticket_stack.md` in order. Decisions in this
packet are already made. Do not ask the user to redesign contracts or perform
setup that the executor can perform.

Before editing:

1. Read repository `AGENTS.md` completely.
2. Read every packet file completely in README order.
3. Inspect git status and preserve all existing user changes.
4. Create current baseline entries in `execution_log.md`.
5. Inspect relevant current code/tests before replacing behavior.

## Ticket loop

For each ticket:

1. Record target and dependencies.
2. Inspect current contact surfaces and overlapping user changes.
3. Implement the complete ticket, including required deletion/rename.
4. Add or update focused real tests.
5. Run focused tests and fix every failure.
6. Run all currently relevant regression tests.
7. Inspect diff for defaults, fallback, compatibility residue, content leaks,
   and unrelated edits.
8. Record files, commands, exact results, decisions already fixed by packet,
   and next dependency.
9. Continue immediately.

Do not accumulate knowingly broken production paths.

## Implementation discipline

- Prefer direct cohesive edits over new abstraction layers.
- Use one runtime path for each operation.
- No compatibility aliases after config migration.
- No test-only production branches.
- No fake progress.
- No hidden fallback or retry.
- No evidence/corpus/candidate truncation beyond the explicit advisory
  suggestion limit.
- No network call during EVW or control-store transaction.
- No blocking inference on FastAPI event loop.
- Keep exact strict contracts synchronized server/client.
- Preserve the canonical ledger throughout compaction.
- Treat debug capture as sensitive and temporary.

## Test discipline

- Automated tests use deterministic fake providers/embeddings.
- Do not make real API calls during `pytest`.
- Do not regenerate all fixture embeddings during `pytest`.
- The live run occurs only after deterministic gates.
- Do not weaken assertions to green a gate.
- Do not retain old behavior solely for old tests.
- Run commands yourself; do not return a dependency/test checklist to the user.

## Service discipline

- Launch noninteractive processes hidden.
- Record PID, command, state directory, stdout/stderr paths, and ports.
- Monitor operations with bounded waits and commentary.
- Cancel/stop orphan diagnostics.
- Leave no accidental background process at closeout.
- Never treat a port-open check as a functional pass.

## Secret discipline

- Use existing encrypted server configuration.
- Never read back, echo, log, diff, document, or report API-key values.
- Tests use synthetic secrets.
- If a secret appears in generated output, stop outward output, redact the
  artifact without repeating the value, record the incident, and continue only
  when safe.

## Genuine stop conditions

Stop only when:

- required user data would need destructive modification outside scope;
- an overlapping user edit cannot be safely preserved;
- the same environmental blocker remains after three distinct safe approaches;
- unavailable credentials are the only remaining live gate;
- packet and repository contain a genuine unresolved ownership contradiction.

Provider outage does not block local implementation.

Before stopping, record exact reproducer/evidence and request the smallest
required input. Do not call partial work complete.

## Completion

Completion requires:

- RAUC1-000 through RAUC1-900 dispositioned;
- all mandatory local gates green;
- no direct whole runtime path;
- one/many-window unified proof;
- real retrieval-plan/local-vector/server-suggestion proof;
- outside-suggestion diagnostics;
- retained loud compaction proof;
- full regression;
- execution log and closeout report;
- exact lean manual test handoff;
- no known in-scope defect or residue.

