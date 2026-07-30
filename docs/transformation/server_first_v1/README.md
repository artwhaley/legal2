# Server-first v1 execution packet

This folder is the authoritative implementation package for replacing the
experimental split server with the production-shaped server control plane and
unified model API. It supersedes earlier server contracts in `phase_1_4` and
`phase_1_4_closeout`; those folders remain historical evidence only.

Read and execute in this order:

1. `00_mission_and_invariants.md`
2. `01_architecture_and_ownership.md`
3. `02_api_and_orchestration_contract.md`
4. `03_admin_config_and_secrets.md`
5. `04_runtime_resilience_observability.md`
6. `05_python_harness_contract.md`
7. `06_ticket_stack.md`
8. `07_acceptance_gates.md`
9. `08_executor_protocol.md`
10. `kickoff_prompt.md`

`06_ticket_stack.md` is the authoritative implementation order. Architectural
decisions in files 00–05 are binding. If existing code or old documentation
conflicts with this packet, this packet wins. Do not preserve conflicting
behavior for compatibility.

Scope is server-first. The Python client is retained for one phase only as the
real local-EVW integration harness. Flutter and EVW schema work are excluded.

The execution agent must maintain `execution_log.md` after every ticket and
produce `closeout_report.md` at completion.

The copy/paste entrypoint is `kickoff_prompt.md`.
