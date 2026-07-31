# File map and guardrails

## Expected Flutter structure

The executor may adjust names slightly only to match Dart conventions, but
keep responsibilities separated approximately as follows:

```text
flutter_client/lib/main.dart
flutter_client/lib/src/workspace_controller.dart
flutter_client/lib/src/workspace_view.dart
flutter_client/lib/src/evw_database.dart
flutter_client/lib/src/evw_models.dart
flutter_client/lib/src/server_gateway.dart
flutter_client/lib/src/server_contracts.dart
flutter_client/lib/src/search_workflow.dart
flutter_client/lib/src/conversation_workflow.dart
flutter_client/lib/src/corpus_page.dart
flutter_client/lib/src/search_page.dart
flutter_client/lib/src/conversation_page.dart
flutter_client/lib/src/transcript_page.dart
flutter_client/lib/src/print_output_page.dart
flutter_client/lib/src/transcript_editor.dart
flutter_client/lib/src/transcript_height_index.dart
```

Do not create separate repository/service/model files for every class. The
goal is roughly a dozen understandable source files, not generated app
architecture.

## Files in scope

- `flutter_client/**`;
- this packet's `execution_log.md` and `closeout_report.md`;
- root `.gitignore` only if required to keep Flutter source tracked.

## Files out of scope

- `server/**`;
- `message_evidence_workstation/**`;
- non-Flutter tests;
- EVW schema/migrations;
- transformation packets other than this one;
- provider/admin/config stores;
- real EVW fixtures except disposable copies under `.tmp`.

Read out-of-scope code as contract reference only.

## Guardrails

- Preserve the dirty worktree and unrelated user changes.
- Do not reset, clean, checkout, commit, push, deploy, or create a PR.
- Do not delete the Python client or server keyword endpoint.
- Do not add state-management, routing, ORM, code-generation, or design-system
  packages.
- Prefer Flutter SDK, `dart:io`, existing `sqlite3`, `crypto`, and
  `file_selector`.
- Do not create a second SQLite connection for a page or background isolate.
- Do not add silent retry, fallback, default model behavior, or automatic
  corpus selection.
- Do not cache transcript messages outside the existing bounded virtual page
  cache.
- Do not log corpus messages, prompts, responses, or vectors to ordinary
  client logs.
- Do not mutate the source real EVW during automated tests. Copy it first and
  remove the copy, WAL, SHM, and lock afterward.
- Fix mojibake in touched Flutter user-facing strings. Do not perform a broad
  unrelated encoding rewrite.
- All async callbacks must verify mounted/controller identity before updating
  UI.
- Every controller/listener/HTTP client/timer is disposed or closed.

## No-placeholder rule

A page prerequisite message is allowed. A control is allowed only if its
action works end-to-end. In particular, do not add:

- Import, filter, corpus-create, or date-picker controls;
- Build embeddings;
- Keyword expansion;
- New conversation history selector;
- Print, Export PDF, page setup, authentication, account, or billing controls.

