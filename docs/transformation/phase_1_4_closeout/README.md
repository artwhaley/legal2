# Phase 1–4 Closeout Patch Specification

This packet supersedes the implementation portions of
`docs/transformation/phase_1_4` where the verification audit found an
incomplete or compatibility-shaped result. The older packet and execution log
remain historical evidence; they are not the target architecture.

Read this packet in order:

1. `00_target_architecture.md`
2. `01_evw_v14_and_scope_contract.md`
3. `02_server_and_python_client_contract.md`
4. `03_flutter_viewer_contract.md`
5. `04_file_map.md`
6. `04_ticket_stack.md`
7. `05_acceptance_and_closeout.md`
8. `06_executor_protocol.md`

The execution entrypoint is `kickoff_prompt.md`.

## Binding end state

- The EVW production schema is v14. Runtime code opens v14 only.
- One EVW contains one canonical full corpus and any number of immutable saved
  search-corpus definitions. Exactly one ready search corpus is active.
- Every lexical, fuzzy, vector, transcript, window, hint, and conversational
  search requires an active `WorkingCorpusScope`. No search API accepts only a
  `dataset_id`.
- The Python and Flutter clients own local EVW access. The server never imports
  SQLite code, receives an EVW path, opens an EVW, or persists user data.
- The server is the only model/provider/embedding execution process.
- The Python client has one HTTP gateway, one remote embedding route, one
  serialized EVW writer, and no local provider or embedding-model fallback.
- Flutter is a real, lean, read-only v14 viewer as well as a separately invoked
  Windows compatibility probe.
- Old schemas are handled only by an explicit compact-copy migration tool, not
  by runtime compatibility branches.
- Authentication, billing, subscription, BYOK, and cloud deployment remain out
  of scope.

## Clean-break rule

Do not preserve an old interface merely to keep an old test green. Remove the
old implementation and rewrite or delete the test that specifies it. Preserve
canonical user data through the explicit migration tool; do not preserve old
runtime architecture.
