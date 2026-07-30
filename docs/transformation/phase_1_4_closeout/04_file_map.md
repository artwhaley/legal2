# Target File Map and Deletions

This map is binding. Do not create parallel `*_v2`, `new_*`, or legacy wrapper
modules outside it. Existing large UI/search modules may be edited in place.

## Database and domain

```text
message_evidence_workstation/domain/constants.py       SCHEMA_VERSION = 14
message_evidence_workstation/domain/search_scope.py    exact scope dataclasses
message_evidence_workstation/db/schema.py              one authoritative v14 DDL
message_evidence_workstation/db/workspace_lock.py      held OS sidecar lock
message_evidence_workstation/db/workspace_store.py     writer thread + readers/lifecycle
message_evidence_workstation/db/corpus_repository.py   definitions/membership/index state
message_evidence_workstation/db/conversation_repository.py
message_evidence_workstation/db/workspace.py           v14 create/open validation only
message_evidence_workstation/tools/migrate_evw.py      explicit compact-copy CLI
```

Delete `db/v13_repositories.py`, `db/migration_v13_compact.py`, and
`db/migrations.py` after their needed canonical-copy/schema logic is
incorporated. Schema creation lives in `schema.py`; old-version handling lives
only in the explicit migration tool.

`AppContext` contains `workspace: WorkspaceStore`, `dataset_id`, logger/event
bus, and client workflow services. It does not expose a raw connection.

## Local indexing and search

Retain and rewrite in place:

```text
embeddings/chunking.py
embeddings/index_jobs.py
embeddings/sqlite_vec_backend.py
search/fts.py
search/spellfix.py
search/transcript.py
search/window_planner.py
search/dataset_budget.py
search/embedding_search.py
search/exhaustive_hints.py
search/conversational_answer.py
search/evidence_ledger.py
search/ledger_validator.py
search/grouping.py
search/result_models.py
search/date_scope.py
```

Every public operation in these modules uses the exact scope types. Delete
dataset-only public search methods, optional scope parameters, and deprecated
aliases.

Delete from the client:

```text
embeddings/adapters.py
embeddings/model_registry.py
embeddings/remote_adapter.py
embeddings/service.py
embeddings/dataset_embedding_cache.py
search/tool_runner.py
search/synthesis.py
search/retrieval_assist.py
```

If useful deterministic hint/fusion logic remains in a deleted module, move
only that logic into `exhaustive_hints.py` with scope-required signatures.
Delete `search/conversational_eval.py` from production; evaluation harnesses
belong under `tests/` or `scripts/`.

## Client HTTP and orchestration

```text
message_evidence_workstation/client_api/contracts.py   v2 response validation DTOs
message_evidence_workstation/client_api/gateway.py     one HTTP attempt per call
message_evidence_workstation/services/corpus_builder.py
message_evidence_workstation/services/client_workflows.py
```

Delete the entire client `message_evidence_workstation/llm/` and
`message_evidence_workstation/nim/` directories after moving server-owned code.
There is no resolver singleton, provider-neutral router, or local model test in
the desktop package.

## Server

```text
server/__main__.py
server/app.py
server/config.py
server/contracts.py
server/prompts.py
server/prompt_set_v2.json
server/routing.py
server/model_types.py
server/errors.py
server/providers/nim.py
server/providers/google.py
server/embeddings.py
```

Delete `server/prompt_set_v1.json` and every v1 contract/route after retargeting.
Server modules import no client package. Do not add a server database module.

## Python UI

```text
ui/working_corpus_tab.py       one corpus definition/preview/build surface
ui/settings_tab.py             server + client-owned settings only
ui/home_tab.py                 import and route to corpus build
ui/simple_search_tab.py        ClientWorkflowService only
ui/conversational_tab.py       ClientWorkflowService only
ui/main_window.py              scope/status propagation and clean close
ui/search_worker.py            read-only scoped local search
ui/embedding_worker.py         batch read/HTTP/write sequencing via services
```

Remove every provider/model/embedding-download widget and handler from
`settings_tab.py`; do not instantiate and hide them. Remove NIM/provider wording
from Home/Search/Conversation status text.

All other evidence/artifact/transcript UI modules receive WorkspaceStore-backed
repositories for writes. They may use explicit read-only readers for paged
display.

## Flutter

Use exactly the handwritten Dart map in `03_flutter_viewer_contract.md`. Add
only the official `file_selector` dependency. `main.dart` must no longer contain
the probe implementations.

## Verification scripts and tests

```text
scripts/verify_package_boundaries.py
scripts/verify_evw_v14.py
tests/fixtures/scope_boundary_v14.*
tests/test_workspace_store.py
tests/test_evw_v14_schema.py
tests/test_evw_v14_migration.py
tests/test_working_corpus_scope.py
tests/test_scoped_fts.py
tests/test_scoped_vectors.py
tests/test_server_v2.py
tests/test_client_workflows.py
tests/test_phase_closeout_e2e.py
```

Names above replace old architecture-specific test modules where appropriate.
Delete tests for client ModelRouter/providers/prompts/model runs, local adapters,
v1 routes, dataset-only searches, and automatic runtime migration. Keep and
adapt behavioral evidence/artifact/transcript tests.
