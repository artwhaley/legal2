# T27 - Central Model Router and Provider Types

## Goal

Introduce a provider-neutral model router and shared types so feature code can request named LLM tasks without directly instantiating provider clients.

## Dependencies

T25, T26, T25B, T09, T10.

## Implementation Notes

This ticket creates the main architectural boundary. **Complete T25B first** so the router is not built around removed retrieval-fallback or obsolete range-suggestion paths.

After this work, feature code should speak to a central router with task roles and message payloads, rather than constructing provider-specific clients directly.

Preferred package shape:

```text
message_evidence_workstation/llm/
  __init__.py
  router.py
  types.py
  providers/
    __init__.py
    base.py
```

Preferred public entry point:

```python
router.chat(
    task_role=ModelTaskRole.FULL_CONTEXT_SEARCH,
    messages=messages,
    max_output_tokens=None,
    timeout_seconds=None,
    temperature=None,
)
```

The router should:

- resolve task role to user-facing role
- resolve role settings
- choose a provider implementation
- pass provider/model metadata into a normalized response type
- remain small enough that provider-specific formatting stays in provider adapters

Confirmed role mapping (post-T25B):

| Task roles | User-facing role |
|------------|------------------|
| `search_expansion` | expansion |
| `session_summary`, `session_classification`, `coverage_audit`, `full_context_search`, `windowed_context_search` | research |
| `windowed_result_merge`, `full_context_answer`, `conversational_candidate` | writing |
| `model_test`, `model_list` | (settings / provider ops) |

Do not implement retry policy in full here unless it is necessary to make the router usable. That belongs primarily in T29.

## Suggested Execution Plan

1. Add `ModelProvider`, `ModelTaskRole`, `ModelUsage`, and `ModelChatResult` types.
2. Add a provider base protocol/interface.
3. Add a central router facade that resolves role settings and provider selection.
4. Add tests for role resolution and provider dispatch using fakes.

## Files / Areas Likely Touched

- `message_evidence_workstation/llm/types.py` (new)
- `message_evidence_workstation/llm/router.py` (new)
- `message_evidence_workstation/llm/providers/base.py` (new)
- `message_evidence_workstation/config/settings.py`
- `tests/`

## Acceptance Criteria

- The repo contains a provider-neutral model router package.
- Feature code can call a router method using `task_role` without needing provider-specific objects.
- The router resolves role settings correctly for expansion, research, and writing.
- The router returns a normalized `ModelChatResult`.

## Tests / Verification

- Unit test: router resolves `search_expansion` to the expansion role settings.
- Unit test: router resolves research and writing roles correctly.
- Unit test: router dispatches to the configured provider adapter.
- Unit test: normalized response metadata includes provider, model, task role, and latency.

## Non-Goals

- No full NIM migration yet.
- No Google provider yet.
- No settings UI changes yet.

