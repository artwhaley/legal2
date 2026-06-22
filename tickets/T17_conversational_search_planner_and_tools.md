# T17 — Conversational Search Planner and Tools

## Goal

Build the first half of the Conversational Interface: a chat query creates a NIM search plan, and Python executes specific retrieval tools.

## Dependencies

T11, T16, T10.

## Implementation Notes

Create a chat-style UI with user input and response area. The planner prompt should return a constrained plan for this workflow only. Do not build a generic JSON behavior executor. Implement explicit tool functions for FTS5, keyword expansion, message embedding search, chunk embedding search, source-thread read, message-range read, and grouping. Log plan, tool calls, arguments, durations, and result counts.

## Files / Areas Likely Touched

- message_evidence_workstation/ui/conversational_tab.py
- message_evidence_workstation/nim/prompts.py
- message_evidence_workstation/search/tool_runner.py
- message_evidence_workstation/search/result_models.py
- tests/test_conversational_tools.py

## Acceptance Criteria

- Conversational tab accepts a natural-language query.
- Planner NIM call creates ModelRun.
- Planner output is validated before execution.
- Explicit Python tools execute and log results.
- Tool failures are visible and do not become hallucinated answers.
- No database mutation occurs from planner output.

## Tests / Verification

- Mock planner output and verify tools called.
- Malformed planner output test produces visible error.
- Manual query with mocked/fake NIM if needed.

## Non-Goals

- No final synthesis answer yet beyond raw plan/results.
- No automatic category mutation.
