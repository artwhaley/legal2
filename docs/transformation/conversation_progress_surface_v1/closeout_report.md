# Conversation Progress Surface V1 — Closeout

Date: 2026-07-31

## Status

CSP1-000 through CSP1-900 implementation and automated validation are complete.

## Changed files

- `server/contracts.py` — strict provisional range model and extended `window_completed` contract.
- `server/conversation_unified.py` — emits validated accepted ranges and uncertainties at window completion.
- `message_evidence_workstation/client_api/contracts.py` — exact temporary mirror of the extended event.
- `flutter_client/lib/src/server_contracts.dart` — strict client validation.
- `flutter_client/lib/src/conversation_workflow.dart` — existing factual event labels remain the progress source.
- `flutter_client/lib/src/conversation_page.dart` — card-owned elapsed time, stages, window progress, active windows, provisional evidence, activity, and terminal summaries.
- Contract/orchestration/widget test files named by the packet — deterministic extended-event and progress coverage.
- `execution_log.md` — ticket-by-ticket evidence.

## Contract before/after

Before, `window_completed` carried window identity, counts, validation status, usage, and cost. After, it additionally carries exact `accepted_ranges` and `window_uncertainties`. Each accepted range preserves source index, authoritative thread and endpoints, nullable summary/relevance, and validated normalization records. Rejected ranges are never emitted; final ledger IDs are still assigned only during ledger construction.

## Behavior invariants

- No provider request payloads, prompts, models, retries, concurrency, window packing, synthesis inputs, or usage accounting changed.
- Existing final conversation persistence is unchanged. Progress, timer, activity, and provisional ranges remain in memory only.
- Failed and cancelled runs do not write completed conversation history.
- `IndexedStack` remains the navigation retention mechanism; cards stay alive while the selected revision remains selected.
- One page-owned timer starts before workflow execution, ticks independently of event arrival, continues while Conversation is offstage, freezes on terminal state, and is cancelled on dispose.

## Validation

- `.venv\Scripts\python.exe -m pytest -q --basetemp .tmp/csp1-full`: 193 passed, 2 deselected.
- Focused Python contract/orchestration/progress suites: 22 passed.
- `flutter test`: 30 passed.
- `flutter analyze`: no issues.
- `flutter build windows --release`: succeeded; `flutter_client/build/windows/x64/runner/Release/evw_client.exe`.
- `git diff --check` passed for packet source/test files. The pre-existing dirty `.tmp/server-8710.stdout.log` was excluded from residue checks and preserved.

## Cost and external-state proof

Automated tests use deterministic fake providers and disposable in-memory or temporary fixtures. No external provider calls, real embedding rebuilds, server activation, or real EVW mutations were used for validation.

## Manual smoke checklist

With a disposable test workspace and approved provider environment, verify one single-window run, a multi-window run, a retry, cancellation, terminal provider failure, and switching through Corpus, Search, Transcript, and Print output during and after each state. Confirm elapsed time continues offstage, completed ranges appear provisionally, final synthesis replaces provisional evidence, and no failed/cancelled run appears in completed conversation history.

No live-provider smoke run was performed as part of this packet because the acceptance gates explicitly prohibit spending provider tokens during automated validation.
