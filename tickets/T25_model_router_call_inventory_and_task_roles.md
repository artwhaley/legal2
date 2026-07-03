# T25 - Model Router Call Inventory and Task Roles

## Goal

Inventory every current LLM call in the app and assign each one a stable internal task role so the later router work has clear behavioral boundaries.

## Dependencies

T09, T10, T11, T17, T18, token-context-budgeting work, and [03_model_router_refactor_plan.md](C:/Users/artwh/OneDrive/Documents/legal2/03_model_router_refactor_plan.md:1).

## Implementation Notes

The app currently thinks in terms of "NIM calls" and prompt-specific helpers. This ticket establishes the product-level task taxonomy that later tickets will route through. The important output here is not a new provider abstraction yet, but a complete and verified map of call sites to task roles.

Expected task roles:

- `search_expansion`
- `full_context_search`
- `windowed_context_search`
- `windowed_result_merge`
- `full_context_answer`
- `range_suggestion`
- `conversational_candidate`
- `model_test`
- `model_list`

Required work:

- Inventory all direct and indirect LLM call sites.
- Identify whether each call is feature-facing, settings/test-only, or background utility behavior.
- Assign each call site one and only one `ModelTaskRole`.
- Document ambiguous cases inline in the ticket or code comments if a follow-up decision is needed.
- Add a small shared enum/constants home for task roles if it makes later tickets safer, but do not introduce the router yet.

The inventory should cover at least:

- keyword expansion
- conversational planner/tool selection
- exhaustive or whole-transcript analysis
- windowed analysis
- synthesis / merge / final answer
- range suggestion
- model list refresh
- model test button flows

Preferred discovery command:

```powershell
rg -n "NimClient|chat_completion|list_models|test_model|expand_keywords|range_suggestion|tool_runner|synthesis|conversational" message_evidence_workstation tests
```

## Suggested Execution Plan

1. Inventory all LLM entry points and helper layers.
2. Create a shared task-role enum/constants module if needed.
3. Annotate each call site with its intended role or route it through a small helper that makes the role explicit.
4. Add regression tests for the highest-risk role mappings.

## Files / Areas Likely Touched

- `message_evidence_workstation/nim/`
- `message_evidence_workstation/search/keyword_expansion.py`
- `message_evidence_workstation/search/conversational_answer.py`
- `message_evidence_workstation/search/conversational_eval.py`
- `message_evidence_workstation/search/synthesis.py`
- `message_evidence_workstation/search/range_suggestion.py`
- `message_evidence_workstation/search/tool_runner.py`
- `message_evidence_workstation/ui/settings_tab.py`
- `tests/`

## Acceptance Criteria

- Every current LLM call has a documented and testable task role.
- There are no remaining direct model calls whose purpose is unclear.
- Settings/test-only calls are distinguished from user workflow calls.
- The inventory is sufficient to support a later central router without rediscovering call semantics.

## Tests / Verification

- Unit test: task-role enum/constants load correctly.
- Regression test: keyword expansion maps to `search_expansion`.
- Regression test: synthesis/final answer flow maps to `windowed_result_merge` or `full_context_answer` as appropriate.
- Regression test: settings model test flow maps to `model_test`.

## Non-Goals

- No provider abstraction yet.
- No Google provider implementation yet.
- No settings UI redesign yet.

## Follow-on (T25B)

T25 inventory includes call sites slated for removal or router exclusion:

- **Obsolete:** `evidence_range_suggestion` (Output Formatting tab) — do not router-migrate.
- **Removed in T25B:** retrieval fallback (planner, harness LLM path, synthesis) from Conversational tab.
- Session-coverage-only research prep calls were removed with the obsolete `session_coverage` mode.
