# Executor protocol

## Working method

1. Read `AGENTS.md` and the complete packet before editing.
2. Establish the baseline and dirty-worktree inventory.
3. Execute CSP1-000 through CSP1-900 in order.
4. After each ticket, format touched files, run focused tests, inspect the
   diff, run its residue check, and append `execution_log.md`.
5. Run broader regression after dependent tickets.
6. Preserve original errors. Never weaken a contract or test merely to pass.
7. Keep the implementation direct and inspectable.

## Authority

This packet decides:

- the server/client boundary;
- the exact provisional event shape;
- timer ownership;
- session lifetime;
- revision-change clearing;
- persistence exclusions;
- provisional evidence presentation;
- terminal presentation;
- test and cost boundaries.

Do not ask the user to choose alternatives already settled here.

## Stop conditions

Stop and request direction only if:

- overlapping user edits make an allowed file unsafe to modify;
- a required behavior needs an EVW schema change;
- the current event pipeline cannot expose validated ranges without changing
  provider orchestration;
- the existing `IndexedStack` cannot preserve state and the smallest correct
  replacement materially changes navigation architecture;
- a failing gate demonstrates the specified behavior is impossible.

Do not stop because work is lengthy, tests require diagnosis, a fixture needs
updating, or dependencies need to be run. Do not introduce speculative
fallback behavior to get around a failure.

## Dirty worktree

Treat all existing modifications and untracked files as user work. Do not
reset, clean, checkout, delete, commit, push, deploy, or create a PR. Touch
only packet-authorized files unless a documented necessity arises.

## Testing and cost

Run dependencies, automated tests, analysis, formatting, build, and cleanup
yourself. Do not assign automated work to the user.

No packet gate authorizes an external LLM or embedding-provider call. Use fake
providers and fake NDJSON streams. Do not mutate a real EVW; use disposable
fixtures or copies where file access is required.

## Completion

Completion requires implementation, all possible gates, cleanup,
`execution_log.md`, and `closeout_report.md`. If a genuine external blocker
remains, complete everything else and report exact evidence without claiming
the blocked ticket is done.

