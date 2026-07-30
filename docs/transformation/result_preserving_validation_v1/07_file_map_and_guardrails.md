# File map and guardrails

## Primary server files

Expected edits:

- `server/contracts.py`
  - new synthesis/public-result/warning/event contracts;
  - remove disposition contracts and obsolete status.
- `server/prompts.py`
  - extraction/compaction/synthesis defaults.
- `server/model_runtime.py`
  - preserve raw synthesis content and targeted unusable-output handling
    without weakening generic strict operations.
- `server/evidence_ledger.py`
  - keep canonical source ledger;
  - remove disposition/finding publication gates;
  - add granular citation/result assembly helpers or move those to a cohesive
    new server module if that keeps source validation separate.
- `server/conversation_unified.py`
  - isolated window outcomes, partial coverage, compaction preservation,
    result-preserving synthesis, new stream events/status.
- `server/observability.py`
  - exact warning/hard-error mapping and metrics.
- `server/admin.py`
  - human explanation, schema, metrics, obsolete text removal.
- `server/config.py` / `server/config_store.py`
  - only if prompt migration/activation validation requires it.
- `server/token_accounting.py`
  - only if the new response schema affects exact payload counting.
- `server/resilience.py`
  - only the minimum cohesive change needed for explicit targeted empty-output
    retries; do not duplicate resilience.

Permitted new server file:

- one cohesive module such as `server/result_validation.py` for synthesis
  salvage, citation verification, ordering, warning collection, and result
  assembly.

Do not create a folder tree or generic validation framework.

## Python test-equipment files

Expected edits:

- `message_evidence_workstation/client_api/contracts.py`
- `message_evidence_workstation/client_api/gateway.py` only if event/result
  handling requires it
- `message_evidence_workstation/services/client_workflows.py`
- `message_evidence_workstation/ui/main_window.py`
- directly related current tests

Do not revive deleted legacy Python search/provider modules. Do not expand the
Python application beyond what is required for manual server testing.

## Scripts

Expected edits:

- `scripts/run_question_planned_analysis_live.py`
- `scripts/run_retrieval_hint_experiment.py`

Preserve one ordinary product path. Runners orchestrate the public endpoints;
they do not call private synthesis helpers.

## Tests

Expected replacement/update:

- `tests/test_qpa1_contracts.py`
- `tests/test_qpa1_range_validation.py`
- `tests/test_qpa1_synthesis.py`
- `tests/test_qpa1_orchestration.py`
- `tests/sfv1_support.py`
- `tests/test_sfv1_contracts.py`
- `tests/test_sfv1_conversation*.py`
- `tests/test_sfv1_evidence_ledger.py`
- `tests/test_sfv1_resilience_observability.py`
- `tests/test_sfv1_python_client_integration.py`
- `tests/test_sfv1_retrieval_client.py`
- `tests/test_sfv1_retrieval_experiment.py`
- `tests/test_sfv1_mixed_load.py`
- admin/browser tests

Delete obsolete tests whose sole purpose is enforcing dispositions, direct-only
findings, all-or-nothing synthesis, or `LEDGER_BIJECTION_FAILED`.

Do not retain old assertions under renamed test functions.

## Files to leave alone

Unless an exact package-boundary import update is unavoidable:

- `flutter_client/**`
- EVW migrations/schema/repositories
- local embedding persistence/index logic
- corpus revision lifecycle
- auth/billing/BYOK work
- legacy deleted Python provider/search implementation

No EVW fixture mutation is required.

## Dirty-worktree discipline

The repository is intentionally dirty. Before every edit:

- inspect the exact file and `git diff`;
- distinguish existing user work from packet changes;
- preserve unrelated modifications;
- never reset, clean, checkout, or mass-revert;
- do not commit, push, deploy, or create a PR unless separately authorized.

Packet files themselves are new and may be edited freely by the executor as
execution evidence accumulates only where specified.

## Forbidden implementation shortcuts

- no compatibility alias for old dispositions;
- no second conversational endpoint/path;
- no client-side probability inference;
- no numeric confidence;
- no threshold that hides lower-probability results;
- no empty string/list defaults to make invalid output look conforming;
- no fabricated-ID fuzzy repair;
- no truncation of answer/ledger/warnings;
- no catch-all exception that silently returns success;
- no silent retry;
- no full-search rerun to repair one window/synthesis;
- no test-only production branch;
- no tests that merely assert mocked constants without exercising the public
  result assembly;
- no real provider calls in routine pytest;
- no large embedding rebuild in routine pytest.

## Required residue scan

Active runtime/client/script/test code must contain no:

```text
direct_evidence
useful_context
not_responsive
range_dispositions
validate_dispositions
validate_findings
partial_evidence_validation
LEDGER_BIJECTION_FAILED
```

Historical transformation documents may retain those terms. Migration tests
may contain them only as obsolete input literals.

