# Executor protocol

## Required operating mode

Work autonomously through `08_ticket_stack.md` in order. Architectural
decisions are made. Do not ask the user to redesign contracts or perform setup,
dependency installation, automated testing, process control, or artifact
collection that the executor can perform.

Before editing:

1. read repository `AGENTS.md` completely;
2. read every packet file completely in README order;
3. inspect git status and preserve user changes;
4. inventory current contacts and baseline;
5. start `execution_log.md`.

## Ticket loop

For every ticket:

1. record objective/dependencies;
2. inspect current files and overlapping diffs;
3. implement complete production behavior;
4. delete obsolete runtime/test behavior;
5. add real focused deterministic tests;
6. run/fix focused tests;
7. run relevant regression;
8. scan for evidence loss, hidden defaults/retries/fallbacks, content leaks,
   duplicate paths, and unrelated edits;
9. record exact commands/results/files;
10. continue immediately.

Do not accumulate knowingly broken production behavior between dependent
tickets.

## Engineering discipline

- Return useful results; do not optimize for a green schema at their expense.
- Keep source verification strict and model judgment advisory.
- Preserve raw readable synthesis.
- Preserve completed windows and the canonical ledger.
- Prefer direct typed outcomes over broad exception swallowing.
- Emit visible retry and warning events.
- Do not invent convenience behavior outside this packet.
- Do not add a generic validation framework.
- Do not preserve obsolete compatibility.
- Keep network calls outside EVW/control-store transactions.
- Keep blocking work off the FastAPI event loop.
- Keep server/client contracts synchronized.

## Test discipline

- Automated tests use deterministic fake providers/embeddings.
- No routine test makes real provider calls.
- No routine test regenerates large embeddings.
- Do not green tests by weakening source-ID verification.
- Do not assert only mocked constants; exercise public orchestration/results.
- Run dependencies/tests yourself.

## Service and secret discipline

- Launch background services hidden and noninteractive.
- Record PID, command, state directory, logs, and port.
- Use bounded waits and visible progress.
- Stop orphan processes.
- Use encrypted configured credentials without printing or reading them back.
- Redact artifacts; never repeat a secret.

## Dirty worktree

Do not reset, clean, revert, checkout, commit, push, deploy, or create a PR
unless separately instructed. Work around and preserve unrelated changes.

## Genuine stop conditions

Stop only when:

- destructive out-of-scope user-data mutation is required;
- overlapping user edits cannot be preserved safely;
- the same environmental blocker remains after three distinct safe approaches;
- unavailable credentials/provider are the sole remaining live gate;
- packet/repository contain a genuine unresolved ownership contradiction.

Record exact evidence and request the smallest needed decision. Hard work,
failing tests, or imperfect model output are not stop conditions.

## Completion

Completion requires:

- every ticket and gate closed;
- obsolete runtime residue removed;
- deterministic suite green;
- live proof or exact external blocker;
- no readable answer can be thrown away by validation;
- no fabricated source can be presented as verified;
- lower/unclassified evidence remains visible;
- execution log and closeout report complete;
- cleanup complete;
- lean manual test handoff.

