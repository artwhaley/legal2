# T18 — Conversational Result Synthesis

## Goal

Complete the Conversational Interface by synthesizing tool results into an answer, strategy summary, and candidate workstation conversation result panel.

## Dependencies

T17.

## Implementation Notes

Send retrieved windows/results to the Conversational Search Result Synthesis prompt through NIM. The UI should show plain-language answer, search strategy summary, and candidate conversations that can be dragged or added to categories. The LLM can propose candidates, but Python remains responsible for creating records only after explicit user action.

## Files / Areas Likely Touched

- message_evidence_workstation/ui/conversational_tab.py
- message_evidence_workstation/nim/prompts.py
- message_evidence_workstation/search/fusion.py
- message_evidence_workstation/db/repositories.py
- tests/test_conversational_synthesis.py

## Acceptance Criteria

- User query returns answer + strategy summary + candidate result list.
- Synthesis NIM call creates ModelRun.
- Candidate rows include source thread, hit messages, snippets, retrieval methods, confidence/explanation if available.
- Candidate can be added to category through explicit UI action.
- LLM response does not directly mutate DB.
- All tool and synthesis steps are logged.

## Tests / Verification

- Mock synthesis response and verify UI model.
- Manual add candidate to category.
- Test DB unchanged if user does not accept/add.

## Non-Goals

- No final legal conclusions.
- No hidden full-corpus prompt stuffing.
