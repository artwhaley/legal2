# Search Date Range Build Plan

## Goal

Add an explicit date range feature to both Simple Search and Conversational Search.

The selected date range is an analysis and retrieval scope. It must be applied before token budgeting, transcript serialization, window planning, embedding ranking, and exhaustive-scan retrieval hints. The app should make the scope visible in logs and UI status so the user can understand exactly what was searched.

Context expansion for evidence blocks may continue to function normally outside the selected date range. The search/answer should identify in-range evidence, but when the user opens, saves, or reviews a result, surrounding context may include nearby messages outside the filter. This preserves useful context rather than quietly hiding information the user may want.

## Product Rules

1. Date filtering must be explicit and user-controlled.
2. Date filtering must happen before any token budget or answer-mode decision.
3. Date filtering must happen before FTS, keyword, embedding, and exhaustive-hint retrieval.
4. Date filtering must happen before conversational transcript/window construction.
5. The filtered scope must be logged with start date, end date, scoped message count, and scoped thread count.
6. Empty date ranges must fail visibly with a clear message, not silently fall back to full-dataset search.
7. Normal evidence-block context expansion may include messages outside the selected date range.
8. No hidden fallback to unfiltered search is allowed.

## Definitions

### Date Scope

Introduce a small shared value object, likely in `message_evidence_workstation/search/date_scope.py`.

Suggested type:

```python
@dataclass(frozen=True, slots=True)
class MessageDateScope:
    start_timestamp: str | None = None
    end_timestamp: str | None = None

    @property
    def is_active(self) -> bool:
        return bool(self.start_timestamp or self.end_timestamp)
```

The app stores message timestamps as ISO-like text in `message.timestamp`. The first implementation should use inclusive bounds:

```sql
timestamp >= :start_timestamp
timestamp <= :end_timestamp
```

Open-ended ranges should be supported:

- start only: messages at or after start
- end only: messages at or before end
- both: messages between start and end, inclusive
- neither: unfiltered current behavior

The UI should normalize date picker values into timestamp strings before sending them to workers. For day-level controls, use full-day inclusive bounds:

- start date: `YYYY-MM-DD 00:00:00`
- end date: `YYYY-MM-DD 23:59:59.999999`

If stored timestamps use `T` separators or timezone suffixes, use the existing import format consistently rather than mixing formats.

## Simple Search Plan

### UI

Update `message_evidence_workstation/ui/simple_search_tab.py`.

Add start and end date controls near the query/mode controls. The controls should have one obvious behavior:

- blank start means no lower bound
- blank end means no upper bound
- Search uses the current date range
- pagination preserves the current date range
- changing the date range resets pagination to the first page

Status text should include the scope when active, for example:

`Searching FTS5 from 2021-01-01 through 2021-03-31...`

### Worker Contract

Update `SearchJobSpec` in `message_evidence_workstation/ui/search_worker.py`:

```python
date_scope: MessageDateScope = field(default_factory=MessageDateScope)
```

Pass `date_scope` into:

- FTS search
- expanded keyword search
- embedding search worker job spec

Do not apply date filtering only in the UI after results return.

### FTS And Keyword Search

Update `message_evidence_workstation/search/fts.py`.

Add `date_scope` to:

- `search_messages`
- `search_keyword_terms`
- `_search_candidates_sql`
- any non-paginated collection path used by `limit=None`

The SQL candidate query already joins `message m`. Add predicates there:

```sql
AND (? IS NULL OR m.timestamp >= ?)
AND (? IS NULL OR m.timestamp <= ?)
```

The count query and page query must use the same scoped candidate CTE. Total count must mean total in-range matches, not total dataset matches.

### Embedding Search

Update:

- `message_evidence_workstation/ui/embedding_worker.py`
- `message_evidence_workstation/search/embedding_search.py`
- `message_evidence_workstation/embeddings/sqlite_vec_backend.py`

The important rule is: date scope must constrain candidates before final top-K selection.

Current vector search oversamples from sqlite-vec, filters by dataset afterward, then truncates. Date range should not be applied after the already-truncated result list. The safer implementation is:

1. Query sqlite-vec with a larger oversample.
2. Join or hydrate message timestamps.
3. Filter by dataset and date scope.
4. Continue until enough in-scope candidates are available or the oversample limit is exhausted.
5. Apply selectivity filtering to the in-scope ranked hits.

If sqlite-vec limitations prevent a clean SQL join inside the KNN query, implement an explicit oversample-and-filter loop with visible logging:

- requested top K
- oversample size
- in-scope candidate count
- returned hit count
- active date scope

Do not silently fall back to unfiltered embeddings.

For chunk embeddings, use the chunk start/end message metadata to determine scope. First implementation should include a chunk when its range intersects the selected date range, not only when the chunk start message is in range.

## Conversational Search Plan

### UI

Update `message_evidence_workstation/ui/conversational_tab.py`.

Add the same start/end date controls to the conversational search surface. The submitted query should capture the date scope at submit time and pass that exact immutable scope into the worker. A later UI change must not mutate a running answer.

Status text should be explicit:

- `Resolving answer mode for selected date range...`
- `Answering from scoped transcript...`
- `Answering with exhaustive scoped window scan...`

### Scoped Budget Stats

Update `message_evidence_workstation/search/dataset_budget.py`.

Add a scoped stats function, either by extending `compute_dataset_budget_stats`:

```python
def compute_dataset_budget_stats(
    conn: sqlite3.Connection,
    dataset_id: int,
    *,
    date_scope: MessageDateScope | None = None,
) -> DatasetBudgetStats:
```

or by adding `compute_scoped_dataset_budget_stats`.

The aggregate SQL must apply the date predicates before counting:

- `message_count`
- `thread_count`
- `total_body_chars`
- `total_body_normalized_chars`
- `largest_thread_message_count`

`resolve_answer_budget` can stay mostly unchanged because it receives stats. The caller must pass scoped stats.

If the scoped `message_count` is zero, the conversational search should stop visibly before calling the model.

### Scoped Transcript Loading

Update `message_evidence_workstation/search/transcript.py`.

Add date scope support to:

- `load_dataset_messages`
- possibly `load_thread_messages` if future UI paths need thread-scoped filtered loads
- `build_dataset_transcript` in `conversational_answer.py`

`build_dataset_transcript(conn, dataset_id, date_scope=...)` should serialize only scoped messages.

Whole transcript mode should send only scoped transcript content to the model, but logs and coverage summary should say the transcript was scoped.

### Whole Transcript Answer

Update `run_whole_transcript_answer` in `message_evidence_workstation/search/conversational_answer.py`.

Add `date_scope`.

If no transcript is passed, build a scoped transcript. The valid message IDs for parsing must be scoped IDs only. This prevents model output from citing messages outside the analysis scope.

Coverage summary should include scope metadata. Suggested extension:

```python
CoverageSummary(
    mode="whole_transcript",
    messages_considered=len(scoped_transcript.message_ids),
    source_thread_ids=scoped_thread_ids,
    date_scope={...},
)
```

If changing the dataclass is too broad, include scope in `token_budget` or a similar existing dict, but make it visible in the result/logs.

### Answer Mode Selection

Update `_submit_query` in `conversational_tab.py`.

Current flow:

1. compute full dataset stats
2. resolve budget
3. choose whole transcript or exhaustive scan

New flow:

1. capture date scope
2. compute scoped dataset stats
3. log scoped stats
4. resolve budget from scoped stats
5. choose whole transcript or exhaustive scan

This directly satisfies the requirement that trimming happen before token calculations.

### Exhaustive Window Planning

Update `message_evidence_workstation/search/window_planner.py`.

Add `date_scope` to:

- `build_token_bounded_windows_for_dataset`
- `iter_thread_messages_for_window_planning`
- `_compute_chars_per_token`

The thread list query should include only threads with at least one in-scope message.

The message iterator should yield only in-scope messages.

The chars/token calculation must serialize only in-scope messages. This matters because the current planner derives a real chars/token ratio from the transcript; using the full dataset would size scoped windows using out-of-scope data.

If the scoped planner produces no windows, raise a visible error like:

`No messages found in the selected date range.`

### Exhaustive Retrieval Hints

Update `message_evidence_workstation/search/exhaustive_hints.py`.

Add `date_scope` to:

- `collect_exhaustive_window_hints`
- `_fts_hint_items`
- `_message_embedding_hint_items`
- `_chunk_embedding_hint_items`
- `_thread_message_ids`

Retrieval hints must be generated from the same scoped universe as the transcript windows.

FTS hint searches should pass `date_scope` to `search_keyword_terms`.

Embedding hint searches should pass `date_scope` to embedding search.

`_thread_message_ids` should load only scoped message IDs because hint block/window assignment should reason about the same message order visible to the exhaustive scan.

### Exhaustive Scan Answer

Update `run_exhaustive_window_scan_answer` in `conversational_answer.py`.

Add `date_scope`.

Use scoped budget stats:

```python
budget = resolve_answer_budget(
    compute_dataset_budget_stats(conn, dataset_id, date_scope=date_scope),
    ...
)
```

Pass `date_scope` into:

- `build_token_bounded_windows_for_dataset`
- `collect_exhaustive_window_hints`

The window parser already validates against `window.message_ids`; once windows are scoped, scan outputs are naturally constrained.

Final merge validation should use `valid_ids` collected from scoped windows only. Context expansion after results are created can still use normal thread context.

## Evidence Block Context Behavior

Do not date-limit the following context expansion paths:

- conversational result navigation
- evidence block creation
- `_context_start_for_range`
- `_context_end_for_range`
- transcript widget display around a hit

The date range limits what counts as retrieved/analyzed evidence. It does not limit what nearby context the user may inspect or save around that evidence.

This should be documented in a small UI hint or status detail if needed:

`Results are date-scoped; opened evidence may show neighboring context outside the range.`

## Logging And Observability

Add logging at these boundaries:

### Simple Search

- search start
- active date scope
- scoped total count
- page hit count
- embedding oversample and in-scope candidate count

### Conversational Search

- date scope captured
- scoped budget stats computed
- answer budget resolved from scoped stats
- selected mode
- scoped transcript built
- scoped windows planned
- scoped hints collected
- zero-message scope failure

Suggested details:

```json
{
  "date_scope_active": true,
  "start_timestamp": "2021-01-01 00:00:00",
  "end_timestamp": "2021-03-31 23:59:59.999999",
  "scoped_message_count": 1234,
  "scoped_thread_count": 2
}
```

## Tests

### Unit Tests

Add tests for `MessageDateScope` SQL behavior:

- no scope returns all messages
- start only
- end only
- start and end inclusive
- empty range returns zero messages

### FTS Tests

Add tests in `tests/test_fts.py`:

- `search_messages` excludes out-of-range hits
- `search_keyword_terms` excludes out-of-range hits
- total count reflects scoped hits
- pagination preserves scope

### Embedding Tests

Add tests around embedding search helpers:

- message embeddings return only in-scope messages
- chunk embeddings include chunks intersecting the date range
- out-of-range high-similarity hits do not suppress in-range hits from final top-K

### Dataset Budget Tests

Add tests in `tests/test_dataset_budget.py`:

- scoped message count
- scoped thread count
- scoped body char totals
- scoped largest thread count

### Transcript Tests

Add tests in `tests/test_conversational_answer.py` or `tests/test_transcript.py`:

- `build_dataset_transcript(..., date_scope=...)` serializes only scoped messages
- whole transcript prompt contains only scoped message IDs
- parser rejects out-of-scope citations

### Window Planner Tests

Add tests in `tests/test_window_planner.py`:

- planned windows contain only scoped messages
- thread list excludes threads with no scoped messages
- chars/token calculation uses scoped transcript

### Exhaustive Hint Tests

Add tests for:

- FTS hints are date-scoped
- embedding hints are date-scoped
- hint block assignment uses scoped thread order

### UI/Worker Tests

Add or update tests for:

- simple search job spec carries date scope
- conversational submit computes scoped stats before mode selection
- running answer receives immutable date scope captured at submit time

## Implementation Order

1. Add `MessageDateScope` and SQL predicate helpers.
2. Add scoped dataset stats and transcript loading.
3. Wire conversational answer mode selection to scoped stats.
4. Wire whole transcript answer to scoped transcript and scoped validation.
5. Wire window planner to scoped iteration and scoped chars/token calculation.
6. Wire exhaustive hints to scoped FTS and scoped embeddings.
7. Wire simple FTS and expanded keyword search.
8. Wire simple embedding search with pre-top-K date filtering.
9. Add UI controls to Simple Search.
10. Add UI controls to Conversational Search.
11. Add tests in the same order.
12. Run targeted tests, then full suite.

## Acceptance Criteria

1. Simple FTS search with a date range returns only in-range hits and accurate scoped counts.
2. Simple expanded keyword search with a date range returns only in-range hits and accurate scoped counts.
3. Simple embedding search with a date range ranks over in-range candidates, not over full-dataset candidates later filtered down.
4. Conversational answer mode is selected from scoped token budget stats.
5. Whole transcript mode sends only scoped messages to the model.
6. Exhaustive scan windows contain only scoped messages.
7. Exhaustive retrieval hints come only from scoped messages/chunks.
8. Model-returned citations outside the scoped analysis set are rejected.
9. Evidence-block context expansion still works normally and may include neighboring messages outside the selected date range.
10. A date range with no messages stops visibly before any model call.
11. Logs show the active date scope and scoped message counts.

## Risks And Notes

### Timestamp Format

The date filtering depends on lexicographic timestamp ordering. This is acceptable if imported timestamps are consistently normalized. Before implementation, verify the stored format in real datasets. If formats are mixed, add a normalization step at import or a stored sortable timestamp column before relying on date filters.

### Chunk Date Semantics

Chunk embeddings represent message ranges. The first implementation should include a chunk if any part intersects the selected date range. This favors recall and avoids dropping evidence that straddles a date boundary.

### Vector Oversampling

sqlite-vec currently limits KNN results before Python-side dataset filtering. Date filtering adds another candidate constraint. The implementation must avoid a too-small oversample that causes in-range candidates to be missed. Log oversample behavior so stress testing can reveal whether deeper pagination or a different vector-table design is needed.

### Context Outside Scope

Allowing context expansion outside the date range is intentional. The selected range constrains retrieval and analysis, not the user's ability to inspect surrounding conversation.

