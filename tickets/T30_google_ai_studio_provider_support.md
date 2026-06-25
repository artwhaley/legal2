# T30 - Google AI Studio Provider Support

## Goal

Add Google AI Studio as the second concrete model provider so any role can be backed by Gemini models through the central router.

## Dependencies

T26, T27, T28, T29.

## Implementation Notes

Google AI Studio support should be added only after the router and NIM provider path are working. The desktop app should be able to point `Expansion`, `Research`, or `Writing` at Google-backed models without special-case feature code.

Required support:

- `MEW_GOOGLE_API_KEY` env override
- stored Google API key in settings
- Gemini chat/generate-content request formatting
- system message adaptation using `systemInstruction` or equivalent where supported
- timeout handling
- output token cap handling
- usage metadata capture when returned
- normalized errors for auth, quota, timeout, blocked response, and missing model

Initial model handling:

- manual model entry is acceptable
- model listing is optional if it is straightforward and reliable

Likely starting test models:

- `gemini-1.5-pro`
- `gemini-1.5-flash`
- `gemini-2.0-flash`
- `gemini-2.5-flash`
- `gemini-2.5-pro`

Do not hard-code these as a definitive supported list. Treat them as useful starter defaults only if a UI seed list is introduced.

## Suggested Execution Plan

1. Add a Google provider adapter under the router provider package.
2. Add request/response mapping from internal messages to Gemini content payloads.
3. Add Google key resolution from env and stored settings.
4. Add manual model-entry support in settings-backed config.
5. Add mocked tests for success, blocked response, auth failure, quota failure, and timeout.

## Files / Areas Likely Touched

- `message_evidence_workstation/llm/providers/google_provider.py` (new)
- `message_evidence_workstation/llm/router.py`
- `message_evidence_workstation/config/settings.py`
- `message_evidence_workstation/ui/settings_tab.py`
- `tests/`

## Acceptance Criteria

- Any model role can be configured to use provider `google`.
- The router can execute a Google-backed chat call and return normalized content.
- Google auth, quota, timeout, and blocked-response failures are normalized into useful app errors.
- Usage metadata is captured when Google returns it.

## Tests / Verification

- Unit test: Google provider success path returns normalized `ModelChatResult`.
- Unit test: system messages are mapped into the expected Google request shape.
- Unit test: blocked/safety response becomes a normalized error.
- Unit test: auth and quota failures surface correct normalized error types.
- Unit test: `MEW_GOOGLE_API_KEY` overrides stored settings.

## Non-Goals

- No Anthropic or OpenAI provider implementation.
- No live Google API integration tests requiring real credentials.

