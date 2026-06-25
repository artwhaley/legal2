# T29 - Router Retry, Error Normalization, and Metering Hooks

## Goal

Centralize retry behavior, normalized provider errors, and usage/metering metadata at the router layer so later hosted quota work has one trustworthy control point.

## Dependencies

T27, T28, T10.

## Implementation Notes

Today, timeout and provider-specific error behavior live close to the NIM client. This ticket moves cross-provider resilience and audit metadata into the router boundary while keeping provider-specific parsing where it belongs.

Router-level behavior should cover:

- retry policy for transient network and HTTP failures
- normalized app-level error types
- consistent user-facing timeout/auth/model-missing messages
- capture of provider, model, task role, max tokens, timeout, and latency
- capture of token estimates and provider usage when available

Suggested default retry policy:

- retry `408`, retryable `429`, `500`, `502`, `503`, `504`
- retry some connection/timeouts
- default `max_attempts = 2`
- conservative backoff with jitter

Do not retry:

- missing key
- missing model
- auth failure
- invalid request
- safety/content block
- known context-overflow failures unless the caller explicitly retries with reduced context

This ticket should also define the metadata contract that later gets stored in `model_run` rows or equivalent audit records.

## Suggested Execution Plan

1. Add normalized error classes or error typing at the router boundary.
2. Add router-level retry policy and backoff.
3. Extend normalized results to carry usage/metering metadata.
4. Feed that metadata into current ModelRun logging behavior.
5. Add tests for retryable and non-retryable failures.

## Files / Areas Likely Touched

- `message_evidence_workstation/llm/router.py`
- `message_evidence_workstation/llm/types.py`
- `message_evidence_workstation/nim/model_runs.py`
- `message_evidence_workstation/ui/settings_tab.py`
- `tests/`

## Acceptance Criteria

- Retry behavior is consistent across routed providers.
- User-facing error messages remain actionable and specific.
- Router-level metadata includes task role, provider, model, latency, timeout, and usage where available.
- Current ModelRun/audit flow persists enough metadata for later quota and cost tracking.

## Tests / Verification

- Unit test: router retries on `429` and succeeds on second attempt.
- Unit test: router retries on timeout and then surfaces failure when attempts are exhausted.
- Unit test: router does not retry missing API key/auth/model errors.
- Regression test: ModelRun metadata includes provider, model, and task role on success.
- Regression test: ModelRun metadata includes normalized failure type on error.

## Non-Goals

- No subscription enforcement yet.
- No dashboard or billing UI yet.

