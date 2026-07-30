# Executor Protocol

## Before work

1. Read `AGENTS.md`.
2. Read every file in this packet in the order listed in `README.md`.
3. Confirm the repository path.
4. Record git status and baseline tests.
5. Preserve existing user changes.
6. Do not mutate the live EVW during migration development or testing.

## During work

- Execute tickets in dependency order.
- Keep one coherent change per ticket.
- Use `apply_patch` for source edits.
- Run targeted tests after each ticket.
- Run the relevant regression suite at every phase gate.
- Update `docs/transformation/phase_1_4_execution_log.md` after every ticket with files, commands, results, and remaining risk.
- Keep new hand-written files limited to the necessary Flutter probe, server package, and transformation documentation.
- Do not generate fake UI, placeholder controls, no-op endpoints, or speculative account/payment abstractions.
- Do not silently retry, truncate, fallback, or suppress valid data.

## Stop conditions

Stop and report only when:

- a live migration requires an explicit dataset selection;
- exact active prompts cannot be recovered;
- a required native extension remains unbuildable/unloadable after three distinct safe fixes;
- overlapping user changes cannot be preserved;
- validation indicates data-loss risk;
- a required external provider credential/model is unavailable after all fake-provider and local tests are complete;
- the same blocking failure remains after three distinct safe fixes.

Do not stop merely because a task is large or inconvenient.

## Final report

Report:

- completed ticket IDs;
- files changed;
- exact commands and test results;
- final schema version and table inventory;
- final EVW/WAL/SHM sizes;
- working-corpus status and token count;
- server endpoint status;
- confirmation of the local-search/remote-model boundary;
- any blocker requiring user direction.
