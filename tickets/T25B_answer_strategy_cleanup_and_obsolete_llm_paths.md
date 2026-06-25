# T25B - Answer Strategy Cleanup and Obsolete LLM Path Removal

## Goal

Simplify conversational answer modes to the supported product paths, remove quiet low-recall degradation, and mark obsolete LLM call sites so later router work does not migrate dead code.

## Dependencies

T25, token-context-budgeting work, T17/T18 (being superseded for production conversational flow).

## Blocks

T28 (router migration should not wire removed paths).

## Product decisions (locked)

### Answer strategies

Remove `auto` and `retrieval_fallback`. Supported strategies after this ticket:

| Strategy | Behavior |
|----------|----------|
| `whole_transcript` (**new default**) | Try full-dataset transcript answer when token budget allows; otherwise **explicitly** route to exhaustive window scan with clear UI status (not silent degradation). |
| `exhaustive_window_scan` | Always windowed scan + merge (current behavior). |
| `session_coverage` | **Only when user explicitly selects this** in Settings. Runs session-summary prep, classification, coverage audit, then final answer. |

Migration: existing settings with `answer_strategy: "auto"` load as `whole_transcript`.

### Fail loudly, not quietly

- Do **not** offer a retrieval-fallback / harness / planner / synthesis path from the Conversational tab.
- When the app cannot answer at the requested quality level, surface a clear error or an explicit mode switch message in UI and process log — never silently fall back to lower-recall retrieval synthesis.

### Session-coverage research calls

These three run types are confirmed **research-model** work (`UserFacingModelRole.RESEARCH`):

- `session_summary`
- `session_classification`
- `coverage_audit`

They run **only** inside `run_session_coverage_answer` when answer strategy is `session_coverage`. `coverage_audit` does not run in whole-transcript or exhaustive-window modes.

### Obsolete / do not router-migrate

- `evidence_range_suggestion` / Output Formatting tab range suggestion — never requested; awaiting removal. **Exclude from T28 router migration.**

### Remove with retrieval fallback

Production removal targets (tests may be deleted or reduced):

- Conversational tab `_run_retrieval_fallback` and synthesis finish path
- Settings answer-strategy option for retrieval fallback
- `embedding_worker` `conversational_search` harness job type if only used by removed path
- Optionally delete or quarantine: `fetch_conversational_plan`, `run_conversational_synthesis`, `run_conversational_planner`, related prompt run types — or keep modules only until tests are cleaned up

Keyword expansion in Simple Search and inside retrieval harness **unit tests** remains; harness is no longer a Conversational tab user path.

## Implementation Notes

### Settings

- Default `AnswerSettings.answer_strategy` to `whole_transcript`.
- Settings combo: remove Auto and Retrieval fallback entries.
- Migrate loaded `auto` → `whole_transcript`.

### `resolve_answer_budget`

- Remove `ANSWER_STRATEGY_AUTO` and `ANSWER_STRATEGY_RETRIEVAL_FALLBACK` branches.
- Remove `ANSWER_MODE_RETRIEVAL_FALLBACK` decision path.
- `session_coverage` decision only when strategy is explicitly `session_coverage`.

### Conversational tab

- Remove `_run_retrieval_fallback`, `_run_synthesis`, `_finish_execution` synthesis chain, planner imports.
- Update status copy: no generic "Planning search strategy…" on send for non-fallback paths.
- When whole-transcript mode exceeds budget, log and show explicit message before starting exhaustive window scan.

### Obsolete range suggestion

- Keep obsolete comments in `range_suggestion.py` and `output_formatting_tab.py`.
- Do not delete T20 code in this ticket unless trivial; full removal can follow Output Formatting tab cleanup.

### Inventory (`llm/task_roles.py`)

- Mark removed/obsolete call sites (done in T25 follow-up comments).
- After code deletion, prune `RUN_TYPE_TO_TASK_ROLE` entries for planner/synthesis if run types are removed.

## Suggested Execution Plan

1. Remove retrieval-fallback UI path and settings option.
2. Remove `auto` strategy; default and migrate to `whole_transcript`.
3. Simplify `resolve_answer_budget` and conversational tab dispatch.
4. Update tests that assumed `auto` or retrieval fallback.
5. Prune or skip router inventory for obsolete paths (T28 dependency).

## Files / Areas Likely Touched

- `message_evidence_workstation/config/settings.py`
- `message_evidence_workstation/search/conversational_answer.py`
- `message_evidence_workstation/ui/conversational_tab.py`
- `message_evidence_workstation/ui/settings_tab.py`
- `message_evidence_workstation/ui/embedding_worker.py`
- `message_evidence_workstation/search/tool_runner.py` (harness only if dead)
- `message_evidence_workstation/search/synthesis.py` (removal or quarantine)
- `message_evidence_workstation/llm/task_roles.py`
- `tests/test_conversational_answer.py`
- `tests/test_conversational_synthesis.py`
- `tests/test_conversational_tools.py`
- `tests/test_model_task_roles.py`

## Acceptance Criteria

- Default answer strategy is `whole_transcript`.
- No `auto` or `retrieval_fallback` in settings UI or saved defaults for new installs.
- Conversational tab never runs planner → harness → synthesis.
- `session_coverage` runs only when explicitly selected.
- `coverage_audit` runs only as part of session-coverage flow.
- Obsolete range suggestion is documented and excluded from router migration list.
- Research role mapping documented for session prep LLM calls.

## Tests / Verification

- Unit test: `auto` settings migrate to `whole_transcript`.
- Unit test: `resolve_answer_budget` never returns `retrieval_fallback`.
- Unit test: `session_coverage` strategy returns session-coverage mode only when explicit.
- Regression test: whole-transcript → exhaustive-window escalation remains explicit (token budget).
- Remove or update tests that depend on retrieval-fallback conversational flow.

## Non-Goals

- Full deletion of Output Formatting tab or T20 range-suggestion module (unless trivial).
- Model router implementation (T27/T28).
- Role-based settings schema (T26).
