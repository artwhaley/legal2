# T07 — Simple Search UI and Result Grouping

## Goal

Build the Simple Search tab with debounced FTS5 results, green result styling, and initial candidate grouping.

## Dependencies

T03, T04, T06.

## Implementation Notes

Typing into the search box should run FTS5 after a debounce. Show exact matches as bright green and partial matches as light green. Build a `SearchResult`/`GroupedResult` model so later keyword and vector hits can join the same UI. Implement the initial grouping rule: same source thread and within 5 messages or 30 minutes. Log grouping decisions.

## Files / Areas Likely Touched

- message_evidence_workstation/ui/simple_search_tab.py
- message_evidence_workstation/search/result_models.py
- message_evidence_workstation/search/grouping.py
- message_evidence_workstation/search/fusion.py
- tests/test_grouping.py

## Acceptance Criteria

- Typing search text populates results.
- Exact and partial matches are visually distinct.
- Results show source thread, sender, timestamp, snippet, and method badge.
- Nearby hits group into candidate workstation conversations.
- A message appears once even if exact and partial paths both find it.
- Grouping decisions are logged with reason/details.

## Tests / Verification

- Manual search in sample data.
- Unit test grouping by message distance.
- Unit test grouping by time distance.
- Unit test de-duplication of same message.

## Non-Goals

- No drag-to-category yet.
- No keyword expansion.
- No embeddings.
