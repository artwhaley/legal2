# Current state and packet authority

## Implemented state to replace

Current conversational analysis has two branches in `server/conversation.py`:

1. `whole_corpus_answer` directly answers and returns ranges in one model call.
2. `window_evidence_extraction` scans multiple windows, builds a canonical
   ledger, optionally reduces summaries, and calls `ledger_synthesis`.

Current retrieval assistance:

- calls `retrieval_terms` only after the server has selected the windowed path;
- sends the same literal terms to every window model;
- performs no FTS5 or vector retrieval;
- sends no suggested message IDs or ranges.

Current local embedding search:

- requests a query vector from `/v1/embeddings`;
- performs exact local `sqlite_vec` distance queries in the selected immutable
  working-corpus revision;
- is a separate Python-client workflow;
- does not feed conversational analysis.

Current debug capture already records exact public traffic and provider
requests/responses into temporary server-side JSONL when an administrator
explicitly enables it. Extend this implementation; do not replace it.

## Measured synthesis evidence

Use these figures as practical context, not as limits:

| Run | Ledger ranges | Messages inside ranges | Synthesis input | Usable input | Compaction |
|---|---:|---:|---:|---:|---|
| Recent nine-window run | 40 | 558 | 63,514 tokens | 184,870 tokens | No |
| Recent six-window run | 15 | 405 | 45,092 tokens | 184,870 tokens | No |

The 40-range synthesis payload was 238,803 serialized bytes and used 34.4% of
the configured usable synthesis input. Range transcript length, not range
count alone, controls synthesis size.

No captured current test invoked `ledger_reduction`.

## Existing implementation references

Read these current files before editing:

```text
server/app.py
server/config.py
server/config_store.py
server/contracts.py
server/conversation.py
server/evidence_ledger.py
server/prompts.py
server/model_runtime.py
server/embeddings.py
server/debug_capture.py
server/admin.py
server/templates/admin.html
message_evidence_workstation/client_api/contracts.py
message_evidence_workstation/client_api/gateway.py
message_evidence_workstation/services/client_workflows.py
message_evidence_workstation/ui/main_window.py
tests/test_sfv1_contracts.py
tests/test_sfv1_conversation.py
tests/test_sfv1_conversation_hardening.py
tests/test_sfv1_evidence_ledger.py
tests/test_sfv1_admin.py
tests/test_sfv1_python_client_integration.py
```

Read historical `message_evidence_workstation/search/exhaustive_hints.py` and
`tests/test_exhaustive_hints.py` from git history only as behavioral reference.
Do not restore their old router, model adapter, chunk, FTS, or dataset-wide
architecture.

## Authority and conflict rules

This packet supersedes:

- the server-first exact-three-route requirement;
- the separate whole-versus-window answer implementation;
- client contracts that send only question plus messages;
- `retrieval_assistance_enabled` Boolean behavior;
- the `ledger_reduction` public/internal name;
- tests requiring `whole_corpus` or `windowed_ledger` result values;
- tests requiring retrieval-term generation inside the analysis stream.

This packet does not supersede:

- server EVW blindness;
- explicit immutable working-corpus revision scope;
- sparse local reusable embedding artifacts;
- existing embedding endpoint streaming and geometry;
- admin-owned active configuration;
- provider retry/circuit/concurrency behavior;
- exact debug capture;
- content-free normal logs and accounting;
- v15 schema and evidence-block durability.

When old tests conflict, rewrite or delete the conflicting assertion. Do not
retain dead production branches to satisfy it.

