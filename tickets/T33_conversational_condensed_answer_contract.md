# T33 - Conversational Condensed Answer Contract

## Goal
Align the conversational answer JSON contract with the condensed UI model: one high-level assistant summary plus one structured, clickable result object per material hit/range.

## Background
The current conversational response can contain overlapping prose in `answer`, `answer_summary`, and `answer_ranges`. The next UI should display only `answer_summary` plus clickable bullets derived from `answer_ranges`; the full `answer` field is redundant in normal display.

## Scope
- Update answer prompt defaults in `message_evidence_workstation/nim/prompts.py`.
- Keep parser compatibility with current fields.
- Clarify that `answer_summary` is the user-visible prose summary.
- Clarify that every materially distinct result must have exactly one `answer_ranges` object.
- Clarify that `answer_ranges[].summary` is the detailed clickable bullet label.
- Clarify that `answer_ranges[].date_description` is the brief-mode clickable bullet label.
- Clarify that `answer_ranges[].display_text` is hover/detail text.
- Clarify that `answer` is not the primary UI display and must not duplicate every result.
- Preserve the hard brief-mode safety valve: if output overflow is likely, use `answer_format = "brief"` and date-only display lines.

## Prompt Requirements
- `answer_summary` should be one or two sentences and should not enumerate every result.
- `answer_format` must be `detailed` or `brief`.
- `answer_ranges` must contain one object for every material result.
- In detailed mode, `summary` must be suitable as the clickable result text.
- In brief mode, UI will display only `date_description`; no labels or descriptions should be required for the visible line.
- `display_text` should contain the hover preview: excerpt or concise explanation.
- `hit_message_id`, `start_message_id`, and `end_message_id` must use supplied message IDs only.

## Acceptance Criteria
- Default answer prompts explicitly describe the condensed UI usage.
- Default answer prompts explicitly say `answer_summary` is the primary visible prose answer.
- Default answer prompts explicitly say every answer range is rendered as a clickable bullet.
- Default answer prompts retain completeness requirements.
- Default answer prompts retain brief-mode date-only safety valve.
- `candidate_evidence_blocks` is not requested by default answer prompts.

## Tests
- Prompt tests assert:
  - `answer_summary` is described as the visible summary.
  - `answer_ranges` is required for every material result.
  - `summary` is the detailed clickable label.
  - `date_description` is brief-mode date-only label.
  - `display_text` is hover/detail text.
  - old `candidate_evidence_blocks` prompt text is absent.

