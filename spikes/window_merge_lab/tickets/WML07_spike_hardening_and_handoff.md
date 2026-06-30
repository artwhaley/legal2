# WML07 - Spike Hardening And Handoff

## Goal
Finish the spike with docs, smoke checks, and a recommendation template for production merge redesign.

## Depends On
- WML06

## Scope
- Update `README.md` with:
  - launch instructions
  - workflow
  - strategy descriptions
  - safety notes
- Add `RECOMMENDATION.md` template or generator.
- Add lightweight smoke tests where practical for non-GUI loader/strategy/evaluator code.
- Manually verify GUI launch.
- Document known limitations.

## Guardrails
- Do not patch production conversational merge logic in this ticket.
- Recommendations are allowed, production changes are not.

## Acceptance Criteria
- README is clear enough for a fresh executor/user.
- GUI launches.
- Loader can load exported scan windows.
- At least one dry-run strategy can be run through GUI.
- Handoff explains which production fixes should follow:
  - parallel scan calls
  - persisted/resumable scan and merge artifacts
  - bounded merge call counts
  - retry/backoff for transient provider failures
  - better progress UI

