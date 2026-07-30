# File map and guardrails

## Expected production contacts

Inspect before editing; names may have moved. Prefer modifying these current
surfaces over adding parallel modules.

### Server contracts and configuration

- `server/contracts.py`
  - v4 plan models;
  - analysis context;
  - extraction envelope/range contracts;
  - findings/dispositions;
  - validation summary;
  - result and stream events;
  - schema registry.
- `server/config.py`
  - schema version;
  - final operation set;
  - retrieval mode enum;
  - v4 validation/defaults.
- `server/config_store.py`
  - atomic v3-to-v4 migration;
  - bootstrap/default prompt wiring;
  - no runtime v3 aliases.
- `server/config_service.py`
  - snapshot behavior only if contract changes require it.
- `server/prompts.py`
  - new planner prompt;
  - revised extraction/compaction/synthesis prompts.

### Server runtime

- `server/app.py`
  - route rename;
  - planner operation;
  - plan response and fingerprint;
  - route/admission inventory.
- `server/conversation_unified.py`
  - plan-context validation;
  - exact plan injection;
  - range-level validation integration;
  - revised events/results/diagnostics.
- `server/evidence_ledger.py`
  - accepted-range record identity;
  - normalization metadata;
  - rejected-range summary assembly;
  - new disposition/finding validation.
- `server/model_runtime.py`
  - only the minimum special parsing hook required for range-granular
    extraction; do not weaken generic strict output validation.
- `server/observability.py`
  - content-free partial-validation counters/warnings.
- `server/debug_capture.py`
  - exact plan and validation artifacts only while active.

### Admin

- `server/admin.py`
- `server/templates/admin.html`

Update operation guides, output schemas, sample payloads, route descriptions,
retrieval mode, partial-validation activity, and exact next-request behavior.

### Python test equipment

- `message_evidence_workstation/client_api/contracts.py`
- `message_evidence_workstation/client_api/gateway.py`
- `message_evidence_workstation/services/client_workflows.py`
- `message_evidence_workstation/ui/main_window.py`

Rename the plan gateway, validate/echo the plan without modification, execute
semantic retrieval only when instructed, display partial validation visibly,
and persist only completed user-visible results under existing rules.

Do not restore or edit deleted legacy Python model/provider/search modules.

### Scripts

- update `scripts/run_retrieval_hint_experiment.py` only where needed to use
  the v4 plan/route/modes/result;
- add one narrowly scoped live validation/report script only if the existing
  runner cannot produce the required file 09 artifacts without contortion;
- update `scripts/verify_package_boundaries.py` for v4 residue checks.

### Tests

Primary current suites:

- `tests/test_sfv1_contracts.py`
- `tests/test_sfv1_control_store.py`
- `tests/test_sfv1_retrieval_assistance.py`
- `tests/test_sfv1_retrieval_client.py`
- `tests/test_sfv1_conversation_unified.py`
- `tests/test_sfv1_conversation_hardening.py`
- `tests/test_sfv1_evidence_ledger.py`
- `tests/test_sfv1_prompt_contract.py`
- `tests/test_sfv1_admin.py`
- `tests/test_sfv1_admin_browser.py`
- `tests/test_sfv1_python_client_integration.py`
- `tests/test_sfv1_mixed_load.py`
- `tests/test_sfv1_retrieval_experiment.py`
- `tests/test_sfv1_000_architecture.py`

Add focused files if that is clearer:

- `tests/test_qpa1_analysis_plan.py`
- `tests/test_qpa1_partial_range_validation.py`
- `tests/test_qpa1_synthesis_relevance.py`

## Files that must not change

- `flutter_client/**`
- EVW schema/migration/revision/embedding/evidence storage
- deleted legacy Python provider/router/search implementation
- user corpus files
- existing debug captures and investigative artifacts
- auth/billing/BYOK code outside incidental compilation fixes

If an unexpected required change reaches one of these surfaces, stop and record
the concrete ownership contradiction rather than expanding scope.

## Guardrails

- Do not add a second planner or conversational pipeline.
- Do not keep `/v1/conversational-retrieval-plan` as an alias.
- Do not keep `retrieval_terms` as a runtime operation.
- Do not keep `terms_only`, old plan fields, old event names, or old
  dispositions as runtime compatibility.
- Do not make planning optional.
- Do not let the client generate or edit plans/queries.
- Do not move vector lookup into the server or send EVWs to the server.
- Do not add numeric evidence scoring.
- Do not prefilter corpus/windows using retrieval or plan output.
- Do not reject valid sibling ranges because another range is malformed.
- Do not accept, guess, or silently repair unknown IDs.
- Do not treat partial validation as full success.
- Do not add automatic malformed-range repair calls.
- Do not remove or weaken ledger compaction.
- Do not let compaction decide final relevance.
- Do not log content outside active exact debug capture.
- Do not create test-only production branches or fake progress.
- Do not call real providers from routine pytest.
- Do not rebuild the large EVW embedding cache during tests.

## Deletion requirement

After v4 migration and test conversion, statically scan current runtime and
client code for:

```text
/v1/conversational-retrieval-plan
retrieval_terms
retrieval_plan_id
retrieval_assistance
terms_only
retrieval_assistance_accepted
no_relevant_evidence
used
redundant
not_material
```

Old strings may remain only in:

- explicit v3-to-v4 migration code/tests;
- historical docs and artifacts;
- natural-language prose where `used` is not a disposition literal.

Document every permitted residue in closeout.

