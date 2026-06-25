# T46 - Context Window Settings Only

## Goal
Make `settings.nim.context_window_tokens` the sole authoritative context limit for all budgeting and LLM input sizing. Remove silent fallback to 8192.

## Background
`resolve_model_context` currently substitutes `DEFAULT_CONTEXT_WINDOW_TOKENS = 8192` when the settings value is 0. That caused exhaustive window scan to fragment into tiny windows and thousands of API calls. Product decision: use only the Settings page value for every model until a per-model table exists later.

**Spec reference:** `04_pre_scale_hardening_spec.md` §8

## Depends On
- None (execute first in the hardening stack)

## Scope
- Rewrite `message_evidence_workstation/nim/model_context.py` `resolve_model_context`:
  - Input: `nim_settings.context_window_tokens`
  - If `<= 0`: raise `ConfigurationError` or return explicit error state — **never** substitute 8192
  - `provider_metadata` may remain in signature but must not affect budgeting
- Update `resolve_answer_budget`, settings context-budget readout, and window planner callers to use the rewritten resolver
- Settings validation UX:
  - Allow saving API settings when `context_window_tokens <= 0`
  - Block conversational **run** actions and show clear error: "Model context window must be set before using conversational features."
  - Context budget readout shows warning when value is 0
- Remove `DEFAULT_CONTEXT_WINDOW_TOKENS` from live budgeting paths (delete constant or restrict to tests only)
- Do **not** apply `settings.model_metadata` learned values to budgeting in this ticket

## Guardrails
- Do not add per-model context tables yet
- Do not change answer strategy semantics (whole-transcript vs exhaustive decision happens in T48)
- Do not remove session-coverage path behavior beyond shared context resolution

## Non-Goals
- SQL budget stats (T48)
- Window packing changes (T49)
- Settings field removal for archaic AnswerSettings (T47)

## Acceptance Criteria
- Setting context window to 128000 in Settings → `per_call_input_budget` / readout reflects 128000 minus overhead
- Setting to 0 → conversational run blocked with clear message; no 8192 in logs or window planning
- `grep DEFAULT_CONTEXT_WINDOW_TOKENS` finds no live budgeting usage (tests may retain fixtures only)

## Tests
- Unit test: `resolve_model_context` with tokens=128000 returns 128000
- Unit test: tokens=0 raises or returns error state, never 8192
- Settings readout test with configured context window
- Run focused tests for `model_context`, `token_budget`, `conversational_answer` budget paths
- `python -m pytest -q` at end of ticket
