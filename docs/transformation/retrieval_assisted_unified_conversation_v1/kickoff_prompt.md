# Retrieval-Assisted Unified Conversation V1 Executor Kickoff

Repository:

`C:\Users\artwh\OneDrive\Documents\legal2`

Implement the complete authoritative packet:

`C:\Users\artwh\OneDrive\Documents\legal2\docs\transformation\retrieval_assisted_unified_conversation_v1\README.md`

Before editing:

1. Read repository `AGENTS.md` completely.
2. Read every packet document in the exact README order.
3. Inspect and record the dirty worktree/baseline required by RAUC1-000.
4. Treat this packet as authoritative where it conflicts with older
   conversational, whole-corpus, retrieval, or ledger-reduction requirements.
5. Preserve unrelated user work. Do not reset, clean, revert, commit, push, or
   deploy.

Execute RAUC1-000 through RAUC1-900 in dependency order. Complete each ticket's
implementation, focused tests, regression evidence, and required deletion
before beginning a dependent ticket. Maintain:

`C:\Users\artwh\OneDrive\Documents\legal2\docs\transformation\retrieval_assisted_unified_conversation_v1\execution_log.md`

The required end state is:

- The server exposes exactly four product POST routes: keyword expansion,
  conversational retrieval plan, conversational analysis, and embeddings.
- The server remains stateless and EVW-blind.
- The client owns the EVW and exact local vector lookup; the server owns every
  provider/model/prompt/ranking/window/ledger/synthesis decision.
- The separate `whole_corpus_answer` path is deleted. Every conversation runs
  retrieval planning, one or more `window_evidence_extraction` calls, canonical
  ledger construction, and `ledger_synthesis`.
- A corpus that fits is one extraction window; a larger corpus is multiple
  deterministic balanced windows. These are not separate answer systems.
- Server-extracted queries are embedded through the existing embedding
  endpoint, searched locally at message level in the selected immutable
  working-corpus revision, and returned as ranked message IDs.
- Semantic suggestions are advisory only. They never filter corpus/messages/
  windows/evidence. Every model scans its complete assigned window and must find
  evidence outside suggestions.
- Candidate fusion is exact reciprocal-rank fusion with packet-defined ordering
  and settings. Do not invent FTS, chunk search, distance thresholds, or a
  full-question embedding in this phase.
- The canonical ledger never drops valid data.
- Keep the hierarchical ledger-compaction fallback. Rename/harden it and make
  every trigger loud in stream progress, structured warning logs, admin,
  temporary debug capture, usage accounting, Python progress, and final result.
  Final responses always contain an entry for every original range ID using its
  original boundaries, summary, and relevance.
- Configuration migrates atomically to v3 with five chat operations. No runtime
  compatibility aliases remain.
- The existing server-side temporary exact debug capture is extended, not
  replaced.
- Python is changed only as test equipment. Flutter and EVW schema/lifecycle/
  evidence/embedding persistence are untouched.
- No silent fallback, repair, truncation, default-filled model response, fake
  progress, or test-only production behavior.

Install/repair repository-environment dependencies and run all automated work
yourself. Routine tests use deterministic fakes and make no real provider calls
or large embedding rebuilds.

After all local gates pass, use already configured approved credentials for the
single authorized investigative sequence in `09_investigative_run.md`:

- start fresh exact server debug capture;
- run the 100K one-window smoke;
- freeze one `When did we fight about school?` retrieval plan/vector/candidate
  pool on revision 4;
- run one terms-only arm;
- run one full-semantic arm;
- conditionally run one censored-semantic arm with provisional true-positive
  hits removed and noise backfilled;
- measure evidence found outside suggestions;
- do not repeat expensive arms automatically;
- stop and flush capture and report exact artifact paths.

If live credentials are unavailable or the configured provider remains
externally unavailable after configured attempts, complete every local gate and
record the live investigation as the sole external blocker. Never silently
switch providers/models.

At completion create:

`C:\Users\artwh\OneDrive\Documents\legal2\docs\transformation\retrieval_assisted_unified_conversation_v1\closeout_report.md`

Include every ticket/gate, exact commands/results, route/config migration,
changed/deleted files, one/many-window proof, retrieval/candidate/gold-rank and
outside-suggestion results, compaction proof/status, debug capture and
diagnostic artifact paths, preserved EVW/WAL state, full regression totals,
remaining factual risks, and lean human manual-test instructions.

Continue autonomously until completion or a genuine stop condition in
`10_executor_protocol.md`. Begin with RAUC1-000 now.
