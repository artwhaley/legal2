# Retrieval-Assisted Unified Conversation V1

This folder is the authoritative execution packet for unifying conversational
analysis and adding local semantic attention suggestions.

It supersedes conflicting conversational-routing, whole-corpus-answer,
retrieval-term, and ledger-reduction requirements in:

- `docs/transformation/server_first_v1`
- `docs/transformation/explicit_working_corpora_v15`
- older phase 1-4 transformation packets

Those packets remain historical evidence and remain authoritative for
unrelated completed architecture, especially server ownership, EVW v15,
working-corpus revisions, local sparse embedding artifacts, provider runtime,
admin configuration, retry behavior, and debug capture.

Read every file completely in this order before editing:

1. `00_mission_and_invariants.md`
2. `01_current_state_and_authority.md`
3. `02_target_architecture.md`
4. `03_contracts_and_configuration.md`
5. `04_retrieval_ranking_and_prompting.md`
6. `05_ledger_compaction_and_observability.md`
7. `06_file_map_and_guardrails.md`
8. `07_ticket_stack.md`
9. `08_acceptance_gates.md`
10. `09_investigative_run.md`
11. `10_executor_protocol.md`
12. `kickoff_prompt.md`

`07_ticket_stack.md` is the implementation order. Files 00-06 make the
architectural decisions and are binding. Files 08-10 define proof and execution
discipline. Do not preserve conflicting current behavior for compatibility.

The execution agent must maintain `execution_log.md` after every ticket and
create `closeout_report.md` at completion.

The copy/paste entrypoint is `kickoff_prompt.md`.

