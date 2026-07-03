# Token-Aware Context Budgeting Orchestrator

You are implementing token-aware context budgeting for the Message Evidence Workstation.

Workspace:

```text
C:\Users\artwh\OneDrive\Documents\legal2
```

## Mission

Replace character-count based whole-transcript routing with token-aware budgeting. The app should choose whole-transcript mode when the selected model can safely fit the transcript, and otherwise run exhaustive scan over token-bounded, message-preserving windows.

This is an evidence workstation, not a generic RAG toy. Recall and completeness matter. If the transcript does not fit in one call, every planned window must be inspected. Search and embeddings can assist, but they must not be the only doorway into the evidence.

## Current Behavior

- `auto` currently chooses `whole_transcript` if serialized transcript char count is under a configured char limit.
- Otherwise `auto` chooses `exhaustive_window_scan`.
- Exhaustive scan currently inspects session windows.
- Conversational sessions reuse semantic chunk boundaries, but LLM windows should not be split by arbitrary character count.
- FTS hyphen escaping is fixed and must stay fixed.

## Execute Tickets In Order

1. `01_token_estimation.md`
2. `02_model_context_resolver.md`
3. `03_provider_model_metadata.md`
4. `04_answer_settings_ui.md`
5. `05_answer_budget_resolver.md`
6. `06_token_bounded_window_planner.md`
7. `07_exhaustive_scan_token_windows.md`
8. `08_output_token_budgets.md`
9. `09_settings_logs_visibility.md`
10. `10_regression_full_suite.md`

## Implementation Protocol

- Inspect relevant code before editing.
- Keep changes incremental and testable.
- Preserve all explicit answer strategies:
  - `auto`
  - `whole_transcript`
  - `exhaustive_window_scan`
  - `retrieval_fallback`
- Preserve existing settings file compatibility.
- Do not require `tiktoken`; support it optionally.
- Do not require provider metadata; use registry/default fallback.
- Never split individual messages.
- Never let exhaustive scan omit messages.
- Keep unrelated UI redesign out of scope.
- Run focused tests after each phase and the full suite at the end.

## Key Files To Inspect

```text
message_evidence_workstation/search/conversational_answer.py
message_evidence_workstation/search/transcript.py
message_evidence_workstation/search/session_map.py
message_evidence_workstation/nim/client.py
message_evidence_workstation/nim/model_runs.py
message_evidence_workstation/config/settings.py
message_evidence_workstation/ui/settings_tab.py
message_evidence_workstation/search/fts.py
tests/test_conversational_answer.py
tests/test_session_map.py
tests/test_ui_smoke.py
tests/test_fts.py
```

## Definition Of Done

- `auto` uses token-aware context budgeting, not raw character count.
- Model context size resolves by user override, provider metadata, registry, or safe default.
- Whole transcript mode is selected when token budget says it fits.
- Exhaustive scan uses token-bounded, message-preserving windows when it does not fit.
- Settings explain the budget and routing decision.
- Process logs explain the budget and routing decision.
- Output token budgets are passed to NIM calls.
- FTS hyphen regression still passes.
- Full test suite passes:

```powershell
.\.venv\Scripts\python.exe -m pytest --basetemp .pytest_tmp
```
