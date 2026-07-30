# Target File Map

Inspect current contents/diffs before editing. Do not create parallel legacy,
`v2`, or compatibility modules.

## Database/domain

```text
message_evidence_workstation/domain/constants.py
message_evidence_workstation/domain/search_scope.py
message_evidence_workstation/domain/models.py
message_evidence_workstation/domain/slots.py
message_evidence_workstation/db/schema.py
message_evidence_workstation/db/migrations.py
message_evidence_workstation/db/workspace_store.py
message_evidence_workstation/db/corpus_repository.py
message_evidence_workstation/db/evidence_blocks.py
message_evidence_workstation/db/printable_artifacts.py
message_evidence_workstation/services/corpus_builder.py
message_evidence_workstation/services/import_dataset.py
message_evidence_workstation/tools/migrate_evw.py
```

`domain/slots.py` may retain transient UI slot calculations, but no v15
evidence row stores slots.

## Local search/embedding/workflows

```text
message_evidence_workstation/search/scoped_search.py
message_evidence_workstation/services/client_workflows.py
message_evidence_workstation/client_api/contracts.py
message_evidence_workstation/client_api/gateway.py
message_evidence_workstation/app_bootstrap.py
message_evidence_workstation/app.py
message_evidence_workstation/ui/main_window.py
```

Inspect every additional production call site found by static scans and update
in place.

## Verification and clients

```text
scripts/verify_evw_v15.py
scripts/build_multicorpus_test_fixture.py
flutter_client/lib/main.dart
flutter_client/lib/src/evw_database.dart
flutter_client/lib/src/evw_models.dart
flutter_client/lib/src/workspace_view.dart
flutter_client/lib/src/compatibility_probe.dart
flutter_client/lib/src/native_extensions.dart
flutter_client/test/widget_test.dart
flutter_client/windows/native/SHA256SUMS.txt
flutter_client/windows/native/vec0.dll
flutter_client/README.md
README.md
docs/transformation/server_first_v1/manual_test.md
```

## Test responsibilities

Use/merge focused files:

```text
tests/test_evw_v15_schema.py
tests/test_evw_v15_migration.py
tests/test_working_corpus_revisions.py
tests/test_sparse_embedding_artifacts.py
tests/test_evidence_revision_compatibility.py
tests/test_explicit_revision_search.py
tests/test_sfv1_python_client_integration.py
tests/test_sfv1_multicorpus_e2e.py
```

Rewrite old behavioral tests. Delete tests whose only contract is v14,
activation, mutable membership, positional persisted slots, or duplicate vector
partitions.

## Server boundary

No server production file changes are required or permitted for embedding-cache
identity or clearing. Keep the existing nonempty `POST /v1/embeddings`
contract, model selection, batching, route count, admin controls, and
orchestration unchanged. Client tests prove the revised opaque scope ID and
missing-only workloads without teaching the server about EVW state.

## Required deletions

- `scripts/verify_evw_v14.py`
- runtime activation/implicit-active methods
- `working_corpus.is_active` and active index
- old working-corpus definition/membership tables
- corpus-partitioned message/chunk vec0 tables
- `vector_store_metadata`
- embedding-profile/model/version persistence in the EVW
- persisted evidence slot columns
- Python/Flutter active-corpus wording
- two-EVW manual test instructions
- proposed `--corpus-id` argument
- destructive `--reload-dataset` and `reload=True` reimport path

Historical execution logs/reports remain historical. Add a supersession note
where needed; do not rewrite prior evidence.

## Forbidden additions

- global corpus selection state;
- mutable ready revision membership;
- automatic latest/first corpus selection;
- automatic full-corpus embedding;
- vector duplication solely for corpus overlap;
- global KNN followed by membership filtering;
- silent evidence association drop/range repair;
- guessed positional-evidence migration;
- runtime schema migration;
- server EVW/corpus registry;
- capabilities/profile/cache-management server endpoint;
- hidden retries/fallbacks;
- test-only production branches.
