# Question-Planned Conversational Analysis V1 Executor Kickoff

Repository:

`C:\Users\artwh\OneDrive\Documents\legal2`

Implement the complete authoritative packet:

`C:\Users\artwh\OneDrive\Documents\legal2\docs\transformation\question_planned_analysis_v1\README.md`

Before editing:

1. Read repository `AGENTS.md` completely.
2. Read every packet document in exact README order.
3. Inspect and record the dirty worktree/baseline required by QPA1-000.
4. Treat this packet as authoritative where it conflicts with older planning,
   retrieval-plan, extraction-validation, disposition, prompt, or result
   requirements.
5. Preserve unrelated user work. Do not reset, clean, revert, commit, push, or
   deploy.

Execute QPA1-000 through QPA1-900 in dependency order. Complete each ticket's
implementation, focused tests, regression evidence, required deletion, and
execution-log entry before beginning a dependent ticket.

Maintain:

`C:\Users\artwh\OneDrive\Documents\legal2\docs\transformation\question_planned_analysis_v1\execution_log.md`

The required end state is:

- Exactly four product POST routes:
  `/v1/keyword-expansion`, `/v1/conversational-plan`,
  `/v1/conversational-analysis`, and `/v1/embeddings`.
- Configuration schema v4 with exactly five model operations:
  `keyword_expansion`, `analysis_planning`,
  `window_evidence_extraction`, `ledger_compaction`, and
  `ledger_synthesis`.
- Every conversation starts with one strict server-owned planning call that
  operationalizes the question, defines concepts/inclusions/exclusions,
  provides semantic retrieval queries, and specifies answer requirements.
- The exact frozen plan reaches every extraction window, compaction call, and
  synthesis call.
- The client remains a dumb executor of the server plan. It owns the EVW and
  exact local message-vector lookup but owns no provider/model/prompt/planning/
  ranking/window/retry policy.
- Local retrieval mode is exactly `none|semantic_ranges`.
- The existing unified one/many-window exhaustive pipeline remains. Retrieval
  never filters corpus messages or windows.
- Extraction favors candidate recall and no longer globally asks for
  contradictory evidence unrelated to the user's question.
- Extraction model envelopes are strict, but each range is validated
  independently. Valid sibling ranges survive. Unknown/fabricated IDs are
  quarantined, never guessed. Only provably reversed valid endpoints may be
  swapped, with an explicit normalization record.
- Any rejected range makes the completed result explicitly
  `partial_evidence_validation`. Rejected ranges never enter the canonical
  ledger, compaction, findings, dispositions, or evidence counts.
- Synthesis answers the plan, emits structured findings, and assigns every
  accepted range exactly one disposition:
  `direct_evidence`, `useful_context`, or `not_responsive`.
- All accepted ranges remain in the returned ledger. Not-responsive ranges are
  preserved for audit but are not presented as answering evidence.
- No numeric evidence/confidence ranking is added.
- Ledger compaction remains a loud measured context-overflow fallback and no
  longer decides final dispositions.
- Admin exposes every meaningful planner/extraction/compaction/synthesis model,
  prompt, reasoning, temperature, output, timeout, retry, and schema control,
  with next-request activation and no restart.
- Python changes are test-equipment changes only. Flutter and EVW schema/
  lifecycle/evidence/embedding persistence remain untouched.
- No hidden fallback, silent repair, response defaults, arbitrary evidence
  cap, fake progress, content leak, or test-only production branch.

Install/repair repository-environment dependencies and run all automated work
yourself. Routine tests use deterministic fakes and make no real provider calls
or large embedding rebuilds.

After all local gates pass, execute the single authorized live validation in
`09_live_validation.md` using already configured credentials. It must run GLM
5.2 on the established large corpus with at least six windows, active exact
debug capture, the exact question `Show me fights about school.`, and one
ordinary plan/retrieval/analysis/synthesis flow. Do not automatically repeat,
switch models, or tune after seeing the result. Preserve the actual answer,
findings, full ledger, dispositions, validation diagnostics, prompts, usage,
timing, and artifact paths for review.

If credentials are unavailable or the configured provider remains externally
unavailable after configured attempts, complete every local gate and record the
live gate as the sole external blocker. Never silently switch provider/model.

At completion create:

`C:\Users\artwh\OneDrive\Documents\legal2\docs\transformation\question_planned_analysis_v1\closeout_report.md`

Include every ticket/gate, exact commands/results, migration, route/operation
inventory, changed/deleted files, one/many proof, partial-range proof,
synthesis/disposition proof, live answer/artifacts or exact blocker, debug
capture state, no-write EVW/WAL evidence, full regression totals, factual
remaining risks, and lean human manual-test instructions.

Continue autonomously until completion or a genuine stop condition in
`10_executor_protocol.md`. Begin with QPA1-000 now.

