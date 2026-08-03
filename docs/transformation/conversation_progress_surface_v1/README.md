# Conversation Progress Surface V1

This packet is the complete authority for implementing truthful conversational
progress in the Flutter client while preserving the existing production
analysis behavior.

Read every file completely, in this order, before editing source:

1. `00_scope_and_architecture.md`
2. `01_server_event_contract.md`
3. `02_flutter_state_and_ux.md`
4. `03_ticket_stack.md`
5. `04_acceptance_gates.md`
6. `05_executor_protocol.md`
7. `kickoff_prompt.md`

The executor must maintain `execution_log.md` while working and create
`closeout_report.md` only after implementation and validation.

The packet makes the architectural decisions. Do not replace them with a
larger framework, a model-authored status protocol, raw reasoning, fake
percentages, or persistent development logs.

