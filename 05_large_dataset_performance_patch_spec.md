# Large Dataset Performance Patch Specification

**Status:** Approved for implementation  
**Project:** Message Evidence Workstation (`legal2`)  
**Scope:** Search responsiveness, transcript scalability, and removal of full-dataset UI loads  
**Primary goal:** Make the app remain responsive on large donor datasets by treating SQLite as the source of truth and query engine, not as a file that gets materialized into Python collections.

---

## Executive Summary

The current app has several partial scale hardening changes, but some critical paths still behave like the dataset is small:

- Search pagination exists in the UI, but FTS still materializes and sorts the full result set before slicing a page.
- The simple search box runs eagerly on text changes.
- FTS, expanded keyword, message embedding, and chunk embedding can all run from one query.
- Search runs synchronously on the UI thread.
- Simple Search and Conversational tabs load dataset-wide `message_id -> sort_index` maps on dataset bind.
- Transcript virtualization exists, but deep scrolling and message focusing still rely on expensive `OFFSET` and `ROW_NUMBER()` work.
- Some transcript helpers and signals still load or notify over entire threads.
- Keyword expansion search hydrates unbounded chip matches.

This patch makes search explicitly mode-based, moves search execution to background workers with cancellation, pushes pagination into SQL, introduces durable per-thread message ordinals for transcript range access, and removes full-dataset Python maps from UI tabs.

---

## Non-Goals

- No client/server refactor.
- No raw donor importer work.
- No changes to embedding index build semantics except search execution behavior.
- No semantic transcript segmentation in this patch. Transcript "sections" can be represented as optional metadata later, but the immediate performance fix is durable per-thread ordinals plus windowed SQL access.
- No artificial caps that hide search matches. Pages are allowed; silent truncation is not.

---

## User Decisions

1. Replace combined search behavior with four explicit modes:
   - FTS5
   - Expanded keyword
   - Message embedding
   - Chunk embedding
2. Real SQL-level pagination for FTS and keyword results.
3. Search runs on Enter or explicit Search button, not on every keystroke.
4. Remove full-dataset in-memory maps and replace with SQL access patterns.
5. Fix transcript deep-scroll and message-focus performance.
6. Remove transcript full-thread escape hatches and all-thread notification loops.
7. Bound and paginate expanded keyword search.
8. Run search in the background with a Cancel button.

---

## Patch Architecture

### 1. Search Mode Model

Add a search mode enum or literal type:

```python
SearchMode = Literal["fts5", "expanded_keyword", "message_embedding", "chunk_embedding"]
```

UI should expose exactly one selected mode at a time. Prefer a `QComboBox` or `QButtonGroup` with exclusive radio buttons.

Mode behavior:

| Mode | Runs | Result cardinality |
|------|------|--------------------|
| `fts5` | FTS5 exact/prefix/fuzzy logic | Complete, paged |
| `expanded_keyword` | LLM expansion, then FTS over chips | Complete, paged |
| `message_embedding` | Message vector top-K | Top-K by distance |
| `chunk_embedding` | Chunk vector top-K | Top-K by distance |

Remove additive toggle behavior from Simple Search:

- Remove `keyword_toggle`.
- Remove `message_embedding_toggle`.
- Remove `chunk_embedding_toggle`.
- Remove code paths that run FTS first and then optionally fuse keyword/vector hits.
- Embedding selectivity remains visible only for embedding modes.
- Keyword chip UI remains visible only for expanded keyword mode.

Acceptance criteria:

- A single user search invokes exactly one retrieval mode.
- Switching modes does not automatically execute a search unless the user presses Enter/Search.
- Vector results are clearly labeled as top-K, not complete result sets.

---

## 2. Search Trigger and Cancellation UX

### Current Problem

`QLineEdit.textChanged` starts a 300ms debounce and runs `_run_search`. On large datasets this is too eager and can queue expensive work for partial inputs.

### Required UI

Controls:

- Query input
- Search mode control
- Search button
- Cancel button
- Page controls for complete-result modes
- Status label with elapsed time and result count

Behavior:

- Pressing Enter runs search.
- Clicking Search runs search.
- Typing only edits text; it does not search.
- Cancel is enabled only while a background search is active.
- Page Next/Previous runs the same mode/query with a different cursor/page.
- If a newer search starts, stale results from older searches must be ignored.

Implementation:

- Keep a monotonically increasing `search_generation`.
- Background workers receive a cancellation token object or generation id.
- UI callbacks compare generation before rendering.
- Cancel marks the active token as cancelled and disables stale callback rendering.

Acceptance criteria:

- Typing a query does not touch the database.
- Enter/Search starts one background job.
- Cancel prevents results from rendering and returns UI to an idle/cancelled state.
- Repeated Enter presses do not interleave stale results.

---

## 3. Background Search Worker

### Requirement

All potentially expensive search work must leave the UI thread:

- FTS5 search
- Expanded keyword search and chip FTS
- Embedding query
- Result hydration
- Result grouping

### Design

Create `message_evidence_workstation/ui/search_worker.py`.

Recommended dataclasses:

```python
@dataclass(slots=True)
class SearchJobSpec:
    db_path: Path
    dataset_id: int
    mode: SearchMode
    query: str
    page_size: int
    offset: int = 0
    keyword_terms: list[str] = field(default_factory=list)
    embedding_model: str = ""
    embedding_selectivity: str = "balanced"
    generation: int = 0

@dataclass(slots=True)
class SearchJobResult:
    generation: int
    mode: SearchMode
    query: str
    groups: list[GroupedSearchResult]
    total_count: int | None
    page_size: int | None
    offset: int
    has_more: bool
    next_offset: int | None
    elapsed_ms: int
    cancelled: bool = False
```

Worker rules:

- Use a separate SQLite connection via `connect(db_path)`.
- Use `ProcessLogger` on the worker connection.
- Never touch Qt widgets from worker code.
- Deliver results to UI via `QTimer.singleShot` or existing background task helper.
- For embedding modes, either reuse the embedding worker or route through the same dedicated embedding thread, because PyTorch/sentence-transformers must stay off QThread and should not be loaded in multiple places.

Acceptance criteria:

- Searching for a common term does not freeze the UI.
- Cancel remains clickable while search is running.
- Worker connection closes on success, error, and cancellation.

---

## 4. Real SQL-Level FTS Pagination

### Current Problem

`fts.search_messages` does this:

1. Collect all exact/partial/fuzzy hits for all token variants.
2. Merge all hits in Python.
3. Fetch order keys for all merged hits.
4. Sort all hits.
5. Slice the requested page.

That is not real pagination.

### Required Change

Push page selection into SQL. `search_messages(..., limit, offset)` must return only the requested page worth of hydrated hit ids plus the total count.

### Recommended Approach

For FTS5 mode, define a query plan around candidate CTEs:

- Build exact/prefix/fuzzy MATCH clauses.
- For each clause, return rows with:
  - `message_id`
  - `source_thread_id`
  - `match_type`
  - `match_priority`
  - `rank`
  - `timestamp`
  - `sort_index`
- Use SQL windowing to keep the best match per message.
- Use deterministic ordering.
- Apply `LIMIT/OFFSET` only after deduplication.

Shape:

```sql
WITH candidates AS (
  SELECT ..., 0 AS match_priority, 'exact' AS match_type, bm25(message_fts) AS rank
  FROM message_fts ...
  WHERE ...
  UNION ALL
  SELECT ..., 1 AS match_priority, 'partial' AS match_type, bm25(message_fts) AS rank
  FROM message_fts ...
  WHERE ...
),
deduped AS (
  SELECT *,
         ROW_NUMBER() OVER (
           PARTITION BY message_id
           ORDER BY match_priority, rank, timestamp, sort_index, message_id
         ) AS rn
  FROM candidates
),
ordered AS (
  SELECT *
  FROM deduped
  WHERE rn = 1
)
SELECT ...
FROM ordered
ORDER BY match_priority, rank, timestamp, sort_index, message_id
LIMIT ? OFFSET ?;
```

Total count:

```sql
SELECT COUNT(*) FROM ordered;
```

If the CTE count is too expensive on scale fixtures, add a documented optional approximate count later. For this patch, exact count is preferred.

### Important Guardrails

- Do not call `search_exact` and `search_partial` in loops that materialize all hits for the paged search path.
- Keep legacy `search_exact`/`search_partial` only for tests or targeted code that explicitly needs full lists on small scopes.
- Ensure malformed queries return empty results, not uncaught FTS syntax errors.
- Preserve deterministic ordering across repeated identical queries.

Acceptance criteria:

- Searching a common token returns first page without materializing all matching message ids in Python.
- `total_count` reflects the complete deduped result count.
- Page 2 does not rehydrate or group page 1.
- Tests include a synthetic large fixture and instrumentation proving page size bounds Python hit count.

---

## 5. Expanded Keyword Mode

### Current Problem

Expanded keyword search currently acts as additive search:

- It can request LLM keyword expansion.
- It then runs exact FTS for every active chip.
- It hydrates every chip hit without pagination.
- It can also combine with FTS and vector search.

### Required Behavior

Expanded keyword is its own mode.

Flow:

1. User enters query.
2. User selects Expanded keyword mode.
3. User presses Search.
4. Worker obtains expansion terms if needed.
5. Worker executes paged keyword FTS across the active terms.
6. UI renders the current page and chip row.

Pagination:

- Results are complete and paged.
- Deduplicate messages across chips.
- Best chip/match should win deterministically.
- Total count is deduped message count, not sum of per-chip hits.

Chip behavior:

- Chips are cached for the current query.
- User may remove/add chips and press Search again.
- Manual chip additions do not trigger automatic search.

Acceptance criteria:

- Expanded keyword mode never runs base FTS or embedding search unless explicitly selected as the mode.
- Expanded keyword mode can page through all matching chip results.
- High-frequency chips do not freeze the UI.

---

## 6. Embedding Search Modes

### Required Behavior

Message embedding and chunk embedding are separate modes:

- `message_embedding` calls `search_message_embeddings`.
- `chunk_embedding` calls `search_chunk_embeddings`.
- Both run through the embedding worker/dedicated background path.
- Both return top-K by similarity, controlled by embedding selectivity.

UI:

- Hide FTS pagination controls for embedding modes unless a future vector pagination feature exists.
- Show text like: `Showing top 20 by similarity`.
- Cancel works for queued/running embedding search at the UI generation level. If the underlying embedding computation cannot be interrupted safely, stale results must still be ignored.

Acceptance criteria:

- Message embedding mode does not run chunk vectors.
- Chunk embedding mode does not run message vectors.
- Embedding search does not run FTS first.

---

## 7. Remove Dataset-Wide UI Maps

### Current Problem

Simple Search and Conversational bind a dataset by loading:

```sql
SELECT message_id, sort_index FROM message WHERE dataset_id = ?
```

into Python dicts.

### Required Change

Remove dataset-wide `_sort_index_by_message` from UI startup paths.

Options:

1. Prefer grouping from already hydrated current-page hit metadata.
2. If grouping needs order data for a small current result set, fetch order keys only for current result ids.
3. If grouping needs distance by thread position, use SQL-provided `thread_ordinal` from the new ordinal table/column.

Update `group_hits` signature to accept either:

```python
order_by_message: dict[str, MessageOrderKey]
```

or enrich `SearchHit` with:

```python
thread_ordinal: int | None = None
```

Preferred: enrich `SearchHit` during search hydration so grouping does not need global maps.

Acceptance criteria:

- `SimpleSearchTab.set_dataset` does not query all messages.
- `ConversationalTab.set_dataset` does not query all messages.
- Search grouping still groups nearby page hits correctly.

---

## 8. Transcript Ordinal Index

### Current Problem

Transcript virtualization still uses expensive access patterns:

- Range fetch uses `LIMIT ? OFFSET ?`.
- Message focus uses a `ROW_NUMBER()` CTE over the whole thread.
- Some helper paths load full threads.

On large threads, deep scroll and result navigation become slow.

### Required Data Model

Add a durable per-message ordinal within each source thread.

Preferred schema change:

```sql
ALTER TABLE message ADD COLUMN thread_ordinal INTEGER;

CREATE INDEX IF NOT EXISTS idx_message_thread_ordinal
    ON message(dataset_id, source_thread_id, thread_ordinal);

CREATE UNIQUE INDEX IF NOT EXISTS idx_message_thread_ordinal_unique
    ON message(dataset_id, source_thread_id, thread_ordinal)
    WHERE thread_ordinal IS NOT NULL;
```

Alternative if altering `message` is undesirable:

```sql
CREATE TABLE message_thread_order (
    dataset_id INTEGER NOT NULL,
    source_thread_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    thread_ordinal INTEGER NOT NULL,
    PRIMARY KEY (dataset_id, message_id)
);
```

Preferred for simplicity: add `message.thread_ordinal`.

### Ingestion Behavior

During normalized import:

- Assign `thread_ordinal` per source thread in chronological order.
- If source JSONL already arrives sorted by thread/time, still compute ordinals explicitly.
- For streaming import, keep `counts_by_thread[source_thread_id]` and assign incrementally only if input order is guaranteed per thread.
- Safer best practice: after message insert completes, run one SQL update using window functions:

```sql
WITH ordered AS (
  SELECT dataset_id,
         message_id,
         ROW_NUMBER() OVER (
           PARTITION BY dataset_id, source_thread_id
           ORDER BY timestamp, sort_index, message_id
         ) - 1 AS ordinal
  FROM message
  WHERE dataset_id = ?
)
UPDATE message
SET thread_ordinal = (
  SELECT ordinal
  FROM ordered
  WHERE ordered.dataset_id = message.dataset_id
    AND ordered.message_id = message.message_id
)
WHERE dataset_id = ?;
```

Migration behavior:

- Add migration to backfill `thread_ordinal` for existing datasets.
- Backfill must be idempotent.
- Rebuild or validate indexes after backfill.

### Repository Changes

Replace:

- `fetch_messages_for_slot_range` OFFSET implementation
- `message_index_in_thread` ROW_NUMBER implementation
- `fetch_message_ids_for_thread` full fetch where avoidable

With:

```sql
SELECT ...
FROM message
WHERE dataset_id = ?
  AND source_thread_id = ?
  AND thread_ordinal >= ?
  AND thread_ordinal < ?
ORDER BY thread_ordinal;
```

and:

```sql
SELECT thread_ordinal
FROM message
WHERE dataset_id = ?
  AND source_thread_id = ?
  AND message_id = ?;
```

Acceptance criteria:

- Deep transcript fetch is indexed by ordinal, not OFFSET.
- Focusing a message is one indexed lookup, not a window scan.
- Existing tests for slot ranges pass.
- Add scale test for focusing message 95,000 in a 100,000-message thread under target latency.

---

## 9. Transcript Virtualization Cleanup

### Required Fixes

1. Remove or rewrite `build_transcript_model_for_thread` so it does not call `list_messages_for_thread`.
2. Replace `_emit_all_separator_changes` with bounded visible-range notifications.
3. Replace `_emit_all_message_changes` so it only emits for the current loaded window or visible range.
4. Ensure `highlighted_message_ids()` for active overlays does not depend on only the currently loaded window unless the active overlay is a draft. For persisted blocks, source of truth is overlay metadata.
5. Avoid calling `_message_at` for labels that might fetch arbitrary windows during summary rendering.

### Visible Range Signal Strategy

In `EvidenceTranscriptModel`, add a helper:

```python
def loaded_message_range(self) -> tuple[int, int]:
    return self._window_start, self._window_start + len(self._messages)
```

Emit data changes only for:

- Loaded messages
- Visible separators plus small overscan
- Specific changed slots

Acceptance criteria:

- Creating/selecting an evidence block in a 50k-message thread does not emit one signal per slot.
- Transcript model never loads a full thread for UI display.
- Memory remains bounded while scrolling.

---

## 10. Transcript Sections Question

### Decision for This Patch

Do not physically break transcripts into separate sections during ingestion as the primary performance solution.

Reason:

- The database already has the right abstraction boundary.
- The problem is not that transcripts are too large conceptually; it is that several access paths ignore indexed, windowed SQL.
- Durable per-thread ordinals plus indexed range fetching gives true random access and smooth virtual scrolling.

Recommended future enhancement:

- Keep `transcript_session` or semantic chunks as optional navigation metadata.
- Use sections for analyst navigation, summarization, or future topic-aware scan planning.
- Do not make sections required for core transcript scrolling.

Acceptance criteria:

- Transcript scrolling works on a single 100k-message thread without requiring session breaks.
- Sessions/chunks remain metadata, not UI paging boundaries.

---

## 11. Conversational and Tool Runner Cleanup

### Current Problem

Some conversational tools still load full source threads and slice in memory.

Hot spots:

- `read_source_thread`
- `read_message_range`
- grouping that depends on dataset-wide sort maps

### Required Changes

- `read_source_thread` should fetch only `max_messages` from SQL using ordinal order.
- `read_message_range` should resolve start/end ordinals with indexed lookups, then fetch bounded ordinal range.
- Conversational result grouping should use ordinals from current hit metadata or bounded SQL lookups.

Acceptance criteria:

- No conversational tool loads a full thread just to return a bounded range.
- Range reads across large threads use indexed ordinal constraints.

---

## 12. Sidebar and Evidence Block Drop Cleanup

### Current Problem

Dropping a search result can load a full thread to build `ordered_ids`.

### Required Change

Evidence block creation should not require a full `ordered_message_ids` list.

Add repository helpers:

```python
message_ordinal(conn, dataset_id, source_thread_id, message_id) -> int | None
message_ids_for_ordinal_range(conn, dataset_id, source_thread_id, start, end) -> list[str]
```

Update evidence block creation from candidates to use ordinals directly:

- Resolve start/end message ids to ordinals.
- Store slot fields from ordinals.
- Fetch highlights only for bounded ranges.

Acceptance criteria:

- Drag/drop search result into sidebar does not call `list_messages_for_thread`.
- Creating a block from a result remains correct.

---

## 13. Tests

### Unit Tests

Add or update tests for:

- Search mode exclusivity.
- Search does not run on text change.
- Search starts on Enter/Search button.
- Cancel ignores stale worker results.
- FTS pagination returns same first N ids as full query on small fixture.
- FTS pagination does not materialize all hits in Python on synthetic large fixture.
- Expanded keyword pagination dedupes across chips.
- `thread_ordinal` backfill is correct.
- `fetch_messages_for_slot_range` uses ordinal semantics.
- `message_index_in_thread` uses direct ordinal lookup.
- Simple Search and Conversational `set_dataset` do not query all messages.
- Transcript visible updates are bounded.

### Scale Tests

Mark with `@pytest.mark.scale`:

- 100k-message single-thread transcript focus to index 95k under target latency.
- Common-token FTS search first page under target latency.
- Repeated page navigation does not grow memory linearly.
- Typing in search box performs zero DB search calls.

### Suggested Instrumentation

Use monkeypatch/counting wrappers around:

- `repositories.list_messages_for_thread`
- `load_dataset_messages`
- `fetch_message_ids_for_thread`
- `message_index_in_thread`
- FTS legacy full-list helpers

Tests should fail if these are called from large-dataset UI paths.

---

## 14. Migration and Compatibility

Migration steps:

1. Add `thread_ordinal` column if missing.
2. Backfill ordinals for existing messages.
3. Create ordinal indexes.
4. Preserve existing primary keys and sort behavior.

Compatibility:

- Existing datasets without ordinals are backfilled on schema init.
- Reloaded datasets compute/backfill ordinals after message import.
- Tests that assume `sort_index` equals position should be updated to use `thread_ordinal` where relevant.

Rollback:

- The migration is additive.
- Existing code can still use timestamp/sort ordering during the transition.

---

## 15. Performance Targets

Initial targets for local desktop:

| Operation | Target |
|-----------|--------|
| Search box typing | No DB work |
| Start FTS common-token search | UI remains responsive immediately |
| FTS first page on 100k messages | Under 2 seconds preferred |
| Cancel search | UI state updates under 200ms |
| Focus transcript message near end of 100k thread | Under 500ms after DB warmup |
| Scroll transcript deep into 100k thread | No full-thread load, bounded memory |
| Dataset tab bind | No O(total messages) Python dict build |

---

## 16. Implementation Order

1. Add `thread_ordinal` schema, migration, import backfill, and repository helpers.
2. Convert transcript data source to ordinal range fetch and direct ordinal lookup.
3. Remove transcript full-thread escape hatches and all-slot notification loops.
4. Remove dataset-wide sort maps from Simple Search and Conversational tabs.
5. Refactor Simple Search UI to explicit modes and run-on-Enter/Search.
6. Add background search worker and Cancel button.
7. Implement SQL-level FTS pagination.
8. Implement paged expanded keyword mode.
9. Split embedding modes and route through background embedding worker.
10. Update sidebar/conversational bounded range helpers.
11. Add unit and scale tests.

---

## Done Definition

The patch is complete when:

- No search is triggered by typing alone.
- Exactly one search mode runs per search action.
- FTS and expanded keyword searches page at SQL level.
- Search work runs off the UI thread.
- Cancel prevents stale result rendering.
- Simple Search and Conversational dataset binding do not load all messages.
- Transcript deep scroll and focus use indexed ordinals.
- Transcript UI paths do not load full threads.
- Evidence block workflows still pass.
- Unit tests pass, and new scale tests demonstrate bounded behavior.

