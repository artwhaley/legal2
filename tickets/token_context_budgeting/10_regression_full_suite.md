# Ticket 10: Regression And Full Suite

## Goal

Ensure token-aware budgeting did not break existing search, answer, settings, evidence block, or UI behavior.

## Required Test Files

New or updated:

```text
tests/test_token_budget.py
tests/test_model_context.py
tests/test_window_planner.py
tests/test_conversational_answer.py
tests/test_ui_smoke.py
tests/test_fts.py
tests/test_nim_client.py
tests/test_prompts_model_runs.py
```

## Required Regression Coverage

- `200_000` chars estimates around `50_000` tokens by heuristic.
- Unknown model falls back to safe default.
- User override wins.
- Provider metadata wins.
- Registry fallback works.
- Auto selects whole transcript when token estimate fits.
- Auto selects exhaustive scan when token estimate does not fit.
- Old char limit no longer controls auto mode.
- Exhaustive window planner covers every message.
- Overlap does not cause message loss.
- NIM calls use configured output token budgets.
- Settings UI exposes context-budget controls and readout.
- FTS hyphen query does not raise.

## Full Suite

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest --basetemp .pytest_tmp
```

## Definition Of Done

- Full suite passes.
- No app startup failures.
- No accidental removal of existing answer strategies.
- No regression to evidence block creation.
- No regression to category/sidebar behavior.
- No regression to FTS hyphen handling.
- Final implementation summary lists:
  - files changed
  - tests run
  - remaining limitations
