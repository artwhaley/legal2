# File map and guardrails

Inspect current contents and diffs before editing. Modify existing cohesive
modules in place. Do not create parallel v2, compatibility, experiment-server,
or alternate orchestration packages.

## Server files expected to change

```text
server/app.py
server/config.py
server/config_store.py
server/contracts.py
server/conversation.py
server/evidence_ledger.py
server/prompts.py
server/model_runtime.py
server/observability.py
server/admin.py
server/templates/admin.html
```

Change `server/embeddings.py` only to expose/reuse prepared embedding metadata
needed by the retrieval-plan response. Do not duplicate embedding inference,
batching, queues, or lifecycle.

Change `server/debug_capture.py` only if a cohesive helper is needed for new
request-bound records. Keep one capture manager and one ordered writer.

`server/provider.py`, `server/resilience.py`, and
`server/token_accounting.py` should normally require no architectural change.
Edit only if the new endpoint or exact accounting exposes a real missing
general-purpose hook.

## Python test-harness files expected to change

```text
message_evidence_workstation/client_api/contracts.py
message_evidence_workstation/client_api/gateway.py
message_evidence_workstation/services/client_workflows.py
message_evidence_workstation/ui/main_window.py
```

The GUI change is limited to:

- running retrieval plan -> query embeddings -> local hits -> analysis in the
  existing conversational action;
- showing new progress/compaction events;
- preserving cancellation and elapsed time;
- presenting the final result.

Do not add model selection, prompts, ranking policy, window policy, provider
policy, or diagnostic A/B controls to the Python GUI.

## Diagnostic script

Add exactly one focused non-production runner:

```text
scripts/run_retrieval_hint_experiment.py
```

It reads the EVW and writes `.tmp` artifacts but does not modify the EVW. It
uses only public product APIs for retrieval/analysis and existing admin
configuration for treatment mode.

Do not add a general experiment framework.

## Tests expected to change or be added

Prefer extending current focused files:

```text
tests/test_sfv1_contracts.py
tests/test_sfv1_control_store.py
tests/test_sfv1_admin.py
tests/test_sfv1_admin_browser.py
tests/test_sfv1_conversation.py
tests/test_sfv1_conversation_hardening.py
tests/test_sfv1_evidence_ledger.py
tests/test_sfv1_gateway.py
tests/test_sfv1_python_client_integration.py
tests/test_sfv1_resilience_observability.py
tests/test_sfv1_provider_accounting.py
```

Add at most these cohesive new files if separation is clearer:

```text
tests/test_sfv1_retrieval_assistance.py
tests/test_sfv1_retrieval_experiment.py
```

Do not create one test file per helper.

## Documentation expected to change

```text
README.md
docs/transformation/server_first_v1/manual_test.md
```

Mark conflicting current instructions superseded and describe four routes plus
the unified one/many-window path. Do not rewrite historical execution logs or
closeout reports.

## Required deletions

Delete runtime/test residue whose only purpose is the removed direct whole
path:

- `whole_corpus_answer` operation/config assignment;
- `WholeCorpusOutput` if no independent keyword path needs it;
- `whole_started` and `whole_completed` events;
- `build_whole_ledger`;
- direct whole-call branch and strategy;
- whole-specific prompt/admin guide/preview;
- tests asserting one whole model call;
- old result values `whole_corpus` and `windowed_ledger`.

Rename, do not duplicate:

- `ledger_reduction` -> `ledger_compaction`;
- `ledger_reduction_max_depth` -> `ledger_compaction_max_depth`;
- reduction event/help/test names -> compaction names.

After control-store migration, no runtime alias for an old operation name
remains.

## Explicitly leave alone

Do not modify:

```text
message_evidence_workstation/db/schema.py
message_evidence_workstation/db/migrations.py
message_evidence_workstation/db/corpus_repository.py
message_evidence_workstation/db/evidence_blocks.py
message_evidence_workstation/services/corpus_builder.py
message_evidence_workstation/tools/migrate_evw.py
flutter_client/
```

Do not change:

- EVW schema version 15;
- working-corpus/revision lifecycle;
- embedding artifact hashing/storage/clear behavior;
- evidence-block persistence;
- Flutter behavior;
- provider fallback policy;
- authentication/billing/BYOK;
- server control database content-free persistence rule.

If an acceptance failure appears to require one of these changes, diagnose and
record the conflict before editing. Do not expand scope silently.

## Repository safety

- Preserve all preexisting dirty and untracked user work.
- Never reset, checkout, clean, or revert unrelated changes.
- Do not commit, stage, push, deploy, or open a PR.
- Automated tests use temporary control state and EVW fixtures/copies.
- The diagnostic runner opens the real test EVW read-only.
- Resolve and verify `.tmp` paths before cleanup.
- Never print or store API keys.
- Use the repository `.venv`; install missing dependencies yourself.
- Do not assign dependency installation, automated tests, fixture preparation,
  server startup, or debug-capture setup to the user.

## Product guardrails

Forbidden:

- server EVW access;
- client-selected models/prompts/window sizes/retry policy;
- retrieval as corpus or window prefilter;
- global vector search followed by scope filtering;
- automatic embedding rebuild;
- silent candidate/evidence truncation;
- distance thresholds invented for this test;
- hidden term derivation fallback;
- test-only branches in production orchestration;
- client-controlled debug capture;
- public capabilities or internal-operation endpoints;
- fake provider tests that bypass real orchestration contracts;
- weakening strict contracts merely to make tests pass.

