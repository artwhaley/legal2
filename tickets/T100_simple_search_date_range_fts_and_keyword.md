# T100 - Simple Search Date Range For FTS And Keyword

## Goal

Add a visible date range feature to simple search and apply it correctly to FTS5 and expanded keyword search, including counts and pagination.

## Dependencies

T99.

## Implementation Notes

Update simple search so date range is part of the search job contract, not a UI-only decoration.

Wire the selected scope through:

- `SimpleSearchTab`
- `SearchJobSpec`
- `run_search_job`
- `fts.search_messages`
- `fts.search_keyword_terms`

Decisions:

- Changing the date range resets pagination to the first page.
- Scoped total counts are the only counts shown to the user.
- Empty scoped searches return zero results visibly; they do not fall back to full-dataset behavior.

The FTS candidate SQL already joins `message`. Add scope predicates there so both count and page queries operate over the same in-range candidate set.

## Files / Areas Likely Touched

- `message_evidence_workstation/ui/simple_search_tab.py`
- `message_evidence_workstation/ui/search_worker.py`
- `message_evidence_workstation/search/fts.py`
- `tests/test_fts.py`
- `tests/test_search_worker.py`

## Acceptance Criteria

- Simple Search has explicit start/end date controls.
- FTS5 search returns only in-range hits.
- Expanded keyword search returns only in-range hits.
- Pagination preserves the active date scope.
- Displayed total counts and page counts are scoped counts.
- Search worker contracts carry the date scope explicitly.
- No UI-side post-filtering is used to simulate scoped results.

## Tests / Verification

- Add tests for:
  - scoped FTS search
  - scoped expanded keyword search
  - scoped total count
  - pagination with active scope
  - worker spec propagation
- Run:
  - `python -m pytest tests/test_fts.py tests/test_search_worker.py -q`

## Non-Goals

- No embedding date scope yet.
- No conversational search changes yet.
