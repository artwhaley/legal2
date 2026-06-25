# Pre-Scale Hardening Specification

**Status:** Draft for review — no implementation in this document  
**Audience:** Reviewing agent, then implementation agent  
**Project:** Message Evidence Workstation (`legal2`)

---

## Executive summary (for reviewing agent)

A codebase audit before large-donor-dataset testing and a future client/server refactor found that the MVP passes smoke tests on a ~100-message fixture but contains **structural scaling assumptions** that will fail on real data. The problems are not random hardcoded `max=50` shortcuts; they are **unbounded loads**, **miswired configuration**, **legacy domain duplication**, and **UI patterns that materialize entire threads in memory**.

This specification converts audit findings plus product-owner decisions into an ordered hardening plan. It is the single source of truth for the next implementation phase.

### Why these changes are justified

| Finding | Risk on large donor data | Decision in this spec |
|--------|---------------------------|------------------------|
| `load_dataset_messages` loads every message into RAM for budgeting | OOM / multi-minute stalls before first LLM call | Budget from SQL aggregates only |
| `resolve_model_context` falls back to **8192** when settings value is 0 | Tiny windows → thousands of LLM calls | **Always** use `nim.context_window_tokens` from Settings; no silent default |
| Window planner uses `usable_input_tokens` but exhaustive scan also rebuilds sessions and loads full threads repeatedly | Redundant I/O; scan cost opaque | Pack windows to fill budget; startup preload; remove redundant session rebuild from scan path |
| FTS queries have no pagination | Tens of thousands of hits loaded at once | Paginate; never silently drop hits |
| Transcript UI loads full thread + reflows all rows | UI freeze on large threads | Virtualized infinite-scroll transcript |
| JSONL import buffers entire files | Memory spike on import | Stream JSONL with batched writes |
| `load_dataset_messages` sets `source_metadata_json={}` | Provenance broken on analysis paths | Analysis payloads stay light; IDs must resolve to full DB rows |
| Four dead `AnswerSettings` fields in UI/settings | Operators tune knobs that do nothing | Remove them |
| `workstation_conversation` schema/repos/HTML export | Duplicate domain; blocks clean API | Delete legacy path; existing data is disposable test data |
| Printable preview is QLabel + line-count pagination | Product deliverable is wrong | Real paginated print preview widget (PDF-quality layout) |
| Process log commits per line | SQLite churn during embedding | Batch/summary logging |
| Embedding resume loads all embedded IDs into a set | Slow but necessary for correctness | Optimize without gutting resume |
| N+1 per-hit message fetches in search | Latency, not completeness loss | Batch fetch + paginated presentation (not caps) |

### Explicitly deferred (not in this spec)

- Client/server service-layer extraction
- Raw donor importers (Facebook/WhatsApp/etc.)
- Environment-variable / deployment config unification
- Session-coverage conversational path redesign (kept until large-dataset crawl strategy is decided; do not invest here now)

### Recommended implementation order

1. **Context window wiring** (item 8) — fixes scan cost immediately  
2. **Answer budget from SQL** (item 1) + **window packing correction** (item 2)  
3. **Startup load tab + dataset load pipeline** (item 9)  
4. **Streaming JSONL import** (item 5)  
5. **Search pagination** (item 3) + **batch message hydration** (item 10)  
6. **Virtualized transcript** (item 4)  
7. **Print preview widget** (item 14)  
8. **Legacy removal** (items 7, 11, 16, 19)  
9. **Process log batching** (item 18)  
10. **Embedding resume optimization** (item 15)  
11. **Analysis payload / provenance reference model** (item 6) — verify and document

---

## 1. Answer mode budgeting from SQL (not full dataset load)

### Problem

`build_dataset_transcript` → `load_dataset_messages` executes an unbounded `SELECT` and builds full `Message` objects for the entire dataset. `resolve_answer_budget` then token-estimates the serialized text to choose whole-transcript vs exhaustive scan.

### Requirement

Replace full-dataset materialization for **mode selection and budget preview** with SQL-backed statistics that are cheap at any scale.

### SQL statistics to compute (per dataset)

All via aggregate queries — no message bodies in Python unless a specific downstream step needs them:

| Stat | SQL approach |
|------|----------------|
| `message_count` | `COUNT(*)` |
| `thread_count` | `COUNT(DISTINCT source_thread_id)` |
| `total_body_chars` | `SUM(LENGTH(body))` |
| `total_body_normalized_chars` | `SUM(LENGTH(body_normalized))` |
| Per-thread message count | `GROUP BY source_thread_id` (for largest-thread warning only) |
| Optional: sampled token estimate | `SUM(LENGTH(body))` × chars-per-token heuristic, or tiktoken on a stratified sample of N rows |

### Behavior

- `resolve_answer_budget` accepts a `DatasetBudgetStats` dataclass (or similar) instead of `SerializedTranscript` for the **decision** step.
- Whole-transcript vs exhaustive-scan decision compares `estimated_transcript_tokens` (from stats) against `usable_input_tokens` (see item 8).
- **Do not** load message bodies for budgeting.
- Log the stats used in `answer_budget_resolved` for diagnosability.

### Acceptance criteria

- No `load_dataset_messages` call on the budgeting path.
- Budget readout on Settings tab uses the same SQL stats path (or a representative empty/small query), not a full dataset load.
- Tests: fixture dataset produces same mode decision as before; mock stats with 10M estimated tokens always selects exhaustive scan.

---

## 2. Exhaustive window scan — correct packing, no 8192 default

### Problem (current broken behavior)

1. `resolve_model_context` returns `DEFAULT_CONTEXT_WINDOW_TOKENS = 8192` when `nim.context_window_tokens` is 0 — **this must never happen** (see item 8).
2. When the effective budget is small, `_pack_messages_into_windows` creates many tiny windows (operator report: “every 4 messages”) because `target_tokens` is too low.
3. Exhaustive scan calls `build_dataset_transcript` for budgeting, `rebuild_dataset_sessions` before the loop, and `load_thread_messages` per thread during planning — redundant with corrected startup (item 9).

### Intended behavior (product)

**Goal:** Minimize the number of LLM API calls subject to context limits.

For each source thread (chronological message order):

1. Compute **per-call input budget** (tokens):
   ```
   per_call_input_budget = floor(
       (context_window_tokens - prompt_overhead_tokens - reserved_output_tokens) * safety_ratio
   )
   ```
   Where:
   - `context_window_tokens` = **only** `settings.nim.context_window_tokens` (item 8)
   - `prompt_overhead_tokens` = `settings.nim.prompt_overhead_tokens`
   - `reserved_output_tokens` = `settings.nim.max_output_tokens` (output reservation is non-negotiable)
   - `safety_ratio` = `settings.nim.context_safety_ratio`

2. **Pack greedily:** grow each window message-by-message until adding the next message would exceed `per_call_input_budget` (token estimate on serialized window text including header). Emit window. Advance start index to `(last_index + 1 - overlap_messages)` (same overlap semantics as today in `_pack_messages_into_windows`).

3. **Overlap:** Keep `window_overlap_messages` as a **real setting** — but move it to `NimSettings` or a single `AnswerSettings` field that is actually wired (not one of the four deleted fields). Default: `2`. Overlap is required so boundary messages are not lost between windows.

4. **Optional topic-aware break (future-friendly, not required now):** If a natural break (session boundary, large time gap) falls within the last X% of the window budget, end the window early at that boundary. **Not required for this phase** — overlap is sufficient. If implemented later, it must never reduce a window below a minimum message count without logging.

5. **One LLM call per packed window** — unchanged orchestration, but window count must drop dramatically once context window is wired correctly.

6. **Remove `target_tokens = max(500, target_tokens)` floor** or replace with a sanity floor derived from settings (e.g. at least 256) — the 500 floor must not dominate when settings are wrong.

### Session rebuild in exhaustive scan

- **Remove** `rebuild_dataset_sessions` from the exhaustive scan path.
- Window planning uses **chronological per-thread packing only** (`build_token_bounded_windows_for_dataset`) — already the intended design per `window_planner.py` docstring.
- Sessions table may still be populated at **startup** (item 9) for future session-coverage experiments; exhaustive scan must not rebuild them.

### Pre-flight transparency

Before starting scan, log and surface in UI:

- `context_window_tokens` (from settings)
- `per_call_input_budget`
- `planned_window_count` (total across all threads)
- `overlap_messages`
- Estimated total LLM calls (= window count)

Operator can cancel before spend.

### Acceptance criteria

- With `context_window_tokens` set to 128000 on Settings, a 100-message fixture produces **far fewer** windows than with 8192.
- No code path uses `DEFAULT_CONTEXT_WINDOW_TOKENS` for live budgeting.
- Unit test: synthetic thread of 1000 messages packs into `ceil(total_tokens / budget)` windows ± overlap overhead, not O(message_count).

---

## 3. Simple search — paginate, never silently cap

### Problem

FTS returns unbounded hit lists. Multi-token search unions unbounded per-token results. UI then hydrates hits one query at a time.

### Principle

**Completeness over convenience.** A bad query (“the”) may return 10,000 hits — that is the correct answer. The UI must make it manageable, not hide results.

### Requirements

#### 3.1 FTS layer

- Add **cursor-based pagination** to FTS queries:
  - Parameters: `limit`, `offset` for the first pass, with stable ordering by rank plus `(timestamp, sort_index, message_id)` tie-breakers
  - Prefer keyset cursor fields (`after_rank`, `after_timestamp`, `after_sort_index`, `after_message_id`) if offset pagination is too slow or unstable on scale fixtures
  - Default page size: configurable in settings (suggest default **200** — this is a *page*, not a cap on total results)
  - `search_messages` returns `{ hits, total_count, has_more, next_offset }`
- `total_count` from `SELECT COUNT(*)` with same MATCH clause (acceptable cost for FTS5 at scale; if slow, document and add approximate count later)

#### 3.2 Result hydration

- Replace per-hit `SELECT` with **batch fetch** by message ID list for the current page only.
- See item 10.

#### 3.3 UI

- Simple Search results list shows current page with **Next / Previous** (and optional “load more” infinite scroll in results pane only — not the transcript).
- Display: “Showing 1–200 of 9,847 matches” — always show true total when available.
- No silent truncation in logs or UI.

#### 3.4 Embedding search

- Vector search already has `top_k` by selectivity — that is a **ranking budget**, not arbitrary truncation. Document that embedding results are “top K by distance” not “all matches.”
- For hybrid display, FTS pagination and embedding top-K remain separate lanes with clear labeling.

### Acceptance criteria

- Search for a high-frequency token returns paginated UI with correct total count.
- All pages reachable without data loss.
- Page ordering is deterministic across repeated identical queries while the underlying dataset is unchanged.
- No regression in exact-match ranking order within a page.

---

## 4. Virtualized transcript — infinite-scroll abstraction

### Problem

`EvidenceTranscriptModel.load_messages` holds every message body. `Gen2TranscriptSurfaceWidget._reflow` computes layout for all rows. Large threads freeze the app.

### Requirement

User experience: **feels infinitely scrollable** through a thread of any size. Implementation: **windowed data + windowed layout**.

### Architecture

#### 4.1 Data layer

- `TranscriptDataSource` (new abstraction):
  - `message_count(thread_id) -> int`
  - `fetch_messages(thread_id, start_index, count) -> list[Message]` — SQL `LIMIT/OFFSET` or keyset on `(timestamp, sort_index, message_id)`
  - `fetch_evidence_blocks(thread_id) -> list[EvidenceBlock]` — small cardinality; can load whole list
  - `fetch_block_highlights(block_ids) -> dict` — **one batched query** (item 10)

#### 4.2 Model layer

- `EvidenceTranscriptModel` holds only:
  - Visible window messages (e.g. current ± buffer of 100 rows)
  - Block overlay metadata for visible range + active block
  - Slot/boundary state for active evidence block editing

#### 4.3 View layer

- Replace full-thread reflow with:
  - **Estimated row heights** (cache measured heights per message_id)
  - **Total scroll extent** = sum of cached/estimated heights
  - On scroll: fetch and layout rows entering viewport + overscan buffer
  - Recycle row widgets (Qt list view pattern or custom viewport similar to `QAbstractItemView` virtualization)

#### 4.4 Evidence block editing

- Boundary drag, highlight toggles, and overlay persistence operate on **message_id + slot indices**, not row array indices in a full thread list.
- Persist overlay edits to DB on debounced timer (existing behavior) — must not require full thread in memory.

#### 4.5 Printable / export paths

- Unaffected — they load bounded evidence-block ranges via slots, not the transcript widget model.

### Acceptance criteria

- Thread with 50,000 messages: app remains responsive; memory stable (no linear growth with scroll depth beyond cache).
- Scroll to message_id (evidence block selection, citation navigation) lands correctly within 500ms on fixture scaled to 10k+ messages (perf test).
- All existing evidence-block editing tests pass or are updated for virtualized indices.

---

## 5. Streaming JSONL import

### Problem

`_read_jsonl` loads entire `source_threads.jsonl` and `messages.jsonl` into Python lists before insert.

### Requirement

- Stream line-by-line from disk.
- Validate required fields per line; fail with file + line number (keep current error quality).
- **Batched inserts:** `executemany` in chunks of e.g. 1000 rows with commit per chunk.
- Progress callback: `(phase, lines_read, lines_written)` for the Load Dataset tab (item 9).

### Post-import indexes

- FTS / spellfix / session rebuild: run **after** import completes, narrated on the Load Dataset tab (not silent).
- Consider marking indexes “stale” and rebuilding in background — but for this phase, synchronous rebuild is acceptable if narrated; streaming import is the priority.

### Acceptance criteria

- Peak memory during import does not scale with total message count (only batch size).
- Import 100k-line fixture without OOM on a typical analyst machine.

---

## 6. Analysis payloads vs full provenance — reference model

### Question

Can we strip metadata from LLM/analysis payloads as long as message IDs resolve back to full source data for provenance?

### Answer: **Yes — that is the intended architecture.** But today there is a bug.

### Canonical rule

| Layer | Contents | Metadata |
|-------|----------|------------|
| **Canonical store** (`message`, `source_thread`, `source_metadata_json`, `metadata_json`) | Full donor fields | Complete |
| **Analysis / LLM payload** (transcript serialization, window scan text) | `message_id`, `timestamp`, `sender_display`, `body` (and thread header) | **Minimal by design** — saves tokens |
| **Provenance / exhibit output** (`load_printable_artifact_context`, provenance ledger) | Resolved from canonical store via IDs | Complete available fields |

### Required fix

- `load_dataset_messages` currently hardcodes `source_metadata_json={}` — **remove this**. Even if analysis serialization omits metadata, loaders must not destroy it if bodies are ever loaded.
- Analysis serializers (`serialize_messages`, window text builders) **continue to omit** `source_metadata_json` from prompt text — intentional token savings.
- Every analysis result that cites `message_id` must be provably joinable:
  ```sql
  SELECT * FROM message WHERE dataset_id = ? AND message_id = ?
  ```
- Provenance builders **only** read canonical store, never analysis payloads.

### Optional: analysis view table (future)

Not required now. If needed later: `message_analysis` materialized view with pre-trimmed columns + FK to `message`. Spec note only.

### Acceptance criteria

- Provenance ledger for printable artifacts includes donor fields when present in DB, regardless of conversational code paths.
- Unit test: message with rich `source_metadata_json` → conversational window text does **not** contain hash/file path → provenance ledger **does** contain them.

---

## 7. Remove archaic AnswerSettings fields

Remove entirely from code, settings migration, UI, and tests:

| Field | Reason |
|-------|--------|
| `whole_transcript_max_chars` | Decision is token-based; field unused (`del max_chars`) |
| `max_inspected_sessions` | Never wired |
| `window_target_tokens` | Misleading; actual budget derived from context window |
| `transcript_window_padding` | Hardcoded elsewhere; unused |

### Migration

- `settings.json` on load: strip these keys if present (silent ignore).
- Remove from Settings tab answer form.
- Remove from `AnswerSettings` dataclass.

### Overlap setting

`window_overlap_messages` **stays** — move to `NimSettings` or keep as the sole remaining scan-tuning field under Answer settings with clear label: “Window overlap (messages).”

### Acceptance criteria

- Grep finds zero references to removed field names in production code.
- Settings file round-trips without them.

---

## 8. Context window — single settings value, no defaults, every API call

### Problem

`resolve_model_context` ignores provider metadata and falls back to **8192** when `nim.context_window_tokens <= 0`. This caused catastrophic window fragmentation.

### Product decision (authoritative)

**For all models, for all API calls that participate in context budgeting:**

Use **only** `settings.nim.context_window_tokens` from the Settings page.

- No `DEFAULT_CONTEXT_WINDOW_TOKENS` in live paths.
- No per-model table yet (future).
- No silent fallback.

### Required behavior

1. **Settings validation:** Allow Settings / API keys to save even if `context_window_tokens <= 0`, but block conversational run actions and context-budget readouts with a clear error: "Model context window must be set before using conversational features." Context budget readout shows warning when 0.

2. **`resolve_model_context` rewrite:**
   - Input: `nim_settings.context_window_tokens`
   - If `<= 0`: raise `ConfigurationError` (or return explicit error state) — **never** substitute 8192.
   - Remove `DEFAULT_CONTEXT_WINDOW_TOKENS` usage from budgeting, window planner, conversational answer, settings readout.

3. **All LLM calls** use the same budget derivation for input sizing:
   - Conversational whole-transcript
   - Exhaustive window scan (packing budget)
   - Window merge
   - Session summary (legacy path — unchanged but uses same setting when invoked)
   - Token budget readout on Settings tab

4. **Remove dead ends:** `provider_metadata` parameter on `resolve_model_context` may remain in signature for future per-model table but must not affect behavior. Delete `del provider_metadata` comment implying it’s intentional forever.

5. **`settings.model_metadata` / learned context from API errors:** Do not use for budgeting in this phase. Optional: display read-only in UI “provider reported X” without applying it.

### Acceptance criteria

- Setting context window to 128000 in UI → window planner `per_call_input_budget` reflects 128000 minus overhead.
- Setting to 0 → conversational actions disabled with clear message; no 8192 anywhere in logs.
- Grep: `DEFAULT_CONTEXT_WINDOW_TOKENS` only in tests or removed entirely.

---

## 9. Startup load tab and dataset load pipeline

### Problem

`app.py` bootstraps synchronously: schema, optional import, main window. Embedding model load and index builds are manual on Settings. Exhaustive scan redundantly rebuilds sessions. Multiple code paths reload the same data.

### New startup flow

#### 9.1 Temporary load tab (main navigation)

Initial app state opens the main navigation shell with a temporary **Load Dataset** tab available alongside Settings. This is not a modal startup dialog.

Purpose:

- Let the user move between Load Dataset and Settings until API keys, model settings, embedding settings, and dataset selection are ready.
- Keep dataset-dependent tabs unavailable or clearly disabled until a dataset load completes successfully.
- Remove the temporary Load Dataset tab after a successful load so normal app navigation is not cluttered.

**Controls (this phase):**

- **Load dataset** button — file picker for normalized donor directory (same contract as today: `dataset.json`, `source_threads.jsonl`, `messages.jsonl`)
- **Status log area** — multi-line, append-only, timestamped narrative
- (Future: “Create workspace from raw export” — disabled / hidden for now)

**No dataset-dependent tabs are usable** until load pipeline completes successfully. Settings remains usable before load.

#### 9.2 Load pipeline (on button click)

Execute in order; narrate each step in status area:

| Step | Action | Notes |
|------|--------|-------|
| 1 | Open/create workspace DB | WAL already enabled |
| 2 | Schema migrate | Idempotent |
| 3 | Stream import dataset (item 5) | Or skip if already loaded and user chose not to reload |
| 4 | Rebuild FTS | Narrate progress |
| 5 | Rebuild spellfix | Narrate |
| 6 | Build transcript sessions (once) | `rebuild_dataset_sessions` — **single place** for session materialization |
| 7 | Ensure default categories / printable artifact groups | Lightweight |
| 8 | **Auto embedding pipeline** (see below) | Previously manual on Settings |
| 9 | Activate dataset-dependent tabs with `AppContext` | Pass `dataset_id`, conn, logger; remove temporary Load Dataset tab |

#### 9.3 Auto embedding on load

Replicate Settings “embedding” workflow automatically after dataset load:

1. Preload embedding model (same as `SettingsTab.start_embedding_model_preload`)
2. Validate sqlite-vec extension
3. Build **message-level** embeddings (resume-aware — item 15)
4. Build **chunk-level** embeddings (resume-aware)
5. Narrate: model name, messages embedded / total, chunks embedded / total, elapsed time, errors

**Settings still expose manual rebuild controls** for re-run after settings change — but first load is automatic.

**Authoritative clarification:** First load should attempt automatic embedding, but embedding readiness is not a hard modal gate. Provide cancel / skip / retry controls during embedding setup and indexing. If embedding fails or is skipped, open the app with embedding-dependent features clearly marked unavailable or stale, and log the exact failure and next action in the Load Dataset tab.

#### 9.4 Redundant loads to eliminate

| Current redundancy | After |
|-------------------|-------|
| `bootstrap_app` import + main window `set_dataset` refresh | Single pipeline on temporary Load Dataset tab |
| Exhaustive scan `rebuild_dataset_sessions` | Removed (item 2) |
| `build_dataset_transcript` for budget | SQL stats (item 1) |
| Per-thread full load in planner + UI | Planner streams thread messages once per planning call; UI uses virtualization (item 4) |

#### 9.5 CLI compatibility

Retain `--dataset`, `--db`, `--reload-dataset` flags: if provided, skip the manual load-tab button and auto-run pipeline (for CI/tests).

#### 9.6 Startup acceptance clarification

- Fresh launch opens the main navigation shell with Load Dataset + Settings available.
- After successful load, dataset-dependent tabs enable and the temporary Load Dataset tab is removed.
- User can navigate to Settings before dataset load to enter API keys and model settings.
- Embedding failure/skip does not strand the user in a dead-end modal state.

### Acceptance criteria

- Fresh launch: main navigation shell opens with Load Dataset + Settings available; after successful load, dataset-dependent tabs enable and the Load Dataset tab is removed.
- Second launch with existing workspace: offer load or open existing (minimal dialog OK for this phase).
- No session rebuild during exhaustive scan.

---

## 10. Search hydration — batch fetch, not caps (addresses audit item 10)

### What was wrong in the audit suggestion

“Add LIMIT 50 to FTS” was rejected — correctly. Caps discard completeness.

### What actually helps

| Issue | Solution | Why it preserves completeness |
|-------|----------|-------------------------------|
| N+1 `SELECT` per hit | Single `WHERE message_id IN (...)` per page | All hits on page hydrated; paginate to next page |
| Loading bodies for all hits at once | Hydrate **current page only** | User can reach every page |
| Embedding top-K | Label as “top K by similarity” | Honest ranking limit, not hidden truncation |

### Implementation

- `repositories.fetch_messages_by_ids(conn, dataset_id, message_ids) -> dict[str, Message]`
- FTS page fetch → collect IDs → one batch query
- Embedding search → same batch hydrate for returned K hits

### Acceptance criteria

- Search page of 200 hits → one batch query (or two if chunking IN clause), not 200 queries.
- Total hit count unchanged from today’s FTS semantics.

---

## 11. Remove `workstation_conversation` legacy domain

### Scope of removal

**Authoritative data decision:** Existing data in legacy workstation-conversation tables is testing-only and does not need preservation. It is acceptable to drop these tables after code removal using `DROP TABLE IF EXISTS` plus a changelog note; no backup/export precheck is required for this phase.

**Delete or deprecate:**

- Tables: `workstation_conversation`, `conversation_hit`, `conversation_range`, `message_highlight_override` — **drop in migration** after code removal (user approved cut; existing EVW files with data in these tables: tables remain empty in practice; migration uses `DROP TABLE IF EXISTS` with note in changelog — **no production UI wrote to these in current app**)

- Repository functions: `create_workstation_conversation_from_search`, `load_output_conversation_context`, range/highlight helpers used only by legacy export

- `export/html_preview.py` and `export/audit_export.py` references to workstation HTML

- `OutputConversationContext`, `WorkstationConversation` models if unused after cut

- Tests exclusively for workstation conversation workflow (keep evidence-block tests)

- Import cleanup in `normalized_loader.py` that deletes workstation rows on reload

**Keep:**

- `evidence_block` + printable artifacts as sole review/export unit

### Acceptance criteria

- No production import of workstation conversation symbols.
- Full pytest green after test migration.
- Smoke checklist has no workstation conversation steps (already updated).

---

## 12. Service layer / client-server split

**Deferred.** No work in this phase. Item 4’s `TranscriptDataSource` and item 9’s pipeline are stepping stones.

---

## 13. Raw donor importers

**Deferred.**

---

## 14. Print preview widget — product-grade page layout

### Problem

Current “preview” is `QLabel` HTML with line-count pagination (`LINES_PER_PAGE = 32`). This is not the product. **Page layout is the reason someone buys the program.**

### Requirement

Replace printable preview right pane with a **true print preview widget** that shows **exactly what will print/export** to PDF.

### Architecture

#### 14.1 Layout engine (non-Qt, reusable)

Extend `output/printable_preview.py` into a real **layout engine**:

- Input: `PrintableArtifactContext`
- Output: `PrintLayoutDocument`:
  - Page size: US Letter default (8.5×11 in), configurable later
  - Margins: fixed spec (e.g. 1 in top/bottom, 0.75 in sides) — constants in one module
  - Font metrics: embedded font family + sizes (title, body, metadata, footer, provenance)
  - **Measure with QFontMetrics equivalent** (in layout engine: accept metrics callback for Qt; pure math for tests)

**Per-page content boxes:**

**Authoritative title rule:** The artifact title appears centered at the top of every printed/exported page.

- Centered artifact title at the top of **every** printed/exported page
- Block section header: `Block A — {title}`
- Per message: metadata line (smaller/lighter), body (wrapped to content width)
- Footer on **every** page: Exhibit / Case / Page X of Y
- Provenance ledger: **after all blocks**, may span multiple pages; never interleaved per block

Pagination: **greedy fill** of measured boxes into page content height — not character line counts.

#### 14.2 Preview widget (Qt)

- `PrintPreviewWidget` using `QGraphicsView` or `QPdfWriter` + `QPrinter` preview pattern:
  - Render each page to a pixmap or PDF page at zoom level
  - Zoom in/out, previous/next page (retain current controls)
  - **Print button** → system print dialog via `QPrinter`
  - **Export PDF** button → write PDF directly (this completes deferred PDF ticket)

#### 14.3 WYSIWYG guarantee

Preview pixels must come from the **same layout function** as PDF export. One code path.

#### 14.4 Delete

- `PrintablePreviewWidget` QLabel/HTML approach
- `LINES_PER_PAGE` / `WRAP_WIDTH` char heuristics as primary pagination

### Acceptance criteria

- Visual: footer on every page; provenance only at end; block labels correct after reorder.
- Print to PDF matches preview at 100% zoom (pixel or vector equivalence).
- Multi-page artifact with long bodies paginates at word wrap boundaries, not arbitrary 32-line chunks.
- Tests: layout engine unit tests on fixed metrics (page break positions deterministic).

---

## 15. Embedding index resume — optimize without gutting

### Current behavior

`_embedded_message_ids` loads all embedded message IDs into a Python `set` for resume.

### Requirement

- **Keep resume semantics:** re-run skips already-embedded messages/chunks.
- **Optimize:**
  - Store embedding index metadata including provider/model ID, embedding dimensions, corpus/index generation, batch completion state, and `last_embedded_message_sort_key` only after a batch commits successfully
  - Resume query may use `SELECT ... FROM message WHERE dataset_id = ? AND (timestamp, message_id) > (?, ?) ORDER BY ...` for the fast path
  - Before relying on the fast path, verify there are no missing embeddings before the checkpoint for the active model/index generation
  - If holes exist, fill holes with an anti-join query before continuing past the checkpoint
  - For chunk embeddings: track `last_chunk_id` similarly
  - Fallback to set-based or anti-join resume if metadata is missing, stale, or incompatible with current model/index settings

### Acceptance criteria

- Interrupt 100k embedding at 60k, resume → continues from ~60k without re-embedding skipped rows.
- Resume does not require loading 100k IDs into RAM (verify with memory test or instrumentation).

---

**Additional embedding resume correctness requirement:** Interrupt during a batch, delete an embedded row, or change embedding model settings; resume must not skip missing or stale embeddings.

## 16. Remove obsolete LLM prompts and paths

### Remove from production

- Prompt template seeds / UI entries: `evidence_range_suggestion`, `conversational_search_planner`, `conversational_search_synthesis` (if unused)
- `llm/types.py` `RANGE_SUGGESTION` enum value if nothing references it
- `task_roles.py` obsolete inventory entries (or move to docs)
- Settings prompt combo entries for deleted run types

### Keep

- Active run types: expansion, research, writing, conversational answer modes, session summary (until session path deleted later), coverage audit (legacy)

### Acceptance criteria

- Grep finds no `range_suggestion` / `RUN_TYPE_RANGE_SUGGESTION` in production code.
- Prompt seed list matches active features only.

---

## 17. Environment variable consolidation

**Deferred.**

---

## 18. Process log — batch summaries, not per-line commits

### Problem

`ProcessLogger.log` commits every insert. Embedding jobs log frequently.

### Requirement

- **Batch mode** for long operations: `ProcessLogger.batch()` context manager accumulates entries; single commit on exit.
- Embedding / import / FTS rebuild use batch mode.
- **Summarize:** one info line per batch completion (“Embedded messages 32000–33000 of 100000, 2.1s”) instead of per-message debug.
- UI live log cap (500) unchanged.
- `fetch_process_logs` limits unchanged for viewer.

### Acceptance criteria

- Embedding 10k messages produces O(batches) log rows, not O(messages).
- Single import transaction does not commit log per line.

---

## 19. HTML preview removal

Part of item 11. Confirm:

- Delete `export/html_preview.py`
- Remove `test_html_export.py` or rewrite for PDF preview
- Audit export may keep JSON/text process logs; no HTML conversation export

---

## Additional high-tier concerns (not yet discussed)

### A. Largest-thread watchdog

On dataset load, SQL: `SELECT source_thread_id, COUNT(*) AS c ... ORDER BY c DESC LIMIT 1`. If `c > threshold` (e.g. 5000), the Load Dataset tab narrates warning: "Thread X has N messages; transcript uses virtualized scrolling."

### B. SQLite single-writer discipline

Background workers use separate connections — good. Document: only one embedding worker at a time; UI reads use same WAL DB. Future server replaces this.

### C. `answer_strategy` auto mode

Still chooses whole-transcript vs exhaustive based on token estimate — after item 1, estimate is SQL-based. Document that “whole transcript” sends **one** LLM call with full serialized dataset — only viable when stats fit budget; otherwise exhaustive. No silent failure.

### D. Donor import format versioning

Add `dataset.json` field `normalized_format_version` — the Load Dataset tab validates before import. Prevents half-migrated donor dumps.

### E. Printable artifact at scale

**Authoritative requirement:** Current code must be audited and corrected so `load_printable_artifact_context` fetches per-block slot ranges only using bounded SQL range/keyset hydration. It must not call `list_messages_for_thread` and then slice the full thread in memory.

Loading context for an artifact with many blocks each spanning large slot ranges may load many messages — acceptable if bounded by evidence block slots, not full threads. Monitor: `load_printable_artifact_context` should load **per-block slot range only** (already uses `message_ids_for_slot_range` — verify never loads full thread per block).

### F. Test strategy for this spec

- Scale fixtures: generate 10k / 100k message JSONL for perf tests (CI optional job).
- Keep unit tests fast; mark `@pytest.mark.scale` for large tests.

---

## Review checklist (for reviewing agent)

- [ ] Context window: zero defaults, settings-only, blocks conversational when unset
- [ ] Budget path: no full dataset load
- [ ] Window packing: minimizes call count; overlap wired; no session rebuild in scan
- [ ] Search: pagination + total count, no silent caps
- [ ] Transcript: virtualized, infinite-scroll UX
- [ ] Import: streaming JSONL
- [ ] Provenance: IDs resolve to canonical store; analysis payloads stay light
- [ ] Four dead settings removed; overlap retained
- [ ] Splash + auto embedding pipeline
- [ ] Workstation conversation + HTML export removed
- [ ] Print preview = real layout + print/PDF
- [ ] Embedding resume optimized
- [ ] Obsolete prompts removed
- [ ] Batch logging

---

## Document history

| Date | Author | Note |
|------|--------|------|
| 2026-06-25 | Audit + product owner review | Initial spec from pre-scale audit |
