# Question-Planned Conversational Analysis V1

This folder is the authoritative execution packet for replacing shallow
retrieval-term extraction with a real analysis-planning operation, accepting
independently valid model ranges, and making final synthesis explicitly
separate answer-responsive evidence from contextual or nonresponsive material.

It supersedes conflicting planning, retrieval-plan, extraction-validation,
disposition, prompt, and conversational-result requirements in:

- `docs/transformation/retrieval_assisted_unified_conversation_v1`
- `docs/transformation/server_first_v1`
- older transformation packets

Those packets remain authoritative for unrelated completed architecture:
server ownership, the stateless EVW boundary, local vector lookup, balanced
window packing, provider runtime, retries, cancellation, debug capture,
accounting, ledger compaction, and working-corpus revisions.

Read every file completely in this order before editing:

1. `00_mission_and_invariants.md`
2. `01_current_state_and_authority.md`
3. `02_target_architecture.md`
4. `03_contracts_and_configuration.md`
5. `04_partial_range_validation.md`
6. `05_synthesis_and_evidence_policy.md`
7. `06_file_map_and_guardrails.md`
8. `07_ticket_stack.md`
9. `08_acceptance_gates.md`
10. `09_live_validation.md`
11. `10_executor_protocol.md`
12. `kickoff_prompt.md`

`07_ticket_stack.md` is the implementation order. Files 00-06 contain binding
architectural decisions. Files 08-10 define proof and execution discipline.

The executor maintains `execution_log.md` after every ticket and creates
`closeout_report.md` at completion. The copy/paste entrypoint is
`kickoff_prompt.md`.

