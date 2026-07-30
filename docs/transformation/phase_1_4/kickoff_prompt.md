# Kickoff Prompt

> **Superseded:** Use
> `C:\Users\artwh\OneDrive\Documents\legal2\docs\transformation\phase_1_4_closeout\kickoff_prompt.md`.

You are the implementation executor for:

`C:\Users\artwh\OneDrive\Documents\legal2`

Execute the complete EVW transformation through Phases 1–4. Do not merely produce a plan. Read and obey `AGENTS.md`, then read every file under:

`C:\Users\artwh\OneDrive\Documents\legal2\docs\transformation\phase_1_4`

Start with `README.md`; it gives the required reading order. `01_ticket_stack.md` is the authoritative implementation order. The other files are the binding specifications for working corpora, EVW schema/WAL lifecycle, Flutter compatibility, server contracts, validation, and execution behavior.

Implement every ticket from XFM-000 through XFM-405 in dependency order. Run tests after each ticket and stop at a phase gate only to fix failures. Keep an execution log at:

`C:\Users\artwh\OneDrive\Documents\legal2\docs\transformation\phase_1_4\execution_log.md`

Create that log if it does not exist.

Preserve existing user changes. Do not use destructive git reset/checkout commands. Do not mutate the live `workspace.evw` while developing or testing migration. Never manually delete a nonempty WAL.

The architectural decisions are already made in the specification. Do not ask for clarification about them. Do not invent app-shaped Flutter UI, ORM layers, speculative authentication/payment systems, silent retries, fallbacks, truncation, provider switching, model switching, or hidden logging.

Work autonomously until all gates pass or a real stop condition in `07_executor_protocol.md` occurs. At the end, report completed tickets, changed files, exact test commands/results, final schema/table/WAL state, working-corpus state, server state, and any blocker requiring instructions.
