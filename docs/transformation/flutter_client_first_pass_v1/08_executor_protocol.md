# Executor protocol

## Working method

1. Read the complete packet before editing.
2. Establish and record baseline before changing source.
3. Execute tickets in order.
4. After each ticket, format, run focused tests, inspect the diff, perform its
   residue check, and append `execution_log.md`.
5. Run broader regression after dependent tickets.
6. Preserve original failure details. Do not weaken contracts to make tests
   pass.
7. Keep code lean. Reuse existing working transcript/database machinery.

## Authority and ambiguity

This packet has already decided page scope, state ownership, boundaries,
navigation, evidence semantics, and deferred work. Do not ask the user to
choose alternatives already specified here.

Stop and request direction only if:

- current server/schema contracts materially contradict the packet in a way
  that cannot be reconciled without changing an out-of-scope component;
- required native sqlite functionality cannot work from Flutter Windows;
- the source worktree contains overlapping user edits that cannot be safely
  preserved;
- a data-integrity issue requires an EVW schema change;
- tests prove the specified exact behavior is impossible.

Do not stop because work is long, a test requires diagnosis, dependencies need
repair, or a fixture needs a disposable copy.

## Testing and cost

Run dependency installation, automated tests, builds, fake servers, and cleanup
yourself. Do not assign these to the user.

No automated or manual gate in this packet is authorized to call a paid or
free external model provider. Use deterministic fakes. Record that the total
external model-call count is zero.

## Completion

Completion requires implementation, all possible gates, cleanup, execution
log, and closeout report. If one genuine external blocker remains, complete
everything else and report the exact blocker and evidence. Do not call partial
implementation complete.

