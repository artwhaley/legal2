# Model Router Refactor Plan

## Goal

Refactor the current single-provider NIM call pattern into a central model router that supports task-specific model selection now and additional providers soon. The immediate product goal is to experiment with separate models for search expansion, research analysis, and answer writing. The strategic goal is to create the same backend boundary a hosted subscription product will need for quotas, abuse controls, audit logs, and provider flexibility.

This plan intentionally keeps the current PySide desktop app as the prototyping surface while moving LLM behavior toward a server-friendly architecture.

## Current Understanding

The app currently makes LLM calls for these broad jobs:

- Search term expansion.
- Full-context transcript/document analysis and answer.
- Windowed context analysis and merge.
- Session-coverage research prep (summaries, classification, coverage audit) and final answer.
- Settings model test and model list.

**Removed / obsolete (T25B):** retrieval-fallback planner and synthesis; Output Formatting range suggestion.

The exact call-site inventory is in `message_evidence_workstation/llm/task_roles.py` (T25).

## Target User-Facing Model Roles

Expose three practical model roles in settings:

- `Expansion model`: cheap and fast model for search term expansion.
- `Research model`: strong analyzer for full-context and windowed context searches.
- `Writing model`: good synthesizer for windowed merge, final answers, and polished output.

Internally, these roles should map to more specific task roles so the backend can meter and audit accurately.

## Internal Task Roles

Add a task-role enum or equivalent constants:

```text
search_expansion
full_context_search
windowed_context_search
windowed_result_merge
full_context_answer
conversational_candidate
model_test
model_list
```

Session-coverage-only research prep (same research model role):

```text
session_summary      -> maps via run_type in session_coverage flow
session_classification
coverage_audit
```

Obsolete — do not router-migrate:

```text
range_suggestion       # Output Formatting dead code (T25B)
```

Removed — do not router-migrate:

```text
conversational_search_planner   # retrieval fallback (T25B)
conversational_search_synthesis
```

Initial role-to-user-setting mapping:

```text
search_expansion            -> expansion
full_context_search         -> research
windowed_context_search     -> research
session_summary             -> research   (session_coverage only)
session_classification      -> research   (session_coverage only)
coverage_audit              -> research   (session_coverage only)
windowed_result_merge       -> writing
full_context_answer         -> writing
conversational_candidate    -> writing
model_test                  -> selected provider/model being tested
model_list                  -> provider-level operation
```

`coverage_audit` runs only inside explicit `session_coverage` answer mode, after session classification and before the final `coverage_session_answer` call.

## Provider Scope

Implement NIM through the router first, preserving existing behavior.

Add Google AI Studio as the second concrete provider in Phase 6. Google is especially important for long-context transcript/document analysis and should be tested for the `Research model` role.

Do not implement Anthropic, OpenAI, or local endpoints in this patch. Shape the interfaces so they can be added without another broad refactor.

## Proposed File Structure

Create a new package:

```text
message_evidence_workstation/llm/
  __init__.py
  router.py
  types.py
  providers/
    __init__.py
    base.py
    nim_provider.py
    google_provider.py
```

Keep existing `message_evidence_workstation/nim/` modules initially. `nim_provider.py` should wrap or reuse existing NIM client behavior rather than duplicate all details. Over time, NIM-specific code can migrate behind the provider.

## Core Data Types

Define provider-neutral request and response types.

```python
class ModelProvider(str, Enum):
    NIM = "nim"
    GOOGLE = "google"


class ModelTaskRole(str, Enum):
    SEARCH_EXPANSION = "search_expansion"
    FULL_CONTEXT_SEARCH = "full_context_search"
    WINDOWED_CONTEXT_SEARCH = "windowed_context_search"
    WINDOWED_RESULT_MERGE = "windowed_result_merge"
    FULL_CONTEXT_ANSWER = "full_context_answer"
    RANGE_SUGGESTION = "range_suggestion"
    CONVERSATIONAL_CANDIDATE = "conversational_candidate"
    MODEL_TEST = "model_test"
    MODEL_LIST = "model_list"


@dataclass(slots=True)
class ModelRoleConfig:
    provider: ModelProvider
    model: str
    api_base_url: str = ""
    api_key: str = ""
    temperature: float = 0.2
    max_output_tokens: int = 4096
    timeout_seconds: float = 600.0
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ModelUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ModelChatResult:
    content: str
    provider: ModelProvider
    model: str
    task_role: ModelTaskRole
    raw_response: dict[str, Any]
    latency_ms: int
    usage: ModelUsage | None = None
    message_layout: str = "provider_default"
```

The router should accept OpenAI-style internal messages:

```python
messages: list[dict[str, str]]
```

Providers are responsible for adapting those messages to provider-specific request bodies.

## Settings Model

Extend settings from one global NIM config to role-based model configs.

Current `NimSettings` can remain for backward compatibility during migration. Add a new settings object such as:

```python
@dataclass
class ModelRoutingSettings:
    expansion: ModelRoleConfig
    research: ModelRoleConfig
    writing: ModelRoleConfig
```

Migration behavior:

- If role-based settings do not exist, seed all three roles from existing NIM settings.
- Preserve existing `MEW_NIM_API_KEY` behavior for NIM roles.
- Add `MEW_GOOGLE_API_KEY` for Google roles.
- Keep app-stored API keys supported for desktop prototyping.
- When both env var and stored key exist, env var wins.

Recommended defaults:

```text
expansion.provider = nim
research.provider = nim
writing.provider = nim
```

All three default to the existing selected NIM model until the user configures role-specific choices.

## Router Behavior

Add a central router facade:

```python
router.chat(
    task_role=ModelTaskRole.FULL_CONTEXT_SEARCH,
    messages=messages,
    max_output_tokens=None,
    timeout_seconds=None,
    temperature=None,
)
```

Responsibilities:

- Resolve task role to user-facing model role.
- Resolve provider credentials and environment overrides.
- Instantiate the provider adapter.
- Apply default output-token and timeout settings.
- Perform retry/backoff for transient errors.
- Normalize provider errors into one app-level error type.
- Return `ModelChatResult`.
- Write or provide enough metadata for ModelRun audit records.

Do not let feature code instantiate `NimClient` directly after migration. Feature code should call the router with a task role.

## Provider Interface

Create a minimal provider base class:

```python
class ModelProviderClient(Protocol):
    def list_models(self) -> list[ModelInfo]:
        ...

    def chat_completion(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        temperature: float,
        max_output_tokens: int,
        timeout_seconds: float,
        task_role: ModelTaskRole,
    ) -> ModelChatResult:
        ...
```

Keep the interface small. Do not try to model every provider feature up front.

## NIM Provider

NIM provider should reuse existing behavior:

- Existing API base URL default: `https://integrate.api.nvidia.com/v1`.
- Existing `/models` model list behavior.
- Existing `/chat/completions` request shape.
- Existing timeout handling.
- Existing unsupported system-role fallback from `message_roles.py`.
- Existing context-limit metadata behavior where possible.
- Existing NIM error formatting should be adapted into provider-neutral errors.

The first implementation should preserve current tests before adding Google.

## Google AI Studio Provider

Add Google AI Studio provider support after NIM is routed.

Environment variable:

```text
MEW_GOOGLE_API_KEY
```

Provider responsibilities:

- Call Gemini generate-content style endpoint.
- Adapt internal messages to Google content parts.
- Map system messages to Google `systemInstruction` where supported.
- Support `temperature`.
- Support `maxOutputTokens`.
- Support request timeout.
- Parse candidate text into `ModelChatResult.content`.
- Capture usage metadata when returned.
- Normalize blocked/safety responses into useful errors.
- Normalize model-not-found, auth, quota, and timeout failures.

Initial Google model list can be either:

- implemented through Google model listing if straightforward, or
- manual model entry first, with model listing deferred.

Manual model entry is acceptable for the first Google provider patch because AI Studio model names change and the app already supports manual NIM model entry.

Likely test targets:

```text
gemini-1.5-pro
gemini-1.5-flash
gemini-2.0-flash
gemini-2.5-flash
gemini-2.5-pro
```

The implementation should not hard-code this list as authoritative. Treat it as useful UI seed data or documentation only.

## Retry And Error Policy

Centralize retry behavior in the router.

Retry by default:

- HTTP 408.
- HTTP 429 when provider guidance allows retry.
- HTTP 500, 502, 503, 504.
- Network connection reset.
- Timeout only if the task has not already used a very long timeout and retry count remains.

Do not retry by default:

- Missing API key.
- Missing model.
- Invalid request shape.
- Authentication failure.
- Permission or entitlement failure.
- Context length exceeded unless the calling code can reduce context.
- Safety/content block.

Suggested initial retry policy:

```text
max_attempts = 2
base_delay_seconds = 1.0
jitter = true
```

Keep this conservative in the desktop app. Server architecture can later add stronger queue-based retry.

## Audit And Metering

Every routed call should include:

- `task_role`.
- user-facing role: expansion, research, or writing.
- provider.
- model.
- request latency.
- timeout setting.
- max output token setting.
- estimated input tokens when available.
- provider usage metadata when available.
- final success/failure status.
- normalized error type on failure.

This should either extend existing `model_run` records or add fields in a backward-compatible way.

This metadata is the bridge to later subscription controls:

- monthly conversational session quota.
- per-user token usage.
- per-workspace token usage.
- per-provider cost attribution.
- abuse detection.
- admin cost dashboards.

For now, no billing logic is required. The patch should create clean hooks.

## UI Settings Plan

Update Setup / Settings to include a model routing section.

Recommended controls:

- Provider selector for `Expansion model`.
- Model selector or manual entry for `Expansion model`.
- Provider selector for `Research model`.
- Model selector or manual entry for `Research model`.
- Provider selector for `Writing model`.
- Model selector or manual entry for `Writing model`.
- API key fields grouped by provider:
  - NIM API key.
  - Google AI Studio API key.
- Test buttons:
  - Test expansion model.
  - Test research model.
  - Test writing model.

Convenience behavior:

- Add a "Use same provider/model for all roles" action or checkbox.
- Existing NIM model settings should continue to populate all roles on first migration.
- If Google model listing is deferred, allow manual Google model entry.

## Call-Site Migration Inventory

Verified inventory: `message_evidence_workstation/llm/task_roles.py` (T25).

Active migration areas:

- `message_evidence_workstation/search/keyword_expansion.py`
- `message_evidence_workstation/search/conversational_answer.py`
- `message_evidence_workstation/search/session_summaries.py`
- `message_evidence_workstation/search/coverage_audit.py`
- `message_evidence_workstation/ui/conversational_tab.py`
- `message_evidence_workstation/ui/simple_search_tab.py`
- `message_evidence_workstation/ui/settings_tab.py`
- `message_evidence_workstation/nim/model_runs.py`

Exclude from migration (T25B): `range_suggestion.py`, retrieval-fallback planner/synthesis paths.

## Implementation Phases

### Phase 1: Inventory And Naming

- Inventory every LLM call site.
- Assign each call site a `ModelTaskRole`.
- Document any ambiguous calls.
- Add tests that assert expected task-role mapping for high-risk flows.

Acceptance:

- There is a complete call-site inventory.
- Each current LLM call has a planned task role.

### Phase 2: Settings Schema

- Add role-based model routing settings.
- Add migration from existing NIM settings.
- Add `MEW_GOOGLE_API_KEY` env var support.
- Preserve `MEW_NIM_API_KEY`.

Acceptance:

- Existing settings files still load.
- Fresh settings default all roles to current NIM behavior.
- Env vars override stored keys.

### Phase 3: Router And NIM Provider

- Add provider-neutral types.
- Add router facade.
- Add NIM provider adapter.
- Route one low-risk call first, preferably search expansion.
- Then route remaining NIM calls.

Acceptance:

- Existing NIM behavior is preserved.
- Existing NIM tests pass after being updated to router boundaries.
- Feature modules no longer instantiate `NimClient` directly except inside provider code or compatibility tests.

### Phase 4: Central Retry And Error Handling

- Add router-level retry policy.
- Normalize provider errors.
- Keep user-facing error messages specific and actionable.
- Preserve existing timeout guidance.

Acceptance:

- Transient errors are retried according to policy.
- Missing key/model errors are not retried.
- Tests cover retryable and non-retryable failures.

### Phase 5: Audit And Metering Metadata

- Add task role, provider, model, and usage metadata to model-run logging.
- Capture estimated token counts where available.
- Capture provider usage metadata where available.

Acceptance:

- ModelRun viewer/logs show provider, model, task role, and status.
- Tests assert metadata is persisted for success and failure.

### Phase 6: Google AI Studio Provider

- Add Google provider config.
- Add Google chat/generate-content adapter.
- Add `MEW_GOOGLE_API_KEY`.
- Add manual model entry for Google.
- Add model test support for Google.
- Add model listing only if it is straightforward and reliable.

Acceptance:

- A Google model can be assigned to expansion, research, or writing.
- Router can execute a Google-backed chat call.
- Google errors are normalized.
- Google usage metadata is captured when returned.
- Tests mock Google HTTP responses and failures.

### Phase 7: Settings UI

- Add role-specific provider/model controls.
- Add provider key controls.
- Add per-role test buttons.
- Preserve simple default behavior for users who want one model.

Acceptance:

- User can configure NIM for all roles.
- User can configure Google for at least one role.
- User can test each configured role.
- Settings survive restart.

### Phase 8: Regression And Smoke

- Run full automated tests.
- Manually smoke:
  - NIM expansion.
  - NIM research.
  - NIM writing.
  - Google expansion or test call.
  - Google research on a small transcript.
  - Mixed-provider configuration.
  - Missing API key failure.
  - Bad model failure.

Acceptance:

- Full test suite passes.
- Existing workflows still function.
- Mixed role/provider behavior is visible in model-run logs.

## Test Plan

Add focused tests for:

- Settings migration from old NIM-only settings.
- Role-to-task mapping.
- Router provider selection.
- NIM provider request/response adaptation.
- Google provider request/response adaptation.
- Google system instruction adaptation.
- Retry on 429/5xx.
- No retry on missing key/auth/model errors.
- ModelRun metadata persistence.
- Settings UI smoke for role controls.

Keep provider HTTP tests mocked. Do not require live NIM or Google credentials in automated tests.

## Risks

- Provider abstraction can become too generic and hide important provider differences.
- Google safety/block responses may not map neatly to existing error flows.
- Existing NIM system-role fallback should not be lost during migration.
- Context-limit handling may differ by provider and should stay provider-aware.
- Settings UI can become cluttered if provider/model/role controls are not grouped carefully.
- ModelRun schema changes need backward-compatible migrations.

## Non-Goals For This Patch

- No subscription billing implementation.
- No account system.
- No hosted backend server.
- No Anthropic/OpenAI provider implementation.
- No full output-formatting redesign.
- No removal of the existing desktop app.
- No live-provider tests that require real API keys.

## Server Architecture Notes

This refactor should make the later server extraction easier by creating a single backend-owned choke point for model usage. In the hosted product, the router becomes the place where the backend enforces:

- user identity.
- workspace ownership.
- subscription tier.
- monthly session quota.
- token and document size caps.
- provider/model permissions.
- abuse controls.
- cost accounting.
- audit exports.

Flutter should eventually call server APIs that request named product operations. It should not know which provider/model fulfilled those operations.

## Recommended Implementation Order

1. Inventory direct model calls and assign task roles (T25 — done).
2. Answer strategy cleanup and obsolete path removal (T25B).
3. Add role-based settings with NIM migration (T26).
4. Build router types and NIM provider (T27).
5. Convert active LLM call paths through router (T28).
6. Centralize retry and error handling (T29).
7. Add model-run metadata (T29).
8. Add Google provider (T30).
9. Add settings UI controls (T31).
10. Run full regression and manual smoke tests (T32).

