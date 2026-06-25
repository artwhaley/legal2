# T32 - Model Router Regression and Smoke Suite

## Goal

Lock down the router refactor with focused automated tests and a manual smoke checklist covering NIM-only, Google-only, and mixed-provider role configurations.

## Dependencies

T25, T26, T25B, T27, T28, T29, T30, T31.

## Implementation Notes

This ticket is the hardening pass for the refactor. The app is changing from one global provider/model path to a routed, role-based setup, so the tests need to prove we did not quietly break search expansion, conversational analysis, synthesis, settings flows, or ModelRun logging.

Automated coverage should include:

- task-role mapping
- settings migration
- router dispatch
- NIM request/response behavior through the router
- Google request/response behavior through the router
- retry and error normalization
- settings UI role controls
- ModelRun metadata persistence

Manual smoke should include:

- all roles set to NIM
- expansion on NIM, research on Google, writing on NIM
- research and writing on Google with expansion on NIM
- missing NIM key failure
- missing Google key failure
- bad model name failure
- settings restart persistence

## Suggested Execution Plan

1. Add or update automated tests for each major behavior introduced by T25-T31.
2. Expand the smoke-test documentation with a model-router section.
3. Run the full test suite.
4. Perform manual mixed-provider smoke verification.

## Files / Areas Likely Touched

- `tests/`
- `docs/smoke_test_checklist.md`
- possibly `docs/known_limitations.md`

## Acceptance Criteria

- Full test suite passes with the router/provider refactor enabled.
- Mixed-role provider configurations work without code changes.
- Settings survive restart with per-role provider/model assignments intact.
- ModelRun/audit behavior remains visible and useful for debugging.

## Tests / Verification

- Full `pytest` suite.
- Manual smoke: NIM-only role configuration.
- Manual smoke: mixed NIM/Google role configuration.
- Manual smoke: provider failure cases surface clear UI/log messages.
- Manual smoke: restart preserves role settings and provider selection.

## Non-Goals

- No production load testing.
- No billing or quota enforcement validation yet.

