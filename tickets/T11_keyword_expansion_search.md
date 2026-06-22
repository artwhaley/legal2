# T11 — Keyword Expansion Search

## Goal

Implement the yellow Keyword Expansion toggle, chips, and expanded FTS5 result lane in Simple Search.

## Dependencies

T07, T09, T10.

## Implementation Notes

When enabled, send the current search query to the active Keyword Expansion prompt through NIM. Parse suggested terms into chips. Let chips be removed with `x` and added manually with `+`. Active chips run FTS5 searches. Expanded hits appear as yellow results below direct green FTS hits and participate in result fusion/de-duplication.

## Files / Areas Likely Touched

- message_evidence_workstation/ui/simple_search_tab.py
- message_evidence_workstation/search/fusion.py
- message_evidence_workstation/nim/prompts.py
- tests/test_keyword_expansion.py

## Acceptance Criteria

- Yellow toggle calls NIM keyword expansion.
- Returned terms appear as chips.
- Chips can be removed and custom chips added.
- Chip searches run through FTS5.
- Expanded hits appear as yellow results below direct FTS.
- NIM failures are visible in UI and log.
- ModelRun record is created for expansion call.

## Tests / Verification

- Mock NIM expansion returns terms; verify chips.
- Mock malformed NIM response; verify loud error.
- Manual UI test add/remove chips.
- Fusion test same hit found by direct and chip search appears once with multiple badges.

## Non-Goals

- No embedding search.
- No conversational interface.
