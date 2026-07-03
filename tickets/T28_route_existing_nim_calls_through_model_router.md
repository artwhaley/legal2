# T28 - Route Existing NIM Calls Through Model Router

## Goal

Preserve current NIM-backed behavior while migrating existing feature code to the new central router boundary.

## Dependencies

T25, T26, T25B, T27, T09, T10, T11, token-context-budgeting work.

## Implementation Notes

This ticket is the compatibility bridge. The app should still behave like the current NIM-driven desktop app, but the feature modules should stop owning provider details.

**Prerequisite:** T25B must be complete so migration targets exclude removed paths.

Migration targets (active product LLM calls):

- keyword expansion (Simple Search + any remaining harness test utilities)
- whole-transcript and windowed context analysis
- windowed result merge
- final answer generation (`full_context_answer`)
- obsolete session-coverage research prep calls were removed
- settings model test
- settings model list refresh

**Explicitly exclude from router migration:**

- `evidence_range_suggestion` / Output Formatting range suggestion (obsolete, T25B)
- `conversational_search_planner` and `conversational_search_synthesis` (removed with retrieval fallback, T25B)

The NIM provider adapter should reuse existing behavior where practical:

- `/models` model listing
- `/chat/completions`
- timeout handling
- unsupported system-role fallback
- current message layout behavior
- existing user-facing error guidance where compatible

Migration targets include at least:

- keyword expansion
- whole-transcript and windowed context analysis
- result merge / final answer
- settings model test
- settings model list refresh

It is fine if `message_evidence_workstation/nim/` remains in place as the NIM-specific implementation home. The key requirement is that call sites stop constructing `NimClient` directly outside provider code.

## Suggested Execution Plan

1. Implement a NIM provider adapter on top of existing NIM behavior.
2. Convert one low-risk call path first, preferably keyword expansion.
3. Convert remaining feature call paths to the router.
4. Convert settings model-list and model-test flows.
5. Remove or minimize direct `NimClient` instantiation outside provider code.

## Files / Areas Likely Touched

- `message_evidence_workstation/llm/providers/nim_provider.py` (new)
- `message_evidence_workstation/search/keyword_expansion.py`
- `message_evidence_workstation/search/conversational_answer.py`
- `message_evidence_workstation/search/tool_runner.py` (keyword expansion helper only if still used)
- `message_evidence_workstation/ui/settings_tab.py`
- `tests/test_nim_client.py`
- `tests/test_conversational_answer.py`
- related conversational tests

## Acceptance Criteria

- Existing NIM-backed features still work through the new router.
- Direct feature-level `NimClient` construction is removed or reduced to provider internals.
- Existing NIM behavior such as system-role fallback is preserved.
- Model list refresh and model test in settings continue to work.

## Tests / Verification

- Regression test: keyword expansion still works and is routed as `search_expansion`.
- Regression test: whole-transcript and windowed answers route to correct writing/research roles.
- Regression test: model test flow still reports success/failure cleanly.
- Regression test: NIM unsupported system-role fallback still works.
- Full existing NIM/conversational tests pass after migration.

## Non-Goals

- No Google provider behavior yet.
- No retry policy redesign beyond what is required to preserve behavior.
