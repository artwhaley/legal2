# T95 - Virtual Transcript Demo Controls

## Goal
Add demo and stress controls to the virtual transcript tab so the widget can be tested before search integration.

## Background
The virtual widget must prove its behavior in isolation before replacing existing workflows.

**Spec reference:** `08_virtual_transcript_widget_spec.md` section `Demo Tab`

## Depends On
- T94

## Scope
- Add buttons:
  - jump to message 50
  - jump to message 500
  - jump to message 14,000
  - jump random
  - create evidence block at viewport center
  - create evidence block at random message
  - reveal active evidence block
  - reload current thread
- Add status display:
  - active thread id
  - message count
  - visible ordinal range
  - fetched cache count
  - measured height count
  - active evidence block id
- Ensure controls disable gracefully when no dataset/thread is loaded

## Guardrails
- Keep controls inside the virtual tab only
- Do not wire to search/conversational pages
- Do not hide performance problems behind silent loading

## Non-Goals
- Production toolbar polish
- Search integration

## Acceptance Criteria
- Each demo button performs the named action
- Deep random create/reveal does not hang on a 15k-message thread
- Status values update after scroll, jump, create, reload, and resize

## Tests
- Add UI tests or direct widget tests for demo actions where practical
- Add scale smoke tests for random/deep create and reveal

