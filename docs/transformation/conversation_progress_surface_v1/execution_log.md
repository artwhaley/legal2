# Execution log

The executor appends dated entries here. Record commands, results, decisions,
changed files, and ticket acceptance evidence. Do not rewrite history or hide
failed attempts.

## 2026-07-31 — CSP1-000 baseline

- Branch/commit: `main` at `41a3dfda7159cff4ca03dfbea0fcbc9e701c7942` (`second ui pass`).
- Complete pre-ticket dirty baseline:
  - Modified: `.tmp/server-8710.stdout.log`.
  - Untracked: `.tmp/glm-reasoning-ab/`, `.tmp/glm-reasoning-stream-probe/`, `.tmp/intentional-status-probe/`, `docs/transformation/conversation_progress_surface_v1/`, `scripts/probe_glm_reasoning_stream.py`, `scripts/probe_intentional_status_stream.py`, `scripts/run_glm_reasoning_ab.py`.
  - No source files were changed by CSP1-000.
- Python: repository `.venv\Scripts\python.exe`, Python 3.14.4. System Python was also 3.14.4; repository environment was used for Python tests.
- Flutter/Dart: Flutter 3.32.2, Dart 3.8.1.
- Baseline focused Python contracts/orchestration: `12 passed`; pytest exited nonzero during temporary-directory cleanup because an existing `pytest-current` directory was access-denied. No test assertion failed.
- Baseline Flutter: `flutter test` passed 29 tests; `flutter analyze` reported no issues; `flutter build windows --release` succeeded and produced `flutter_client/build/windows/x64/runner/Release/evw_client.exe`.
- Current `window_completed` contract before CSP1-100: strict server, Python mirror, and Dart contracts contain window identity, counts, validation status, token usage, and estimated cost only. No `accepted_ranges` or `window_uncertainties` fields exist.
- Current navigation retention: `WorkspaceView` renders all top-level pages in an `IndexedStack`; switching tabs leaves `ConversationPage` mounted.
- Baseline commands: `git branch --show-current`; `git rev-parse HEAD`; `git status --short`; `where.exe python`; `python --version`; `.venv\Scripts\python.exe --version`; `flutter --version`; `dart --version`; focused `python -m pytest`; `flutter test`; `flutter analyze`; `flutter build windows --release`.

## 2026-07-31 — CSP1-100 complete

- Changed `server/contracts.py` with strict `ProvisionalWindowRange` and exact `accepted_ranges` / `window_uncertainties` fields and invariants on `WindowCompletedData`.
- Added contract coverage in `tests/test_sfv1_contracts.py` for populated/empty ranges, missing/extra fields, count mismatch, duplicate and unordered source indexes, nullable text, and invalid normalizations.
- Focused result: `python -m pytest -q --basetemp .tmp/csp1-pytest-contracts tests/test_sfv1_contracts.py` — 15 passed.
- No provider, orchestration, prompt, or persistence behavior changed in this ticket.

## 2026-07-31 — CSP1-200 complete

- Changed `server/conversation_unified.py` only at the existing `window_completed` emission to serialize every validated accepted range and the validated window uncertainties. Rejected ranges remain excluded.
- Extended `tests/test_qpa1_orchestration.py` to prove valid siblings survive fabricated rejection, reversed endpoints are normalized, null descriptions remain null, and final ledger output remains unchanged.
- Focused result: `python -m pytest -q --basetemp .tmp/csp1-pytest-orchestration tests/test_qpa1_orchestration.py tests/test_sfv1_conversation.py` — 7 passed.
- No provider payload, prompt, call count, retry, concurrency, usage, or persistence path was changed.

## 2026-07-31 — CSP1-300 complete

- Updated Dart validation in `flutter_client/lib/src/server_contracts.dart` and the temporary Python mirror in `message_evidence_workstation/client_api/contracts.py` with the exact extended event shape and range invariants.
- Updated deterministic Dart fixtures and added malformed normalization coverage.
- Focused results: Python contract suite `15 passed`; Dart server-contract suite `3 passed`.
- Old `window_completed` shapes are intentionally rejected; this client and server contract move together.

## 2026-07-31 — CSP1-500 complete

- `_ConversationCard` now retains every progress event and appends every accepted range from each completed window in completion order, preserving source-range order within each event.
- The active Working card now projects exact stage, latest factual status, elapsed time, exact completed/total windows, heartbeat active-window count, uncapped read-only preliminary evidence, and expandable activity history.
- Failure/cancellation cards retain preliminary evidence and activity. Provisional ranges have no save/edit/hide controls.
- Focused result: Python progress/contract/orchestration tests `22 passed`; Flutter server-contract, widget, and workflow tests passed.

## 2026-07-31 — CSP1-600 complete

- Successful cards now show the existing final result as the authoritative presentation with a compact elapsed/window/range summary and collapsed activity history.
- Failure and cancellation cards retain incomplete activity and any provisional evidence and do not enter the existing successful persistence path.
- No progress, timer, activity, or provisional fields were added to EVW writes; existing completed-conversation persistence remains unchanged.

## 2026-07-31 — CSP1-400 complete

- `ConversationPage` now owns one periodic timer for the active card. It starts before workflow execution, updates independently of event arrival, continues while the page remains mounted offstage, freezes in `finally`, and is cancelled in `dispose`.
- Elapsed time is stored on `_ConversationCard`, not in the rebuildable Working widget.
- Focused Flutter result: `flutter analyze` clean; server-contract, widget, and workflow tests passed (15 tests).

## 2026-07-31 — CSP1-700 complete

- Removed the obsolete unreachable `_ConversationStatus` widget after replacing it with card-owned progress presentation.
- Residue review found no reasoning/status-generation calls, fake weighted percentages, provisional caps, progress persistence, prompt/provider/config changes, or navigation-state changes.
- `git diff --check` passed for all packet source/test files; the pre-existing `.tmp/server-8710.stdout.log` remains excluded because it was dirty in the CSP1-000 baseline and is owned by the running server.

## 2026-07-31 — CSP1-800 complete

- Full Python suite: `.venv\Scripts\python.exe -m pytest -q --basetemp .tmp/csp1-full` — 193 passed, 2 deselected, 1 existing Starlette deprecation warning.
- Full Flutter suite: `flutter test` — 30 tests passed.
- `flutter analyze` — no issues.
- `flutter build windows --release` — succeeded; release executable produced at `flutter_client/build/windows/x64/runner/Release/evw_client.exe`.
- Manual smoke checklist prepared without starting a live server or making provider calls: single-window run, multi-window run, retry, cancellation, terminal failure, and tab switching during/after each state. Disposable pytest directories were removed.

## 2026-07-31 — CSP1-900 complete

- Created `closeout_report.md` with contract, invariance, retention, timer, build, residue, and manual-check evidence.
- Full automated gates are green. The only excluded diff-check residue is the pre-existing running-server `.tmp/server-8710.stdout.log`; it was recorded in the baseline and preserved.
