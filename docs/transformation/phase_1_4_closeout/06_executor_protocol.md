# Executor Protocol

## Operating rules

1. Read `AGENTS.md` and this packet completely before editing.
2. Preserve unrelated user work and never mutate the only copy of an EVW.
3. Execute the ticket stack in order and update
   `closeout_execution_log.md` after each ticket.
4. Prefer deleting obsolete paths over adapting them.
5. Do not add compatibility wrappers, dual signatures, optional scope, hidden
   fallback, schema auto-detection in runtime, or test-only production switches.
6. Do not weaken, skip, or xfail an in-scope assertion to pass a gate.
7. Do not add authentication, payment, BYOK, cloud persistence, Flutter editing,
   or unrelated UI.
8. Important operations expose start, bounded progress, completion, and original
   failure. No silent retry or truncation.

## Patch discipline

- Make one coherent ticket change at a time.
- Run targeted tests before moving to the dependent ticket.
- When deleting a production module, delete or rewrite all tests that encode its
  old architecture in the same ticket.
- Keep the app runnable at ticket gates, except a ticket may deliberately break
  imports temporarily within its own uncommitted work while completing the
  clean cut.
- Do not retain dead aliases "for now." If a future feature needs a concept, it
  can add it against v14/API v2 later.

## Stop conditions

Stop only for:

- inability to identify which dataset to preserve from a multi-dataset source;
- validation showing canonical data loss/corruption risk;
- unavailable real EVW copy after every fixture/fake gate is complete;
- missing real provider authority after fake-server integration is complete;
- an overlapping user edit that cannot be preserved;
- the same native/toolchain blocker after three distinct safe fixes.

Old tests failing because the old interface was removed are not blockers. Fix or
replace them with the target contract.

## Completion rule

Do not claim complete until CLS-000 through CLS-402 are done, every command in
the acceptance file passes, a migrated v14 copy opens in both clients, all five
requested search capabilities work in the Python client, limited-corpus leak
tests pass for every mode, and forbidden legacy/import scans are empty.
