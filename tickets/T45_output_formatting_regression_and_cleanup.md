# T45 - Output Formatting Regression And Cleanup

## Goal
Finish the output formatting refactor by removing obsolete code paths, updating tests/docs, and running the regression suite.

## Cleanup Targets
- Remove obsolete range suggestion UI usage from Output Formatting.
- Remove obsolete `search/range_suggestion.py` if no remaining production code uses it.
- Remove obsolete output HTML preview code only if no remaining code/tests use it.
- Remove `WorkstationConversation` usage from Output Formatting if it is no longer needed there.
- Keep old tables in schema for compatibility unless a separate migration decision is made; do not drop data in existing EVW files.
- Update smoke checklist/docs to reflect:
  - no Source Thread Viewer tab
  - Output Formatting uses printable artifacts
  - Transcript Widget is the source-thread viewer replacement

## Regression Scope
- Full test suite.
- Manual smoke:
  - Start app.
  - Select a source thread from left sidebar; Transcript Widget loads it.
  - Create/select an evidence block.
  - Open Output Formatting.
  - Drag evidence block into printable artifacts tree.
  - Edit title, exhibit number, case number.
  - Append another evidence block to the same artifact.
  - Move blocks up/down.
  - Confirm preview updates and provenance ledger appears at end.

## Acceptance Criteria
- No production imports of deleted/obsolete `SourceThreadView`.
- No Output Formatting references to workstation conversations, range suggestions, highlight overrides, or embedded source-thread preview.
- Full test suite passes.
- New printable artifact workflow works on a fresh workspace and an existing EVW workspace.
- No destructive migration drops existing user data.

## Tests
- Full `python -m pytest -q`.
- UI smoke tests for tab layout and printable artifact workflow.
- Repository tests for schema/domain behavior.
- Preview/provenance model tests.
