# T37 - Conversational Prompt Migration And Regression

## Goal
Finalize the condensed conversational output refactor with live prompt migration and full regression coverage.

## Scope
- Update live testing EVW prompt rows after code prompt changes.
- Target run types:
  - `whole_transcript_answer`
  - `coverage_session_answer`
  - `exhaustive_window_scan`
  - `exhaustive_window_merge`
- Expected new active prompt version: next version after current live version.
- Verify live prompt rows contain condensed UI instructions.
- Run full test suite.
- Capture one fresh successful whole-transcript answer run if useful for manual verification.

## Acceptance Criteria
- Python default prompts and live EVW prompts match the new condensed answer contract.
- Live prompts contain:
  - `answer_summary`
  - `answer_format`
  - `answer_ranges`
  - clickable bullet/result language
  - brief-mode date-only safety valve
- Live prompts do not ask for `candidate_evidence_blocks`.
- Full test suite passes.
- Terminal startup remains clean of the previous SettingsTab initialization traceback.

## Tests
- Full test suite.
- Smoke test for app construction.
- Optional manual query:
  - `Show me all the times we talked about medical care`
- Inspect latest `model_run` raw JSON and confirm:
  - valid JSON
  - `answer_summary`
  - one `answer_ranges` object per displayed result row
  - result row text is not duplicated in three UI panes

