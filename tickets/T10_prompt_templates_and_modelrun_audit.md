# T10 — Prompt Templates and ModelRun Audit

## Goal

Implement editable prompt templates and persistent ModelRun records for every NIM call.

## Dependencies

T09, T01.

## Implementation Notes

Create default prompt templates for Keyword Expansion, Conversational Search Planner, Conversational Search Result Synthesis, and Evidence/Conversation Range Suggestion. Prompt edits should create a new version or mark an updated version clearly. Wrap NIM calls with a recorder that stores prompt template ID/version, model, input summary, raw request JSON, raw response JSON, latency, and errors.

## Files / Areas Likely Touched

- message_evidence_workstation/nim/prompts.py
- message_evidence_workstation/nim/model_runs.py
- message_evidence_workstation/ui/settings_tab.py
- message_evidence_workstation/db/repositories.py
- tests/test_prompts_model_runs.py

## Acceptance Criteria

- Default prompt templates are inserted on first DB init or first settings open.
- Settings tab lets user view/edit prompt bodies.
- Active prompt version can be retrieved by run type.
- Successful mocked NIM call creates ModelRun row.
- Failed mocked NIM call creates ModelRun row with error fields.
- Raw request/response JSON is stored for audit during MVP.

## Tests / Verification

- Unit test default prompt seeding.
- Unit test prompt version update.
- Unit test ModelRun success and failure records.

## Non-Goals

- No keyword expansion UI behavior yet.
- No prompt marketplace/import/export.
