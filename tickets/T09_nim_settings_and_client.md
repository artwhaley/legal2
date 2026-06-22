# T09 — NIM Settings and Client

## Goal

Add concrete NVIDIA NIM settings and a testable NIM client wrapper for all MVP LLM calls.

## Dependencies

T03, T01.

## Implementation Notes

Implement settings fields for API base URL, API key, model dropdown, refresh model list, temperature, max output tokens, timeout, and streaming flag. Store non-secret settings in the workspace or a local config file. Store API key in an environment variable or local user config; do not hardcode. The client should support a basic chat completion request and model-list refresh when available. Fail loudly and log raw error details.

## Files / Areas Likely Touched

- message_evidence_workstation/nim/client.py
- message_evidence_workstation/ui/settings_tab.py
- message_evidence_workstation/config/settings.py
- tests/test_nim_client.py

## Acceptance Criteria

- Settings tab exposes NIM fields.
- Refresh model list attempts provider call and logs success/failure.
- Manual model name entry is available only after/alongside visible refresh failure.
- NimClient supports mocked chat completion success.
- NimClient surfaces and logs HTTP/auth/timeout errors.
- No other LLM provider path is introduced.

## Tests / Verification

- Mock HTTP tests for model list success/failure.
- Mock chat completion success/failure.
- Manual UI test with invalid credentials produces visible log error.

## Non-Goals

- No keyword expansion prompt yet.
- No generic provider abstraction.
- No local LLM support.
