# EVW Transformation Execution Packet

> **Superseded:** Do not execute this packet again. The binding clean-break
> remediation is `../phase_1_4_closeout/README.md` and its kickoff prompt. This
> folder remains historical evidence for the first execution and audit.

This folder is the authoritative implementation specification for the first four transformation phases.

The executor must read the files in this order:

1. `00_mission_and_invariants.md`
2. `02_working_corpus_spec.md`
3. `03_evw_schema_and_wal_spec.md`
4. `04_flutter_compatibility_spec.md`
5. `05_server_contract_spec.md`
6. `01_ticket_stack.md`
7. `06_validation_and_gates.md`
8. `07_executor_protocol.md`

The copy/paste entrypoint is `kickoff_prompt.md`.

This packet deliberately keeps the kickoff prompt short. The implementation decisions live here so they are reviewable, versioned, and available to an execution agent without exceeding chat-paste limits.

## Authority

These documents supersede earlier informal transformation notes for Phases 1–4. Existing repository behavior and `AGENTS.md` remain authoritative where they impose stricter safety or data-integrity rules.

## End state

At the end of Phase 4:

- The EVW contains canonical user data, visible conversation history, workspace settings, evidence, artifacts, and scoped local indexes.
- A working corpus is an explicit bounded selection over the canonical full corpus.
- FTS5 and vector lookup remain local.
- A separately runnable Python server owns model routing, prompts, parsing, validation, and embedding generation.
- The existing Python UI uses the server and has no direct provider or local embedding-model path.
- Flutter has passed the Windows EVW compatibility gate, but no speculative Flutter product UI has been built.
- Authentication, billing, subscriptions, account databases, BYOK, and cloud deployment are not implemented.
