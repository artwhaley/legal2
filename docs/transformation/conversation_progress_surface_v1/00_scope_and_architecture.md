# Scope and architecture

## Objective

Give a human useful, truthful information while a conversational search is
running. The UI must remain responsive, elapsed time must continue advancing
during event-free provider work, completed windows must expose provisional
validated evidence, and the full run state must survive tab changes for the
life of the selected working-corpus session.

This is not a reasoning-stream feature. It must not ask a model to narrate
progress or create any additional model call.

## Current facts

- `WorkspaceView` uses an `IndexedStack`. `ConversationPage` remains mounted
  when another top-level tab is selected.
- `ConversationPage` owns in-memory conversation cards. It currently clears
  them when the selected revision changes.
- `ConversationWorkflow` already receives strict NDJSON progress events and
  publishes readable labels.
- The current working card shows only the latest event and a window progress
  bar. It has no independently advancing elapsed timer.
- The server already emits planning, accounting, heartbeat, retry, window,
  evidence-validation, ledger, compaction, synthesis, warning, failure, and
  completion events.
- `window_completed` currently exposes counts and usage only. The accepted
  range summaries are not sent until the final completed result. Flutter
  cannot display truthful provisional evidence without one narrow server
  contract extension.

## Binding architecture

### Server responsibility

The server adds every validated accepted range to its existing
`window_completed` event. It does not make a new provider call, change a
prompt, change orchestration, persist anything, or assign final ledger IDs
early.

### Flutter responsibility

Flutter projects the existing event stream into a session-only run display:

- live elapsed time;
- current factual stage;
- exact window progress and active-window count;
- visible retry, warning, unavailable-window, failure, and cancellation state;
- provisional validated evidence as windows finish;
- complete activity history;
- a compact terminal run summary after success, failure, or cancellation.

### Session lifetime

All cards and progress remain in memory while the application remains open and
the same working-corpus revision remains selected.

Switching tabs must not:

- dispose the conversation page;
- cancel an active request;
- stop or freeze the elapsed timer;
- clear cards, activity, provisional ranges, terminal results, or errors;
- reset expansion state unnecessarily.

Closing the application discards session-only progress. The existing completed
conversation persistence remains unchanged.

Changing the selected working-corpus revision continues to clear conversation
cards. This prevents ranges from revision A appearing against revision B's
transcript. Do not invent a per-revision session-history map in this phase.

### EVW persistence boundary

Do not persist:

- progress events;
- heartbeats;
- retry history;
- provisional window evidence;
- elapsed timer ticks;
- provider-operation details beyond fields already present in the final
  server result.

On successful completion, preserve the current EVW write exactly: visible
prompt, presented response, mode, and final server result. Failed or cancelled
runs create no completed conversation record.

## Explicit non-goals

- Raw or summarized reasoning streams.
- Model-authored status messages.
- Additional status-generation calls.
- Prompt, provider, model, tokenizer, context-budget, retry, or admin changes.
- EVW schema or migration changes.
- Authentication, billing, BYOK, or account work.
- Python desktop UI or workflow work.
- Search, transcript, evidence-editing, or print behavior changes.
- Navigation or state-management frameworks.
- Persistence of session state across application restarts.
- Session history keyed across multiple revisions.

## Allowed source surface

Expected product edits are limited to:

- `server/contracts.py`
- `server/conversation_unified.py`
- `flutter_client/lib/src/server_contracts.dart`
- `flutter_client/lib/src/conversation_workflow.dart`
- `flutter_client/lib/src/conversation_page.dart`

Expected test edits are limited to:

- `tests/test_sfv1_contracts.py`
- `tests/test_qpa1_orchestration.py`
- `flutter_client/test/server_contracts_test.dart`
- `flutter_client/test/conversation_workflow_test.dart`
- `flutter_client/test/server_gateway_test.dart` only where fixtures require it
- `flutter_client/test/widget_test.dart`

The strict temporary Python API-contract mirror may be changed only as needed
to mirror the extended server event:

- `message_evidence_workstation/client_api/contracts.py`

Do not change the Python GUI, Python workflow, or any Python feature behavior.
If another file is genuinely required, document why in `execution_log.md`
before editing it.

